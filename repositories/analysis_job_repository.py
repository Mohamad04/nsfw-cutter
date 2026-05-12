from datetime import datetime, timezone

from sqlalchemy.orm import Session

from models.analysis_job import AnalysisJob


def create_job(db: Session, *, video_id: int, user_id: int, status: str = "pending", progress: int | None = 0) -> AnalysisJob:
    job = AnalysisJob(video_id=video_id, user_id=user_id, status=status, progress=progress)
    db.add(job)
    db.flush()
    return job


def update_job_status(db: Session, job_id: int, status: str) -> AnalysisJob | None:
    job = db.get(AnalysisJob, job_id)
    if job is None:
        return None
    job.status = status
    if status == "processing" and job.started_at is None:
        job.started_at = datetime.now(timezone.utc)
    db.flush()
    return job


def update_job_progress(db: Session, job_id: int, progress: int) -> AnalysisJob | None:
    job = db.get(AnalysisJob, job_id)
    if job is None:
        return None
    job.progress = progress
    db.flush()
    return job


def mark_job_completed(db: Session, job_id: int) -> AnalysisJob | None:
    job = db.get(AnalysisJob, job_id)
    if job is None:
        return None
    job.status = "completed"
    job.progress = 100
    job.finished_at = datetime.now(timezone.utc)
    db.flush()
    return job


def mark_job_failed(db: Session, job_id: int, error_message: str) -> AnalysisJob | None:
    job = db.get(AnalysisJob, job_id)
    if job is None:
        return None
    job.status = "failed"
    job.error_message = error_message
    job.finished_at = datetime.now(timezone.utc)
    db.flush()
    return job
