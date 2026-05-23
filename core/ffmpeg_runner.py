import subprocess
from pathlib import Path

from core.config import LOCAL_FFPROBE_PATH


def _resolve_command_executable(executable: str) -> str:
    if executable == "ffprobe" and LOCAL_FFPROBE_PATH.is_file():
        return str(LOCAL_FFPROBE_PATH)
    return executable


def run_command(command: list[str]) -> str:
    if not command:
        raise ValueError("Command must not be empty")

    executable = _resolve_command_executable(command[0])
    resolved_command = [executable, *command[1:]]

    try:
        completed = subprocess.run(
            resolved_command,
            capture_output=True,
            text=True,
            encoding="utf-8",
            check=False,
        )
    except FileNotFoundError as exc:
        raise RuntimeError(f"{Path(command[0]).name} was not found") from exc

    if completed.returncode != 0:
        stderr = completed.stderr.strip() or completed.stdout.strip() or "Unknown command failure"
        raise RuntimeError(f"{Path(command[0]).name} failed: {stderr}")

    return completed.stdout


def ensure_ffprobe_available() -> bool:
    try:
        subprocess.run(
            [_resolve_command_executable("ffprobe"), "-version"],
            capture_output=True,
            text=True,
            encoding="utf-8",
            check=True,
        )
        return True
    except FileNotFoundError as exc:
        raise RuntimeError(
            "ffprobe was not found. Please install FFmpeg and ensure ffprobe is available in PATH."
        ) from exc
    except subprocess.CalledProcessError as exc:
        stderr = exc.stderr.strip() if exc.stderr else "Unable to run ffprobe."
        raise RuntimeError(f"ffprobe is available but failed to run: {stderr}") from exc
