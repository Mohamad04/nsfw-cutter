from services.analysis.cancellation import CancellationToken
from services.analysis.contracts import AnalysisRunRequest
from services.analysis.pipeline import AnalysisPipeline


class AnalysisService:
    """Small application-facing facade for the local-first analysis pipeline."""

    def __init__(self, pipeline: AnalysisPipeline | None = None) -> None:
        self.pipeline = pipeline or AnalysisPipeline()

    def analyze(
        self,
        request: AnalysisRunRequest,
        cancellation: CancellationToken | None = None,
        progress_callback=None,
        event_callback=None,
        *,
        job_id: str | None = None,
    ) -> dict:
        record = self.pipeline.run(
            request,
            cancellation,
            progress_callback,
            event_callback=event_callback,
            job_id=job_id,
        )
        return record.model_dump(mode="json")
