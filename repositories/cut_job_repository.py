from sqlalchemy.orm import Session

from models.cut_job import CutJob, CutJobSegment
from schemas._validation import utc_now
from schemas.video_cut_schema import VideoCutRequest, VideoCutResult


def create_job(db: Session, request: VideoCutRequest) -> CutJob:
    job = CutJob(
        input_video_path=str(request.input_path),
        export_mode=str(request.export_mode),
        cut_mode=str(request.cut_mode),
        output_dir=str(request.output_dir),
        status="pending",
    )
    job.segments = [
        CutJobSegment(
            segment_index=segment.index,
            start_seconds=segment.start_seconds,
            end_seconds=segment.end_seconds,
            status="pending",
        )
        for segment in request.segments
    ]
    db.add(job)
    db.flush()
    return job


def mark_running(db: Session, job_id: int) -> CutJob:
    job = _get_job(db, job_id)
    job.status = "running"
    job.started_at = utc_now()
    for segment in job.segments:
        segment.status = "running"
    db.flush()
    return job


def mark_completed(db: Session, job_id: int, result: VideoCutResult) -> CutJob:
    job = _get_job(db, job_id)
    job.status = "completed"
    job.finished_at = utc_now()
    job.merged_output_path = str(result.merged_output_path) if result.merged_output_path else None

    segments_by_index = {segment.segment_index: segment for segment in result.segments}
    for record in job.segments:
        segment_result = segments_by_index.get(record.segment_index)
        if segment_result is None:
            continue
        record.status = "completed"
        record.output_path = str(segment_result.output_path)
        record.error_message = None

    db.flush()
    return job


def mark_failed(db: Session, job_id: int, error_message: str) -> CutJob:
    job = _get_job(db, job_id)
    job.status = "failed"
    job.finished_at = utc_now()
    job.error_message = error_message
    for segment in job.segments:
        if segment.status != "completed":
            segment.status = "failed"
            segment.error_message = error_message
    db.flush()
    return job


def list_recent_jobs(db: Session, limit: int = 20) -> list[CutJob]:
    return db.query(CutJob).order_by(CutJob.created_at.desc(), CutJob.id.desc()).limit(int(limit)).all()


def _get_job(db: Session, job_id: int) -> CutJob:
    job = db.get(CutJob, int(job_id))
    if job is None:
        raise ValueError(f"Cut job does not exist: {job_id}")
    return job
