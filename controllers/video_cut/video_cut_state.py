from dataclasses import dataclass, field


@dataclass
class VideoCutState:
    cut_busy: bool = False
    cut_status: str = "Video export idle"
    cut_progress_value: int = 0
    cut_error: str = ""
    cut_details: str = ""
    cut_warning: str = ""
    cut_output_paths: list[str] = field(default_factory=list)
