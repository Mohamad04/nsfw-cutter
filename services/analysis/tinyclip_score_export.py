from __future__ import annotations

import json
import math
from pathlib import Path
from typing import Literal

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    ValidationError,
    field_validator,
    model_validator,
)

from core.time_utils import utc_now_iso
from services.analysis.cancellation import CancellationToken
from services.analysis.preflight import FileFingerprintService
from services.analysis.preprocessing import MoviePreprocessingService
from services.analysis.preprocessing_contracts import PreprocessingConfig
from services.analysis.stage1_evaluation import write_json_artifact
from services.analysis.tinyclip_semantic import (
    ExperimentalPromptBank,
    TinyCLIPBatchConsumer,
    TinyCLIPSemanticClassifier,
    TinyCLIPSemanticResult,
)


class TinyCLIPScoreArtifactError(ValueError):
    """An evaluation-only TinyCLIP score artifact is invalid."""


class TinyCLIPScoreVideo(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    filename: str = Field(min_length=1)
    duration_us: int = Field(ge=0)
    fingerprint: str | None = None


class TinyCLIPScoreModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    repo_id: str
    revision: str
    checkpoint_sha256: str = Field(min_length=64, max_length=64)
    torch_version: str
    transformers_version: str
    device: Literal["cpu"]
    dtype: str
    processor_class: str
    tokenizer_class: str
    logit_scale_exp: float = Field(gt=0.0)
    experimental_model: Literal[True] = True
    production_license_cleared: Literal[False] = False

    @field_validator("logit_scale_exp")
    @classmethod
    def finite_logit_scale(cls, value: float) -> float:
        if not math.isfinite(value):
            raise ValueError("TinyCLIP score-artifact logit scale must be finite")
        return value


class TinyCLIPScorePrompt(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    concept_id: str
    text: str


class TinyCLIPScorePromptBank(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    bank_id: str
    version: str
    digest: str = Field(min_length=64, max_length=64)
    prompts: tuple[TinyCLIPScorePrompt, ...]
    experimental: Literal[True] = True
    production_approved: Literal[False] = False


class TinyCLIPScoreValue(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    concept_id: str
    prompt_sha256: str = Field(min_length=64, max_length=64)
    cosine_similarity: float
    scaled_logit: float

    @field_validator("cosine_similarity", "scaled_logit")
    @classmethod
    def finite_score(cls, value: float) -> float:
        if not math.isfinite(value):
            raise ValueError("TinyCLIP score artifacts require finite scores")
        return value


class TinyCLIPScoreSample(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    sample_id: str
    timestamp_us: int = Field(ge=0)
    sample_reasons: tuple[str, ...]
    scores: tuple[TinyCLIPScoreValue, ...]


class TinyCLIPScoreArtifact(BaseModel):
    """Versioned raw-score artifact; deliberately contains no candidate policy."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    schema_version: Literal[1] = 1
    artifact_kind: Literal["tinyclip_semantic_raw_scores"] = (
        "tinyclip_semantic_raw_scores"
    )
    generated_at_utc: str
    video: TinyCLIPScoreVideo
    model: TinyCLIPScoreModel
    prompt_bank: TinyCLIPScorePromptBank
    preprocessing: PreprocessingConfig
    samples: tuple[TinyCLIPScoreSample, ...]

    @model_validator(mode="after")
    def validate_prompt_and_sample_order(self) -> TinyCLIPScoreArtifact:
        concept_order = tuple(
            prompt.concept_id for prompt in self.prompt_bank.prompts
        )
        if not concept_order or len(concept_order) != len(set(concept_order)):
            raise ValueError("TinyCLIP artifact prompt concepts must be non-empty and unique")
        for sample in self.samples:
            if tuple(score.concept_id for score in sample.scores) != concept_order:
                raise ValueError(
                    "TinyCLIP sample score order must match the prompt-bank order"
                )
        return self


def export_tinyclip_scores(
    video_path: str | Path,
    output_path: str | Path,
    *,
    batch_size: int,
    prompt_bank: ExperimentalPromptBank,
    config: PreprocessingConfig | None = None,
    local_files_only: bool = False,
    include_video_fingerprint: bool = True,
    cancellation: CancellationToken | None = None,
    classifier: TinyCLIPSemanticClassifier | None = None,
    preprocessing_service: MoviePreprocessingService | None = None,
    fingerprint_service: FileFingerprintService | None = None,
) -> tuple[TinyCLIPScoreArtifact, Path]:
    resolved_video_path = Path(video_path).expanduser().resolve()
    resolved_output_path = Path(output_path).expanduser().resolve()
    if not resolved_video_path.is_file():
        raise FileNotFoundError(f"Video does not exist: {resolved_video_path}")
    if resolved_video_path == resolved_output_path:
        raise ValueError("TinyCLIP score output must not overwrite the source movie.")
    if batch_size <= 0:
        raise ValueError("TinyCLIP score-export batch size must be positive.")

    cancellation_token = cancellation or CancellationToken()
    resolved_config = config or PreprocessingConfig()
    semantic_classifier = classifier or TinyCLIPSemanticClassifier(
        local_files_only=local_files_only
    )
    consumer = TinyCLIPBatchConsumer(
        semantic_classifier,
        prompt_bank,
        batch_size=batch_size,
    )
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
        raise TinyCLIPScoreArtifactError(
            "TinyCLIP score count does not match representative-frame metadata."
        )
    if not consumer.results:
        raise TinyCLIPScoreArtifactError(
            "No representative TinyCLIP scores were produced; provenance is unavailable."
        )

    samples = tuple(
        _score_sample(result, metadata)
        for result, metadata in zip(consumer.results, representatives, strict=True)
    )
    provenance = consumer.results[0]
    fingerprint = None
    if include_video_fingerprint:
        fingerprint = (fingerprint_service or FileFingerprintService()).fingerprint(
            resolved_video_path,
            cancellation_token,
        )
    artifact = TinyCLIPScoreArtifact(
        generated_at_utc=utc_now_iso(),
        video=TinyCLIPScoreVideo(
            filename=resolved_video_path.name,
            duration_us=preprocessing_result.statistics.movie_duration_us,
            fingerprint=fingerprint,
        ),
        model=TinyCLIPScoreModel(
            repo_id=provenance.model_repository_id,
            revision=provenance.model_revision,
            checkpoint_sha256=provenance.checkpoint_sha256,
            torch_version=provenance.torch_version,
            transformers_version=provenance.transformers_version,
            device=provenance.device,
            dtype=provenance.dtype,
            processor_class=provenance.processor_class,
            tokenizer_class=provenance.tokenizer_class,
            logit_scale_exp=provenance.logit_scale_exp,
        ),
        prompt_bank=TinyCLIPScorePromptBank(
            bank_id=prompt_bank.bank_id,
            version=prompt_bank.version,
            digest=prompt_bank.digest,
            prompts=tuple(
                TinyCLIPScorePrompt(concept_id=prompt.concept_id, text=prompt.text)
                for prompt in prompt_bank.prompts
            ),
        ),
        preprocessing=resolved_config,
        samples=samples,
    )
    return artifact, write_json_artifact(artifact, resolved_output_path)


def load_tinyclip_score_artifact(path: str | Path) -> TinyCLIPScoreArtifact:
    try:
        payload = json.loads(Path(path).read_text(encoding="utf-8"))
        return TinyCLIPScoreArtifact.model_validate(payload)
    except (OSError, json.JSONDecodeError, ValidationError) as exc:
        raise TinyCLIPScoreArtifactError(
            f"Unable to load TinyCLIP score artifact ({type(exc).__name__})."
        ) from exc


def _score_sample(result: TinyCLIPSemanticResult, metadata: object) -> TinyCLIPScoreSample:
    timestamp_us = getattr(metadata, "timestamp_us", None)
    if result.source_timestamp_us != timestamp_us:
        raise TinyCLIPScoreArtifactError(
            "TinyCLIP result order does not match representative timestamps."
        )
    sample_reasons = getattr(metadata, "sample_reasons", ())
    return TinyCLIPScoreSample(
        sample_id=result.sample_id,
        timestamp_us=result.source_timestamp_us,
        sample_reasons=tuple(sorted(reason.value for reason in sample_reasons)),
        scores=tuple(
            TinyCLIPScoreValue(
                concept_id=score.concept_id,
                prompt_sha256=score.prompt_sha256,
                cosine_similarity=score.cosine_similarity,
                scaled_logit=score.scaled_logit,
            )
            for score in result.concept_scores
        ),
    )
