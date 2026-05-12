from sqlalchemy.orm import Session

from models.detection_result import DetectionResult


def add_detection_result(
    db: Session,
    *,
    job_id: int,
    video_id: int,
    start_ms: int,
    end_ms: int,
    label: str,
    confidence: float | None = None,
    model_name: str | None = None,
) -> DetectionResult:
    result = DetectionResult(
        job_id=job_id,
        video_id=video_id,
        start_ms=start_ms,
        end_ms=end_ms,
        label=label,
        confidence=confidence,
        model_name=model_name,
    )
    db.add(result)
    db.flush()
    return result


def get_detection_results_by_video(db: Session, video_id: int) -> list[DetectionResult]:
    return db.query(DetectionResult).filter(DetectionResult.video_id == video_id).order_by(DetectionResult.start_ms).all()


def get_detection_results_by_job(db: Session, job_id: int) -> list[DetectionResult]:
    return db.query(DetectionResult).filter(DetectionResult.job_id == job_id).order_by(DetectionResult.start_ms).all()


def filter_results_by_label(db: Session, label: str) -> list[DetectionResult]:
    return db.query(DetectionResult).filter(DetectionResult.label == label.strip()).order_by(DetectionResult.start_ms).all()


def filter_results_by_confidence_threshold(db: Session, threshold: float) -> list[DetectionResult]:
    return (
        db.query(DetectionResult)
        .filter(DetectionResult.confidence.isnot(None), DetectionResult.confidence >= float(threshold))
        .order_by(DetectionResult.confidence.desc())
        .all()
    )
