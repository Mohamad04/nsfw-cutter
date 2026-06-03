from dataclasses import dataclass, field


@dataclass
class AppState:
    video_url: str = ""
    video_name: str = "No video selected"
    subtitle_status: str = "Subtitle: not detected"
    subtitle_detection_state: str = "idle"
    subtitle_candidates: list = field(default_factory=list)
    subtitle_error: str = ""
    subtitle_active_job_token: str = ""
    subtitle_active_media_path: str = ""
    selected_analysis_subtitle_id: str = ""
    selected_analysis_subtitle: dict | None = None
    analysis_subtitle_auto_selected: bool = False
    player_subtitle_track_count: int = 0
    active_preview_subtitle_track_index: int = -1
    project_status: str = "Ready"
    current_folder: str = ""
    available_videos: list = field(default_factory=list)
    selected_video_path: str = ""
    export_busy: bool = False
    export_progress: int = 0
    export_status: str = "No export running"
    backend_preparation_busy: bool = False
    backend_preparation_progress: int = 0
    backend_preparation_status: str = "No backend preparation running"
    current_export_job_id: str = ""
    current_export_job_json_path: str = ""
