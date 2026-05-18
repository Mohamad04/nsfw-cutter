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
