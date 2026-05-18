# Codex Task — Introduce Background Job Execution System

## Objective

Introduce a safe parallel execution mechanism in the desktop app so the **main Qt/QML thread remains responsible only for the UI**, while backend/heavy tasks run in worker threads.

This is required before adding heavy features such as video export, video generation, FFmpeg processing, scanning folders, subtitle detection, database writes, or future AI/ML analysis.

The implementation must use:

- `QThreadPool`
- `QRunnable`
- Qt `Signal` / `Slot` communication
- a lock/job registry mechanism to prevent duplicate processing
- QML-bound properties for progress, status, and busy state
- tests proving that duplicate jobs are blocked and UI-facing state is updated safely

---

## Current project assumptions

The project already has a PySide6/QML structure with a Python controller exposed to QML.

Known existing concepts:

- `Main.qml`
- an `AppController` or similar controller class
- QML UI panels/buttons
- Python/QML bridge using `QObject`, `Signal`, `Slot`, and `Property`
- basic video selection logic
- SQLAlchemy ORM started but not fully connected yet

Do **not** rewrite the whole project.

Inspect the existing structure first, then adapt the following design to the actual filenames and directories.

---

## Core rule

The UI thread must never run heavy backend work directly.

Bad pattern:

```python
@Slot()
def generateVideo(self):
    run_ffmpeg_or_heavy_processing()  # blocks the UI
```

Required pattern:

```python
@Slot()
def generateVideo(self):
    create_worker()
    connect_worker_signals()
    submit_worker_to_thread_pool()
```

---

## Required architecture

Implement or adapt this structure:

```text
app/
  controllers/
    app_controller.py

  core/
    job_registry.py

  workers/
    worker_signals.py
    video_export_worker.py

  services/
    video_export_service.py
```

If the project uses different folder names, keep the existing convention, but preserve the same responsibilities.

---

## Responsibility split

### 1. QML

QML should only:

- call controller slots
- display progress/status
- disable buttons while a job is running
- never know about `QThreadPool`, `QRunnable`, FFmpeg, SQLAlchemy, or locks

Example expected QML behavior:

```qml
Button {
    text: controller.exportBusy ? "Exporting..." : "Generate Video"
    enabled: !controller.exportBusy
    onClicked: controller.startLosslessExport()
}

ProgressBar {
    visible: controller.exportBusy
    value: controller.exportProgress / 100
}

Text {
    text: controller.exportStatus
}
```

Adapt the QML to the existing design instead of replacing the whole UI.

---

### 2. AppController

The controller should:

- own or access a `QThreadPool`
- expose QML properties:
  - `exportBusy: bool`
  - `exportProgress: int`
  - `exportStatus: str`
- expose a QML slot to start the backend task
- create the worker
- connect worker signals to controller slots
- update QML-facing properties only from controller slots
- prevent duplicate actions using the job registry

Required controller properties:

```python
exportBusy: bool
exportProgress: int
exportStatus: str
```

Required controller signals:

```python
exportBusyChanged = Signal()
exportProgressChanged = Signal()
exportStatusChanged = Signal()
```

Required behavior:

- When a job starts:
  - `exportBusy = True`
  - `exportProgress = 0`
  - `exportStatus = "Preparing export..."`
- When progress is emitted:
  - update `exportProgress`
  - update `exportStatus`
- When finished:
  - `exportBusy = False`
  - `exportProgress = 100`
  - status should mention the output path/result
- When failed:
  - `exportBusy = False`
  - status should contain a useful error message
- In all cases:
  - the job must be removed from the running job registry

---

### 3. JobRegistry

Create a small lock-protected registry to prevent duplicate backend jobs.

Suggested file:

```text
app/core/job_registry.py
```

Expected behavior:

```python
registry.try_start(job_key) -> bool
registry.finish(job_key) -> None
registry.is_running(job_key) -> bool
```

Implementation requirements:

- Use `threading.Lock` or `threading.RLock`
- Protect a private `set[str]` of running job keys
- `try_start(job_key)` must be atomic
- `finish(job_key)` must be safe even if the job was already removed
- Do not allow the same job key twice

Example:

```python
from threading import RLock


class JobRegistry:
    def __init__(self):
        self._lock = RLock()
        self._running_jobs: set[str] = set()

    def try_start(self, job_key: str) -> bool:
        with self._lock:
            if job_key in self._running_jobs:
                return False
            self._running_jobs.add(job_key)
            return True

    def finish(self, job_key: str) -> None:
        with self._lock:
            self._running_jobs.discard(job_key)

    def is_running(self, job_key: str) -> bool:
        with self._lock:
            return job_key in self._running_jobs
```

---

### 4. WorkerSignals

Create a reusable signal container.

Suggested file:

```text
app/workers/worker_signals.py
```

Expected signals:

```python
from PySide6.QtCore import QObject, Signal


class WorkerSignals(QObject):
    progress = Signal(str, int, str)   # job_key, percentage, message
    finished = Signal(str, object)     # job_key, result
    error = Signal(str, str)           # job_key, error message
```

Optional later:

```python
cancelled = Signal(str)
```

Do not add cancellation unless it can be implemented correctly.

---

### 5. VideoExportWorker

Create a worker that runs in the thread pool.

Suggested file:

```text
app/workers/video_export_worker.py
```

Expected behavior:

- subclass `QRunnable`
- receive all required data in `__init__`
- own a `WorkerSignals` instance
- run backend logic inside `run()`
- emit progress updates
- emit `finished` on success
- emit `error` on failure
- never touch QML objects directly
- never mutate controller properties directly

Example shape:

```python
from PySide6.QtCore import QRunnable, Slot

from app.workers.worker_signals import WorkerSignals
from app.services.video_export_service import export_lossless_video


class VideoExportWorker(QRunnable):
    def __init__(self, job_key: str, input_path: str, output_path: str):
        super().__init__()
        self.job_key = job_key
        self.input_path = input_path
        self.output_path = output_path
        self.signals = WorkerSignals()

    @Slot()
    def run(self):
        try:
            self.signals.progress.emit(self.job_key, 0, "Starting export...")

            result = export_lossless_video(
                input_path=self.input_path,
                output_path=self.output_path,
                progress_callback=lambda percent, message: self.signals.progress.emit(
                    self.job_key,
                    percent,
                    message,
                ),
            )

            self.signals.progress.emit(self.job_key, 100, "Export completed")
            self.signals.finished.emit(self.job_key, result)

        except Exception as exc:
            self.signals.error.emit(self.job_key, str(exc))
```

---

### 6. VideoExportService

Create or prepare a service layer for backend work.

Suggested file:

```text
app/services/video_export_service.py
```

For now, this service may contain a placeholder/safe implementation if real FFmpeg integration is not ready yet.

However, the service must be designed so that later we can implement lossless FFmpeg export using:

```bash
ffmpeg -i input.mp4 -c copy output.mp4
```

or segment export using:

```bash
ffmpeg -ss START -to END -i input.mp4 -c copy output.mp4
```

Basic expected service API:

```python
def export_lossless_video(
    input_path: str,
    output_path: str,
    progress_callback=None,
) -> str:
    ...
```

Requirements:

- Validate that input exists
- Validate supported extensions: `.mp4`, `.mkv`
- Ensure output directory exists
- Raise clear exceptions on failure
- Return the output path as a string

If FFmpeg is implemented now:

- use `subprocess.Popen` or `subprocess.run`
- capture stderr for errors
- never block the UI thread directly
- no direct QML calls

If progress percentage cannot be accurately calculated yet, emit coarse progress:

```text
0%   Starting
10%  Validating input
30%  Running FFmpeg
90%  Finalizing
100% Done
```

Do not fake precise FFmpeg progress unless duration/progress parsing is actually implemented.

---

## Controller integration example

Adapt this to the existing controller.

```python
from PySide6.QtCore import QObject, Signal, Slot, Property, QThreadPool

from app.core.job_registry import JobRegistry
from app.workers.video_export_worker import VideoExportWorker


class AppController(QObject):
    exportBusyChanged = Signal()
    exportProgressChanged = Signal()
    exportStatusChanged = Signal()

    def __init__(self):
        super().__init__()
        self._thread_pool = QThreadPool.globalInstance()
        self._thread_pool.setMaxThreadCount(2)
        self._job_registry = JobRegistry()

        self._export_busy = False
        self._export_progress = 0
        self._export_status = "No export running"

    @Property(bool, notify=exportBusyChanged)
    def exportBusy(self):
        return self._export_busy

    @Property(int, notify=exportProgressChanged)
    def exportProgress(self):
        return self._export_progress

    @Property(str, notify=exportStatusChanged)
    def exportStatus(self):
        return self._export_status

    @Slot(str, str)
    def startLosslessExport(self, input_path: str, output_path: str):
        job_key = f"export:{input_path}:{output_path}"

        if not self._job_registry.try_start(job_key):
            self._set_export_status("This export is already running.")
            return

        self._set_export_busy(True)
        self._set_export_progress(0)
        self._set_export_status("Preparing export...")

        worker = VideoExportWorker(
            job_key=job_key,
            input_path=input_path,
            output_path=output_path,
        )

        worker.signals.progress.connect(self._on_export_progress)
        worker.signals.finished.connect(self._on_export_finished)
        worker.signals.error.connect(self._on_export_error)

        self._thread_pool.start(worker)

    @Slot(str, int, str)
    def _on_export_progress(self, job_key: str, percentage: int, message: str):
        self._set_export_progress(percentage)
        self._set_export_status(message)

    @Slot(str, object)
    def _on_export_finished(self, job_key: str, result):
        self._job_registry.finish(job_key)
        self._set_export_progress(100)
        self._set_export_status(f"Export completed: {result}")
        self._set_export_busy(False)

    @Slot(str, str)
    def _on_export_error(self, job_key: str, error_message: str):
        self._job_registry.finish(job_key)
        self._set_export_status(f"Export failed: {error_message}")
        self._set_export_busy(False)

    def _set_export_busy(self, value: bool):
        if self._export_busy != value:
            self._export_busy = value
            self.exportBusyChanged.emit()

    def _set_export_progress(self, value: int):
        value = max(0, min(100, int(value)))
        if self._export_progress != value:
            self._export_progress = value
            self.exportProgressChanged.emit()

    def _set_export_status(self, value: str):
        if self._export_status != value:
            self._export_status = value
            self.exportStatusChanged.emit()
```

---

## SQLAlchemy thread rule

If the worker needs database access later:

- do not share a global SQLAlchemy `Session` between the UI thread and worker threads
- create a new session inside the worker/service
- commit/rollback/close it inside the same worker execution

Expected pattern:

```python
with SessionLocal() as session:
    # worker-specific database operations
    session.commit()
```

Do not implement database writes in this task unless they already exist and need safe integration.

---

## QML UI requirements

Update the existing QML with minimal changes.

Required behavior:

1. The export/generate button becomes disabled while export is running.
2. A progress bar or progress text is visible during the job.
3. A status label shows messages from the worker.
4. The UI remains responsive while the worker is running.
5. Repeated clicking must not start duplicate jobs.

Example QML pattern:

```qml
Button {
    id: generateButton
    text: controller.exportBusy ? "Generating..." : "Generate Video"
    enabled: !controller.exportBusy
    onClicked: {
        controller.startLosslessExport(selectedInputPath, selectedOutputPath)
    }
}

ProgressBar {
    visible: controller.exportBusy
    value: controller.exportProgress / 100
}

Text {
    text: controller.exportStatus
}
```

Adapt names and layout to the current `Main.qml`.

Do not redesign the whole interface.

---

## Error handling requirements

Every worker job must handle exceptions.

Required on failure:

- emit `error(job_key, message)`
- remove job from registry
- set busy to false
- keep UI usable
- show meaningful message in `exportStatus`

Do not allow a failed worker to leave the UI stuck in busy mode.

---

## Testing requirements

Add tests using the existing test setup. If no test setup exists, add a minimal `pytest` setup.

Required tests:

### 1. JobRegistry duplicate prevention

Test that:

- first `try_start("job1")` returns `True`
- second `try_start("job1")` returns `False`
- after `finish("job1")`, `try_start("job1")` returns `True`

Suggested test:

```python
def test_job_registry_prevents_duplicate_jobs():
    registry = JobRegistry()

    assert registry.try_start("job1") is True
    assert registry.try_start("job1") is False

    registry.finish("job1")

    assert registry.try_start("job1") is True
```

---

### 2. Service input validation

Test that:

- unsupported file extension raises `ValueError`
- missing input file raises `FileNotFoundError`
- supported `.mp4` / `.mkv` path is accepted if test fixture exists

---

### 3. Controller duplicate blocking

Test that when a job key is already running, calling the start slot again does not start a second worker.

This can be tested by mocking the thread pool or mocking `VideoExportWorker` creation.

---

### 4. Worker signal behavior

If feasible, test that the worker emits either:

- `finished` on success
- or `error` on failure

Do not make tests depend on a real heavy FFmpeg execution unless FFmpeg is already required by the project.

Use a fake service/mocking where appropriate.

---

## Acceptance criteria

The task is complete only if all conditions are satisfied:

- [ ] The app has a reusable background worker mechanism.
- [ ] Heavy backend work is not executed directly inside QML/controller click slots.
- [ ] `QThreadPool` is used to run backend tasks.
- [ ] A `QRunnable` worker is implemented.
- [ ] Worker communicates with controller using signals.
- [ ] Worker does not directly modify QML/UI.
- [ ] Controller exposes `exportBusy`, `exportProgress`, and `exportStatus` to QML.
- [ ] QML disables the generate/export button while a job is running.
- [ ] Duplicate clicks do not start duplicate jobs.
- [ ] Job cleanup happens on success and failure.
- [ ] Tests cover the job registry and main failure/duplicate cases.
- [ ] Existing app behavior still works.
- [ ] Existing UI style is preserved.

---

## Important constraints

Do not:

- rewrite the whole UI
- replace PySide6/QML with another framework
- call backend heavy logic directly from the UI thread
- update QML components directly from a worker thread
- share SQLAlchemy sessions between threads
- introduce unnecessary dependencies
- fake exact FFmpeg progress if it is not actually implemented

Do:

- keep changes incremental
- preserve existing project structure where possible
- add clear comments where concurrency matters
- keep worker code isolated from UI code
- keep service code isolated from worker/threading code
- make sure the app never remains stuck in busy state after an exception

---

## Suggested implementation order for Codex

1. Inspect the current project tree.
2. Locate the existing controller and QML entry point.
3. Add `JobRegistry`.
4. Add `WorkerSignals`.
5. Add `VideoExportWorker`.
6. Add or prepare `VideoExportService`.
7. Integrate the controller with `QThreadPool`.
8. Expose `exportBusy`, `exportProgress`, and `exportStatus` to QML.
9. Update QML button/progress/status bindings.
10. Add tests.
11. Run tests.
12. Run the app manually and verify the UI does not freeze.

---

## Final report expected from Codex

After implementation, report:

1. Files created
2. Files modified
3. How to run tests
4. How to manually verify the feature
5. Any limitations left, especially regarding real FFmpeg progress or cancellation

