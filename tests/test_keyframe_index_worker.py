import unittest

from workers.keyframe_index_worker import KeyframeIndexWorker


class FakeKeyframeService:
    def __init__(self, result=None, error=None):
        self.result = result or []
        self.error = error
        self.calls = []

    def extract_keyframes(self, input_path):
        self.calls.append(input_path)
        if self.error is not None:
            raise RuntimeError(self.error)
        return self.result


class KeyframeIndexWorkerTests(unittest.TestCase):
    def test_worker_emits_indexed_keyframes_on_success(self):
        service = FakeKeyframeService(result=[0.0, 5.0])
        worker = KeyframeIndexWorker("job-1", "movie.mp4", service)
        finished = []
        errors = []
        worker.signals.finished.connect(lambda token, result: finished.append((token, result)))
        worker.signals.error.connect(lambda token, message: errors.append((token, message)))

        worker.run()

        self.assertEqual(service.calls, ["movie.mp4"])
        self.assertEqual(errors, [])
        self.assertEqual(finished[0][0], "job-1")
        self.assertEqual(finished[0][1]["input_path"], "movie.mp4")
        self.assertEqual(finished[0][1]["keyframes"], [0.0, 5.0])
        self.assertGreaterEqual(finished[0][1]["elapsed_seconds"], 0)

    def test_worker_emits_error_instead_of_raising(self):
        worker = KeyframeIndexWorker(
            "job-1",
            "movie.mp4",
            FakeKeyframeService(error="ffprobe failed"),
        )
        finished = []
        errors = []
        worker.signals.finished.connect(lambda token, result: finished.append((token, result)))
        worker.signals.error.connect(lambda token, message: errors.append((token, message)))

        worker.run()

        self.assertEqual(finished, [])
        self.assertEqual(errors, [("job-1", "ffprobe failed")])


if __name__ == "__main__":
    unittest.main()
