from sqlalchemy.orm import Session

from models.export_job import ExportJob


def create_export_job(db: Session, job_data: dict) -> ExportJob:
    record = ExportJob(
        job_id=job_data["job_id"],
        job_type=job_data["job_type"],
        status=job_data["status"],
        progress=job_data["progress"],
        input_video_path=job_data["input_video"]["path"],
        output_path=job_data["output"]["path"],
        export_mode=job_data["export_settings"]["mode"],
        reencode=job_data["export_settings"]["reencode"],
        subtitle_action=job_data["subtitle_policy"]["action"],
        selected_external_subtitle_path=job_data["subtitle_policy"]["selected_external_subtitle_path"],
        settings_json=job_data["export_settings"],
        segments_json=job_data["segments"],
        result_json=job_data["result"],
        full_job_json=job_data,
        error_message=job_data["result"].get("error_message"),
    )
    db.add(record)
    db.flush()
    return record
