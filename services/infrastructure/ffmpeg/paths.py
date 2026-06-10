import shutil
import sys
from pathlib import Path

from core.paths import PROJECT_ROOT


VENDOR_FFMPEG_BIN = Path("vendor") / "ffmpeg" / "bin"


class FFmpegNotFoundError(RuntimeError):
    pass


def get_ffmpeg_path() -> Path:
    return find_executable("ffmpeg")


def get_ffprobe_path() -> Path:
    return find_executable("ffprobe")


def find_executable(name: str) -> Path:
    executable_name = _windows_executable_name(name)

    for root in _runtime_roots():
        candidate = root / VENDOR_FFMPEG_BIN / executable_name
        if candidate.is_file():
            return candidate

    for system_name in _system_binary_names(executable_name):
        system_binary = shutil.which(system_name)
        if system_binary:
            return Path(system_binary)

    raise FFmpegNotFoundError(_missing_binary_message(executable_name))


def _runtime_roots() -> tuple[Path, ...]:
    roots: list[Path] = []

    pyinstaller_root = getattr(sys, "_MEIPASS", None)
    if pyinstaller_root:
        _append_unique(roots, Path(pyinstaller_root))

    if getattr(sys, "frozen", False):
        executable_dir = Path(sys.executable).resolve().parent
        _append_unique(roots, executable_dir)
        _append_unique(roots, executable_dir / "_internal")

    _append_unique(roots, PROJECT_ROOT)
    return tuple(roots)


def _append_unique(roots: list[Path], root: Path) -> None:
    normalized = root.resolve()
    if normalized not in roots:
        roots.append(normalized)


def _windows_executable_name(name: str) -> str:
    executable = Path(name).name
    if executable.lower().endswith(".exe"):
        return executable
    return f"{executable}.exe"


def _system_binary_names(executable_name: str) -> tuple[str, ...]:
    stem = executable_name[:-4] if executable_name.lower().endswith(".exe") else executable_name
    return (executable_name, stem)


def _missing_binary_message(executable_name: str) -> str:
    binary_label = "FFmpeg" if executable_name.lower().startswith("ffmpeg") else "ffprobe"
    return (
        f"{binary_label} executable was not found. Expected bundled binary at "
        f"{VENDOR_FFMPEG_BIN / executable_name} relative to the app bundle, or install "
        "FFmpeg so ffmpeg.exe and ffprobe.exe are available on PATH."
    )
