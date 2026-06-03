import logging

from database.session import SessionLocal
from repositories.cut_job_repository import create_job, mark_completed, mark_failed, mark_running
from schemas.video_cut_schema import VideoCutRequest
from services.editing.cut_execution_service import CutExecutionService


logger = logging.getLogger(__name__)


def run_video_cut_job(request_data: dict, progress_callback=None, service_factory=CutExecutionService) -> dict:
    request = VideoCutRequest.model_validate(request_data)

    with SessionLocal() as db:
        job = create_job(db, request)
        db.commit()
        job_id = job.id

    _emit(progress_callback, 0, "Fast cut job created")
    logger.info("Fast cut job started: id=%s input=%s", job_id, request.input_path)

    try:
        with SessionLocal() as db:
            mark_running(db, job_id)
            db.commit()

        result = service_factory().export_segments(request, progress_callback=progress_callback)

        with SessionLocal() as db:
            mark_completed(db, job_id, result)
            db.commit()

        logger.info("Fast cut job completed: id=%s outputs=%s", job_id, result.output_paths)
        return {
            "job_id": job_id,
            "result": result.model_dump(mode="json"),
        }
    except Exception as exc:
        with SessionLocal() as db:
            mark_failed(db, job_id, str(exc))
            db.commit()
        logger.exception("Fast cut job failed: id=%s", job_id)
        raise


def _emit(progress_callback, percentage: int, message: str) -> None:
    if progress_callback is not None:
        progress_callback(percentage, message)
