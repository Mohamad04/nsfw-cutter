from sqlalchemy.orm import Session

from models.subtitle_info import SubtitleInfo


def create_subtitle_info(db: Session, video_file_id: int, subtitle_info: dict) -> SubtitleInfo:
    policy = subtitle_info["policy"]
    record = SubtitleInfo(
        video_file_id=video_file_id,
        embedded_subtitles_detected=policy["embedded_subtitles_detected"],
        embedded_count=policy["embedded_count"],
        external_subtitles_detected=policy["external_subtitles_detected"],
        external_count=policy["external_count"],
        selected_external_subtitle_path=policy["selected_external_subtitle_path"],
        subtitle_action=policy["action"],
        reason=policy["reason"],
        embedded_streams_json=subtitle_info["embedded_streams"],
        external_subtitles_json=subtitle_info["external_subtitles"],
    )
    db.add(record)
    db.flush()
    return record
