from collections.abc import Callable
from pathlib import Path
from shutil import copyfile


SUPPORTED_EXPORT_EXTENSIONS = {".mp4", ".mkv"}


def export_lossless_video(
    input_path: str,
    output_path: str,
    progress_callback: Callable[[int, str], None] | None = None,
) -> str:
    def emit(percent: int, message: str) -> None:
        if progress_callback is not None:
            progress_callback(percent, message)

    emit(10, "Validating input...")
    source = Path(input_path).expanduser()
    if not source.exists():
        raise FileNotFoundError(f"Input video does not exist: {source}")
    if not source.is_file():
        raise ValueError(f"Input path is not a file: {source}")
    if source.suffix.lower() not in SUPPORTED_EXPORT_EXTENSIONS:
        raise ValueError("Unsupported video extension. Use .mp4 or .mkv.")

    destination = Path(output_path).expanduser()
    if destination.suffix.lower() not in SUPPORTED_EXPORT_EXTENSIONS:
        raise ValueError("Unsupported output extension. Use .mp4 or .mkv.")
    if source.resolve() == destination.resolve():
        raise ValueError("Output path must be different from input path.")

    emit(30, "Preparing output...")
    destination.parent.mkdir(parents=True, exist_ok=True)

    emit(60, "Writing export...")
    copyfile(source, destination)

    emit(90, "Finalizing export...")
    return str(destination)
