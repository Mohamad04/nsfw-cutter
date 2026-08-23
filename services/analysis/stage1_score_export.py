from __future__ import annotations

from pathlib import Path

from core.time_utils import utc_now_iso
from services.analysis.cancellation import CancellationToken
from services.analysis.preflight import FileFingerprintService
from services.analysis.preprocessing import MoviePreprocessingService
from services.analysis.preprocessing_contracts import PreprocessingConfig
from services.analysis.stage1_evaluation import (
    Stage1EvaluationDataError,
    Stage1ScoreArtifact,
    Stage1ScoreModel,
    Stage1ScoreSample,
    Stage1ScoreVideo,
    write_json_artifact,
)
from services.analysis.stage1_safety import (
    MODEL_REPOSITORY_ID,
    MODEL_REVISION,
    ONNXSafetySessionFactory,
    ResolvedSafetyModelArtifact,
    SafetyModelArtifactResolver,
    SafetyONNXSession,
    Stage1BatchConsumer,
    Stage1SafetyClassifier,
)


def export_stage1_scores(
    video_path: str | Path,
    output_path: str | Path,
    *,
    batch_size: int,
    config: PreprocessingConfig | None = None,
    local_files_only: bool = False,
    include_video_fingerprint: bool = True,
    cancellation: CancellationToken | None = None,
    artifact_resolver: SafetyModelArtifactResolver | None = None,
    session_factory: ONNXSafetySessionFactory | None = None,
    preprocessing_service: MoviePreprocessingService | None = None,
    fingerprint_service: FileFingerprintService | None = None,
) -> tuple[Stage1ScoreArtifact, Path]:
    """Run preprocessing and Stage 1 once, then atomically persist raw scores."""
    resolved_video_path = Path(video_path).expanduser().resolve()
    resolved_output_path = Path(output_path).expanduser().resolve()
    if not resolved_video_path.is_file():
        raise FileNotFoundError(f"Video does not exist: {resolved_video_path}")
    if resolved_video_path == resolved_output_path:
        raise ValueError("Stage-1 score output must not overwrite the source movie.")
    if batch_size <= 0:
        raise ValueError("Stage-1 score-export batch size must be positive.")

    cancellation_token = cancellation or CancellationToken()
    cancellation_token.raise_if_cancelled()
    resolver = artifact_resolver or SafetyModelArtifactResolver()
    artifact = resolver.resolve(local_files_only=local_files_only)
    session = (session_factory or ONNXSafetySessionFactory()).create(artifact)
    classifier = Stage1SafetyClassifier(
        artifact_resolver=_ResolvedArtifactResolver(artifact),
        session_factory=_ResolvedSessionFactory(session),
    )
    consumer = Stage1BatchConsumer(classifier, batch_size=batch_size)
    resolved_config = config or PreprocessingConfig()
    preprocessing_result = (
        preprocessing_service or MoviePreprocessingService()
    ).preprocess(
        resolved_video_path,
        config=resolved_config,
        cancellation=cancellation_token,
        representative_callback=consumer,
    )
    cancellation_token.raise_if_cancelled()
    representatives = preprocessing_result.representative_frames
    if len(consumer.results) != len(representatives):
        raise Stage1EvaluationDataError(
            "Stage-1 score count does not match representative-frame metadata."
        )

    samples: list[Stage1ScoreSample] = []
    for result, metadata in zip(consumer.results, representatives, strict=True):
        if result.source_timestamp_us != metadata.timestamp_us:
            raise Stage1EvaluationDataError(
                "Stage-1 result order does not match representative-frame timestamps."
            )
        samples.append(
            Stage1ScoreSample(
                sample_id=result.sample_id,
                timestamp_us=result.source_timestamp_us,
                nsfl=result.nsfl_probability,
                nsfw=result.nsfw_probability,
                sfw=result.sfw_probability,
                selected_label=result.selected_label,
                sample_reasons=tuple(sorted(reason.value for reason in metadata.sample_reasons)),
            )
        )

    fingerprint = None
    if include_video_fingerprint:
        fingerprint = (fingerprint_service or FileFingerprintService()).fingerprint(
            resolved_video_path,
            cancellation_token,
        )
    artifact_model = Stage1ScoreArtifact(
        generated_at_utc=utc_now_iso(),
        video=Stage1ScoreVideo(
            filename=resolved_video_path.name,
            duration_us=preprocessing_result.statistics.movie_duration_us,
            fingerprint=fingerprint,
        ),
        model=Stage1ScoreModel(
            repo_id=MODEL_REPOSITORY_ID,
            revision=MODEL_REVISION,
            sha256=artifact.sha256,
            runtime=f"onnxruntime:{session.onnxruntime_version}",
            providers=session.execution_providers,
        ),
        preprocessing=resolved_config,
        samples=tuple(samples),
    )
    return artifact_model, write_json_artifact(artifact_model, resolved_output_path)


class _ResolvedArtifactResolver:
    def __init__(self, artifact: ResolvedSafetyModelArtifact) -> None:
        self.artifact = artifact

    def resolve(self) -> ResolvedSafetyModelArtifact:
        return self.artifact


class _ResolvedSessionFactory:
    def __init__(self, session: SafetyONNXSession) -> None:
        self.session = session

    def create(self, _artifact: ResolvedSafetyModelArtifact) -> SafetyONNXSession:
        return self.session
