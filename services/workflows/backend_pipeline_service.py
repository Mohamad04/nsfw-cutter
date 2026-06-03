from core.config import EXPORT_JOBS_JSON_DIR, METADATA_JSON_DIR, SUBTITLES_JSON_DIR
from core.json_writer import write_json_artifact
from database.session import SessionLocal
from repositories.export_job_repository import create_export_job
from repositories.metadata_repository import create_video_metadata
from repositories.subtitle_repository import create_subtitle_info
from repositories.video_repository import update_video_rows_for_metadata, upsert_video_file
from services.media.metadata_service import get_video_metadata
from services.media.validation_service import validate_input_video
from services.subtitles.discovery_service import find_matching_external_subtitles
from services.subtitles.inspection_service import get_embedded_subtitle_streams
from services.subtitles.policy_service import decide_subtitle_action
from services.workflows.export_job_service import create_export_job_data


def prepare_export_job_pipeline(video_path: str, output_path: str | None = None, progress_callback=None) -> dict:
    def emit(percent: int, message: str) -> None:
        if progress_callback is not None:
            progress_callback(percent, message)

    emit(10, "Validating video")
    validate_input_video(video_path)
    emit(30, "Extracting metadata")
    metadata = get_video_metadata(video_path)
    emit(50, "Inspecting subtitles")
    embedded_streams = get_embedded_subtitle_streams(video_path)
    external_subtitles = find_matching_external_subtitles(video_path)
    subtitle_policy = decide_subtitle_action(embedded_streams, external_subtitles)
    subtitle_info = {
        "video_path": metadata["path"],
        "embedded_streams": embedded_streams,
        "external_subtitles": external_subtitles,
        "policy": subtitle_policy,
    }
    emit(65, "Creating export job")
    export_job = create_export_job_data(metadata, subtitle_policy, output_path)

    with SessionLocal() as session:
        try:
            emit(80, "Persisting SQLite records")
            video_file = upsert_video_file(session, metadata)
            update_video_rows_for_metadata(session, metadata)
            metadata_record = create_video_metadata(session, video_file.id, metadata)
            subtitle_record = create_subtitle_info(session, video_file.id, subtitle_info)
            export_job_record = create_export_job(session, export_job)
            database_ids = {
                "video_file_id": video_file.id,
                "metadata_id": metadata_record.id,
                "subtitle_info_id": subtitle_record.id,
                "export_job_id": export_job_record.id,
            }

            emit(90, "Writing JSON artifacts")
            metadata_json_path = write_json_artifact(metadata, METADATA_JSON_DIR, "metadata", metadata["stem"])
            subtitle_json_path = write_json_artifact(subtitle_info, SUBTITLES_JSON_DIR, "subtitles", metadata["stem"])
            export_job_json_path = write_json_artifact(
                export_job,
                EXPORT_JOBS_JSON_DIR,
                "export_job",
                export_job["job_id"],
            )
            session.commit()
        except Exception:
            session.rollback()
            raise

    return {
        "metadata": metadata,
        "subtitle_info": subtitle_info,
        "export_job": export_job,
        "json_artifacts": {
            "metadata_json_path": metadata_json_path,
            "subtitle_json_path": subtitle_json_path,
            "export_job_json_path": export_job_json_path,
        },
        "database": {
            **database_ids,
        },
    }
