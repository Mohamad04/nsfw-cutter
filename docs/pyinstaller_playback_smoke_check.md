# PyInstaller Playback Smoke Check

Use the normal release build for distribution:

```powershell
./scripts/build_windows.ps1
```

Use a console build when diagnosing playback failures:

```powershell
./scripts/build_windows.ps1 -Console -AppName VideoCutterDebug
```

After building, verify that the generated onedir folder contains Qt runtime files for playback. Depending on PyInstaller/PySide6 layout, these may be under `PySide6\Qt\...` or directly under `PySide6\...`:

```text
dist/VideoCutter/_internal/PySide6/plugins/multimedia/
dist/VideoCutter/_internal/PySide6/plugins/platforms/
dist/VideoCutter/_internal/PySide6/qml/
```

or:

```text
dist/VideoCutter/_internal/PySide6/Qt/plugins/multimedia/
dist/VideoCutter/_internal/PySide6/Qt/plugins/platforms/
dist/VideoCutter/_internal/PySide6/Qt/qml/
```

The build script fails if the multimedia plugin directory, platform plugin directory, or QML runtime directory is missing.

Bundled `ffmpeg.exe` and `ffprobe.exe` are for processing, probing, and cutting videos. They do not replace Qt Multimedia playback plugins required by QML `MediaPlayer`.
