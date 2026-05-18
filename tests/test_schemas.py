import unittest

from schemas import AnalysisJobCreateSchema, DetectionResultCreateSchema, UserCreateSchema, VideoCutCreateSchema


class SchemaTests(unittest.TestCase):
    def test_user_schema_normalizes_email(self):
        user = UserCreateSchema(username="tester", email="Tester@Example.com", password="secret-password")
        self.assertEqual(user.email, "tester@example.com")

    def test_video_cut_schema_rejects_invalid_range(self):
        with self.assertRaises(ValueError):
            VideoCutCreateSchema(video_id=1, cut_start_ms=200, cut_end_ms=100)

    def test_analysis_job_schema_rejects_unknown_status(self):
        with self.assertRaises(ValueError):
            AnalysisJobCreateSchema(video_id=1, user_id=1, status="unknown")

    def test_detection_result_schema_rejects_invalid_confidence(self):
        with self.assertRaises(ValueError):
            DetectionResultCreateSchema(job_id=1, video_id=1, start_ms=0, end_ms=100, label="nsfw", confidence=1.5)


if __name__ == "__main__":
    unittest.main()
