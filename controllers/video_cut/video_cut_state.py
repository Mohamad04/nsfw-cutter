from dataclasses import dataclass


@dataclass
class VideoCutState:
    cut_busy: bool = False
    cut_status: str = "Video export idle"
    cut_progress_value: int = 0
    cut_error: str = ""
    cut_details: str = ""
    cut_warning: str = ""
