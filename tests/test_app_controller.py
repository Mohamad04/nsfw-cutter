import json
import tempfile
import threading
import time
import unittest
from pathlib import Path

from PySide6.QtCore import QCoreApplication, QThreadPool

from controllers.app_controller import AppController
from services.editing.keyframe_service import KeyframeService
from services.subtitles.processing_service import SubtitleService
from workers.worker_signals import WorkerSignals


class FakeVideoImportService:
    def __init__(self):
        self.video_discovery_service = type(
            "FakeVideoDiscoveryService",
            (),
            {"VIDEO_EXTENSIONS": {".mp4", ".mkv"}},
        )()
        self.videos = [
            {
                "name": "a.mp4",
                "path": "/tmp/a.mp4",
                "subtitle_found": False,
                "subtitle_name": None,
            }
        ]

    def list_importable_videos(self, folder):
        if folder == "invalid":
            raise ValueError("Selected folder does not exist")
        if folder == "empty":
            return []
        return self.videos

    def build_video_listing_for_file(self, file_path):
        raw_path = str(file_path)
        path = Path(file_path)
        if raw_path == "invalid" or path.suffix.lower() not in {".mp4", ".mkv"}:
            raise ValueError("Unsupported video format. Use .mp4 or .mkv")
        return {
            "name": path.name,
            "path": raw_path,
            "extension": path.suffix.lower(),
            "file_size_bytes": 100,
            "subtitle_found": False,
            "subtitle_name": None,
        }

    def import_video_file(self, file_path, user_id=None):
        if file_path == "invalid":
            raise ValueError("Selected video file does not exist")
        raw_path = str(file_path)
        path = Path(file_path)
        return {
            "video_id": 1,
            "video_name": path.name,
            "video_path": raw_path,
            "video_url": "file://" + raw_path if raw_path.startswith("/") else raw_path,
            "subtitle_found": False,
            "subtitle_name": None,
            "status": "Video loaded",
        }


class FakeThreadPool:
    def __init__(self):
        self.workers = []
        self.max_thread_count = None

    def setMaxThreadCount(self, count):
        self.max_thread_count = count

    def start(self, worker):
        self.workers.append(worker)


class FakeExportWorker:
    def __init__(self, job_key, input_path, output_path):
        self.job_key = job_key
        self.input_path = input_path
        self.output_path = output_path
        self.signals = WorkerSignals()


class FakePrepareWorker:
    def __init__(self, job_key, input_path, output_path):
        self.job_key = job_key
        self.input_path = input_path
        self.output_path = output_path
        self.signals = WorkerSignals()


class FakeKeyframeWorker:
    def __init__(self, job_token, input_path, keyframe_service):
        self.job_token = job_token
        self.input_path = input_path
        self.keyframe_service = keyframe_service
        self.signals = WorkerSignals()


class FakeSubtitleWorker:
    def __init__(self, job_token, input_path, subtitle_service):
        self.job_token = job_token
        self.input_path = input_path
        self.subtitle_service = subtitle_service
        self.signals = WorkerSignals()


class FakeSettingsService:
    def __init__(self, last_video=None):
        self.last_video = last_video
        self.recent_videos = []
        self.saved_videos = []

    def load(self):
        return type(
            "FakeSettings",
            (),
            {
                "last_video_path": self.last_video,
                "recent_videos": list(self.recent_videos),
            },
        )()

    def get_last_video(self):
        return self.last_video

    def save_last_video(self, path):
        video_path = Path(path)
        self.last_video = video_path
        self.saved_videos.append(path)
        self.recent_videos = [recent for recent in self.recent_videos if recent != video_path]
        self.recent_videos.insert(0, video_path)
        self.recent_videos = self.recent_videos[:10]
        return self.load()

    def add_recent_videos(self, paths):
        for path in reversed(paths):
            video_path = Path(path)
            self.recent_videos = [recent for recent in self.recent_videos if recent != video_path]
            self.recent_videos.insert(0, video_path)
        self.recent_videos = self.recent_videos[:10]
        return self.load()

    def remove_recent_video(self, path):
        video_path = Path(path)
        self.recent_videos = [recent for recent in self.recent_videos if recent != video_path]
        if self.last_video == video_path:
            self.last_video = None
        return self.load()

    def clear_recent_videos(self):
        self.recent_videos = []
        return self.load()

    def prune_missing_recent_videos(self):
        existing = [path for path in self.recent_videos if path.is_file()]
        changed = existing != self.recent_videos
        self.recent_videos = existing
        return self.load(), changed


class AppControllerTests(unittest.TestCase):
    def setUp(self):
        self.thread_pool = FakeThreadPool()
        self.settings_service = FakeSettingsService()
        self.controller = AppController(
            video_import_service=FakeVideoImportService(),
            thread_pool=self.thread_pool,
            worker_factory=FakeExportWorker,
            prepare_worker_factory=FakePrepareWorker,
            settings_service=self.settings_service,
            keyframe_worker_factory=FakeKeyframeWorker,
            subtitle_worker_factory=FakeSubtitleWorker,
        )

    def _workers_of_type(self, worker_type):
        return [worker for worker in self.thread_pool.workers if isinstance(worker, worker_type)]

    def test_controller_configures_default_thread_limit(self):
        self.assertEqual(self.thread_pool.max_thread_count, AppController.DEFAULT_MAX_THREAD_COUNT)

    def test_controller_accepts_custom_thread_limit(self):
        thread_pool = FakeThreadPool()

        AppController(
            video_import_service=FakeVideoImportService(),
            thread_pool=thread_pool,
            worker_factory=FakeExportWorker,
            max_thread_count=4,
            settings_service=FakeSettingsService(),
        )

        self.assertEqual(thread_pool.max_thread_count, 4)

    def test_ai_suggestions_normalize_formatted_times(self):
        self.controller.setAiSuggestions(
            [
                {
                    "start": "00:12:14",
                    "end": "00:12:36.250",
                    "confidence": "high",
                    "reason": "scene candidate",
                }
            ]
        )

        self.assertEqual(self.controller.aiAnalysisState, "ready")
        self.assertEqual(
            self.controller.aiSuggestions,
            [
                {
                    "start": "00:12:14.000",
                    "end": "00:12:36.250",
                    "confidence": "High",
                    "reason": "scene candidate",
                }
            ],
        )

    def test_ai_suggestions_normalize_second_values(self):
        self.controller.setAiSuggestions(
            [
                {
                    "start_seconds": 735.5,
                    "end_seconds": 762,
                    "confidence": 0.45,
                }
            ]
        )

        self.assertEqual(
            self.controller.aiSuggestions,
            [
                {
                    "start": "00:12:15.500",
                    "end": "00:12:42.000",
                    "confidence": "Low",
                    "reason": "",
                }
            ],
        )

    def test_load_folder_populates_available_videos(self):
        self.controller.loadFolder("folder")

        self.assertEqual(self.controller.availableVideos[0]["name"], "a.mp4")
        self.assertEqual(self.controller.currentFolder, "folder")
        self.assertEqual(self.controller.projectStatus, "1 video(s) found. Select one to load.")

    def test_load_folder_empty_sets_status(self):
        self.controller.loadFolder("empty")

        self.assertEqual(self.controller.availableVideos, [])
        self.assertEqual(self.controller.currentFolder, "empty")
        self.assertEqual(self.controller.projectStatus, "No video found in selected folder")

    def test_load_folder_invalid_clears_current_folder(self):
        self.controller.loadFolder("folder")
        self.controller.loadFolder("invalid")

        self.assertEqual(self.controller.currentFolder, "")
        self.assertEqual(self.controller.availableVideos, [])
        self.assertEqual(self.controller.projectStatus, "Selected folder does not exist")

    def test_load_video_file_updates_properties(self):
        self.controller.loadVideoFile("/tmp/a.mp4")

        self.assertEqual(self.controller.videoUrl, "file:///tmp/a.mp4")
        self.assertEqual(self.controller.videoName, "a.mp4")
        self.assertEqual(self.controller.subtitleStatus, "Subtitle: Detecting...")
        self.assertEqual(self.controller.subtitleDetectionState, "loading")
        self.assertEqual(self.controller.subtitleCandidates, [])
        self.assertEqual(self.controller.analysisSubtitleOptions, [])
        self.assertEqual(self.controller.selectedAnalysisSubtitleId, "")
        self.assertEqual(self.controller.activePreviewSubtitleTrackIndex, -1)
        self.assertEqual(self.controller.projectStatus, "Video loaded")
        self.assertEqual(self.controller.selectedVideoPath, "/tmp/a.mp4")
        self.assertEqual(self.settings_service.saved_videos, ["/tmp/a.mp4"])

    def test_load_video_file_converts_raw_windows_path_to_file_url(self):
        self.controller.loadVideoFile(r"C:\Users\me\Videos\sample video.mp4")

        self.assertEqual(
            self.controller.videoUrl,
            "file:///C:/Users/me/Videos/sample video.mp4",
        )

    def test_load_video_file_starts_background_keyframe_indexing(self):
        self.controller.loadVideoFile("/tmp/a.mp4")

        self.assertEqual(self.controller.keyframeState, "loading")
        self.assertEqual(self.controller.keyframeCount, 0)
        self.assertEqual(len(self._workers_of_type(FakeKeyframeWorker)), 1)
        self.assertEqual(len(self._workers_of_type(FakeSubtitleWorker)), 1)

    def test_loading_same_video_while_indexing_does_not_start_duplicate_worker(self):
        self.controller.loadVideoFile("/tmp/a.mp4")
        self.controller.loadVideoFile("/tmp/a.mp4")

        self.assertEqual(self.controller.keyframeState, "loading")
        self.assertEqual(len(self._workers_of_type(FakeKeyframeWorker)), 1)
        self.assertEqual(len(self._workers_of_type(FakeSubtitleWorker)), 1)

    def test_stale_keyframe_result_does_not_replace_new_video_state(self):
        self.controller.loadVideoFile("/tmp/a.mp4")
        first_worker = self._workers_of_type(FakeKeyframeWorker)[0]
        self.controller.loadVideoFile("/tmp/b.mkv")
        second_worker = self._workers_of_type(FakeKeyframeWorker)[1]

        self.controller._on_keyframe_indexing_finished(
            first_worker.job_token,
            {
                "input_path": first_worker.input_path,
                "keyframes": [0.0, 10.0],
                "elapsed_seconds": 0.1,
            },
        )

        self.assertEqual(self.controller.keyframeState, "loading")
        self.assertEqual(self.controller.keyframeMediaPath, second_worker.input_path)
        self.assertEqual(self.controller.keyframeCount, 0)

    def test_keyframe_worker_failure_sets_error_state(self):
        self.controller.loadVideoFile("/tmp/a.mp4")
        worker = self._workers_of_type(FakeKeyframeWorker)[0]

        self.controller._on_keyframe_indexing_error(worker.job_token, "ffprobe failed")

        self.assertEqual(self.controller.keyframeState, "error")
        self.assertEqual(self.controller.keyframeError, "ffprobe failed")
        self.assertEqual(self.controller.keyframeCount, 0)

    def test_subtitle_discovery_finished_updates_status_and_candidates(self):
        self.controller.loadVideoFile("/tmp/a.mp4")
        worker = self._workers_of_type(FakeSubtitleWorker)[0]
        candidates = [
            {
                "source": "embedded",
                "stream_index": 1,
                "kind": "text",
                "language_name": "French",
                "is_text_readable": True,
            },
            {
                "source": "external",
                "file_path": "/tmp/a.eng.srt",
                "kind": "text",
                "language_name": "English",
                "is_text_readable": True,
            },
        ]

        self.controller._on_subtitle_discovery_finished(
            worker.job_token,
            {"input_path": worker.input_path, "candidates": candidates},
        )

        self.assertEqual(self.controller.subtitleDetectionState, "ready")
        self.assertEqual(
            self.controller.subtitleStatus,
            "Analysis subtitle: Select one · 2 available",
        )
        self.assertEqual(len(self.controller.subtitleCandidates), 2)
        self.assertTrue(all(candidate.get("candidate_id") for candidate in self.controller.subtitleCandidates))
        self.assertEqual(
            [option["label"] for option in self.controller.analysisSubtitleOptions],
            ["Off", "French", "English"],
        )
        self.assertEqual(self.controller.selectedAnalysisSubtitleId, "")
        self.assertEqual(self.controller.subtitleError, "")

    def test_single_text_readable_subtitle_is_auto_selected(self):
        self.controller.loadVideoFile("/tmp/a.mp4")
        worker = self._workers_of_type(FakeSubtitleWorker)[0]

        self.controller._on_subtitle_discovery_finished(
            worker.job_token,
            {
                "input_path": worker.input_path,
                "candidates": [
                    {
                        "source": "external",
                        "file_path": "/tmp/a.fra.srt",
                        "kind": "text",
                        "language_name": "French",
                        "is_text_readable": True,
                    }
                ],
            },
        )

        self.assertEqual(self.controller.subtitleStatus, "Analysis subtitle: French · Auto-selected")
        self.assertNotEqual(self.controller.selectedAnalysisSubtitleId, "")
        self.assertEqual(self.controller.selectedAnalysisSubtitle["language_name"], "French")
        self.assertTrue(self.controller.analysisSubtitleOptions[1]["selected"])
        self.assertEqual(self.controller.activePreviewSubtitleTrackIndex, -1)

    def test_embedded_selection_activates_player_subtitle_track_index_not_ffprobe_stream_index(self):
        self.controller.loadVideoFile("/tmp/a.mp4")
        self.controller.updatePlayerSubtitleTrackCount(1)
        worker = self._workers_of_type(FakeSubtitleWorker)[0]
        self.controller._on_subtitle_discovery_finished(
            worker.job_token,
            {
                "input_path": worker.input_path,
                "candidates": [
                    {
                        "source": "embedded",
                        "stream_index": 3,
                        "codec_name": "subrip",
                        "kind": "text",
                        "language_name": "French",
                        "is_text_readable": True,
                    }
                ],
            },
        )

        self.assertEqual(self.controller.selectedAnalysisSubtitle["stream_index"], 3)
        self.assertEqual(self.controller.selectedAnalysisSubtitle["player_subtitle_track_index"], 0)
        self.assertEqual(self.controller.activePreviewSubtitleTrackIndex, 0)

    def test_embedded_auto_selection_activates_when_player_tracks_arrive_late(self):
        self.controller.loadVideoFile("/tmp/a.mp4")
        worker = self._workers_of_type(FakeSubtitleWorker)[0]
        self.controller._on_subtitle_discovery_finished(
            worker.job_token,
            {
                "input_path": worker.input_path,
                "candidates": [
                    {
                        "source": "embedded",
                        "stream_index": 3,
                        "codec_name": "subrip",
                        "kind": "text",
                        "language_name": "French",
                        "is_text_readable": True,
                    }
                ],
            },
        )
        self.assertEqual(self.controller.activePreviewSubtitleTrackIndex, -1)

        self.controller.updatePlayerSubtitleTrackCount(1)

        self.assertEqual(self.controller.selectedAnalysisSubtitle["player_subtitle_track_index"], 0)
        self.assertEqual(self.controller.activePreviewSubtitleTrackIndex, 0)

    def test_off_selection_disables_preview_subtitles(self):
        self.controller.loadVideoFile("/tmp/a.mp4")
        self.controller.updatePlayerSubtitleTrackCount(1)
        worker = self._workers_of_type(FakeSubtitleWorker)[0]
        self.controller._on_subtitle_discovery_finished(
            worker.job_token,
            {
                "input_path": worker.input_path,
                "candidates": [
                    {
                        "source": "embedded",
                        "stream_index": 3,
                        "codec_name": "subrip",
                        "kind": "text",
                        "language_name": "French",
                        "is_text_readable": True,
                    }
                ],
            },
        )

        selected = self.controller.selectAnalysisSubtitle("__subtitle_preview_off__")

        self.assertTrue(selected)
        self.assertEqual(self.controller.selectedAnalysisSubtitleId, "__subtitle_preview_off__")
        self.assertEqual(self.controller.selectedAnalysisSubtitle, {})
        self.assertEqual(self.controller.activePreviewSubtitleTrackIndex, -1)
        self.assertEqual(self.controller.subtitleStatus, "Analysis subtitle: Off")

    def test_subtitle_discovery_finished_without_candidates_sets_not_detected(self):
        self.controller.loadVideoFile("/tmp/a.mp4")
        worker = self._workers_of_type(FakeSubtitleWorker)[0]

        self.controller._on_subtitle_discovery_finished(
            worker.job_token,
            {"input_path": worker.input_path, "candidates": []},
        )

        self.assertEqual(self.controller.subtitleDetectionState, "ready")
        self.assertEqual(self.controller.subtitleStatus, "Subtitle: Not detected")
        self.assertEqual(self.controller.subtitleCandidates, [])
        self.assertEqual(self.controller.analysisSubtitleOptions, [])
        self.assertEqual(self.controller.selectedAnalysisSubtitleId, "")
        self.assertEqual(self.controller.activePreviewSubtitleTrackIndex, -1)

    def test_subtitle_discovery_failure_sets_error_state(self):
        self.controller.loadVideoFile("/tmp/a.mp4")
        worker = self._workers_of_type(FakeSubtitleWorker)[0]

        self.controller._on_subtitle_discovery_error(worker.job_token, "ffprobe failed")

        self.assertEqual(self.controller.subtitleDetectionState, "error")
        self.assertEqual(self.controller.subtitleStatus, "Subtitle: Detection error")
        self.assertEqual(self.controller.subtitleError, "ffprobe failed")
        self.assertEqual(self.controller.subtitleCandidates, [])
        self.assertEqual(self.controller.selectedAnalysisSubtitleId, "")
        self.assertEqual(self.controller.activePreviewSubtitleTrackIndex, -1)

    def test_selecting_readable_analysis_subtitle_updates_state(self):
        self.controller.loadVideoFile("/tmp/a.mp4")
        worker = self._workers_of_type(FakeSubtitleWorker)[0]
        self.controller._on_subtitle_discovery_finished(
            worker.job_token,
            {
                "input_path": worker.input_path,
                "candidates": [
                    {
                        "source": "embedded",
                        "stream_index": 1,
                        "kind": "text",
                        "language_name": "French",
                        "is_text_readable": True,
                    },
                    {
                        "source": "external",
                        "file_path": "/tmp/a.eng.srt",
                        "kind": "text",
                        "language_name": "English",
                        "is_text_readable": True,
                    },
                ],
            },
        )
        selected_id = self.controller.subtitleCandidates[0]["candidate_id"]

        selected = self.controller.selectAnalysisSubtitle(selected_id)

        self.assertTrue(selected)
        self.assertEqual(self.controller.selectedAnalysisSubtitleId, selected_id)
        self.assertEqual(self.controller.selectedAnalysisSubtitle["language_name"], "French")
        self.assertEqual(self.controller.subtitleStatus, "Analysis subtitle: French")
        self.assertEqual(self.controller.activePreviewSubtitleTrackIndex, -1)
        self.assertEqual(len(self.controller.subtitleCandidates), 2)
        self.assertTrue(self.controller.analysisSubtitleOptions[1]["selected"])

    def test_selecting_unreadable_analysis_subtitle_is_rejected(self):
        self.controller.loadVideoFile("/tmp/a.mp4")
        worker = self._workers_of_type(FakeSubtitleWorker)[0]
        self.controller._on_subtitle_discovery_finished(
            worker.job_token,
            {
                "input_path": worker.input_path,
                "candidates": [
                    {
                        "source": "embedded",
                        "stream_index": 1,
                        "kind": "image",
                        "language_name": "English",
                        "is_text_readable": False,
                    }
                ],
            },
        )
        rejected_id = self.controller.subtitleCandidates[0]["candidate_id"]

        selected = self.controller.selectAnalysisSubtitle(rejected_id)

        self.assertFalse(selected)
        self.assertEqual(self.controller.selectedAnalysisSubtitleId, "")
        self.assertEqual(self.controller.subtitleStatus, "Subtitles found · None text-readable")
        self.assertFalse(self.controller.analysisSubtitleOptions[1]["enabled"])

    def test_selecting_external_analysis_subtitle_uses_overlay_not_preview_track(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            subtitle = Path(temp_dir) / "a.fra.srt"
            subtitle.write_text(
                "1\n"
                "00:00:01,000 --> 00:00:03,000\n"
                "External subtitle text\n",
                encoding="utf-8",
            )

            self.controller.loadVideoFile("/tmp/a.mp4")
            self.controller.updatePlayerSubtitleTrackCount(2)
            worker = self._workers_of_type(FakeSubtitleWorker)[0]
            self.controller._on_subtitle_discovery_finished(
                worker.job_token,
                {
                    "input_path": worker.input_path,
                    "candidates": [
                        {
                            "source": "external",
                            "file_path": str(subtitle),
                            "kind": "text",
                            "format": "srt",
                            "language_name": "French",
                            "is_text_readable": True,
                        }
                    ],
                },
            )

            self.controller.updatePreviewSubtitlePosition(1500)

        self.assertNotEqual(self.controller.selectedAnalysisSubtitleId, "")
        self.assertEqual(self.controller.selectedAnalysisSubtitle["source"], "external")
        self.assertEqual(self.controller.activePreviewSubtitleTrackIndex, -1)
        self.assertEqual(self.controller.previewSubtitleText, "External subtitle text")

    def test_selecting_external_ass_subtitle_uses_text_overlay(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            subtitle = Path(temp_dir) / "a.eng.ass"
            subtitle.write_text(
                "[Script Info]\n"
                "ScriptType: v4.00+\n"
                "\n"
                "[V4+ Styles]\n"
                "Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, "
                "OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, "
                "ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, "
                "MarginR, MarginV, Encoding\n"
                "Style: Default,Arial,20,&H00FFFFFF,&H000000FF,&H00000000,&H00000000,"
                "0,0,0,0,100,100,0,0,1,2,2,2,10,10,10,1\n"
                "\n"
                "[Events]\n"
                "Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text\n"
                "Dialogue: 0,0:00:01.00,0:00:03.00,Default,,0,0,0,,{\\i1}ASS subtitle text\n",
                encoding="utf-8",
            )

            self.controller.loadVideoFile("/tmp/a.mp4")
            worker = self._workers_of_type(FakeSubtitleWorker)[0]
            self.controller._on_subtitle_discovery_finished(
                worker.job_token,
                {
                    "input_path": worker.input_path,
                    "candidates": [
                        {
                            "source": "external",
                            "file_path": str(subtitle),
                            "kind": "text",
                            "format": "ass",
                            "language_name": "English",
                            "is_text_readable": True,
                        }
                    ],
                },
            )

            self.controller.updatePreviewSubtitlePosition(1500)

        self.assertEqual(self.controller.previewSubtitleText, "ASS subtitle text")
        self.assertEqual(self.controller.activePreviewSubtitleTrackIndex, -1)

    def test_off_selection_clears_external_subtitle_overlay(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            subtitle = Path(temp_dir) / "a.eng.srt"
            subtitle.write_text(
                "1\n"
                "00:00:01,000 --> 00:00:03,000\n"
                "External subtitle text\n",
                encoding="utf-8",
            )

            self.controller.loadVideoFile("/tmp/a.mp4")
            worker = self._workers_of_type(FakeSubtitleWorker)[0]
            self.controller._on_subtitle_discovery_finished(
                worker.job_token,
                {
                    "input_path": worker.input_path,
                    "candidates": [
                        {
                            "source": "external",
                            "file_path": str(subtitle),
                            "kind": "text",
                            "format": "srt",
                            "language_name": "English",
                            "is_text_readable": True,
                        }
                    ],
                },
            )
            self.controller.updatePreviewSubtitlePosition(1500)
            self.assertEqual(self.controller.previewSubtitleText, "External subtitle text")

            selected = self.controller.selectAnalysisSubtitle("__subtitle_preview_off__")
            self.controller.updatePreviewSubtitlePosition(1500)

        self.assertTrue(selected)
        self.assertEqual(self.controller.previewSubtitleText, "")
        self.assertEqual(self.controller.activePreviewSubtitleTrackIndex, -1)

    def test_stale_subtitle_discovery_result_does_not_replace_new_video_state(self):
        self.controller.loadVideoFile("/tmp/a.mp4")
        first_worker = self._workers_of_type(FakeSubtitleWorker)[0]
        self.controller.loadVideoFile("/tmp/b.mkv")
        second_worker = self._workers_of_type(FakeSubtitleWorker)[1]

        self.controller._on_subtitle_discovery_finished(
            first_worker.job_token,
            {
                "input_path": first_worker.input_path,
                "candidates": [{"source": "external", "kind": "text"}],
            },
        )

        self.assertEqual(self.controller.subtitleDetectionState, "loading")
        self.assertEqual(self.controller.subtitleStatus, "Subtitle: Detecting...")
        self.assertEqual(self.controller.subtitleCandidates, [])
        self.assertEqual(self.controller.selectedAnalysisSubtitleId, "")
        self.assertEqual(self.controller.activePreviewSubtitleTrackIndex, -1)
        self.assertEqual(self.controller.selectedVideoPath, "/tmp/b.mkv")
        self.assertNotEqual(first_worker.job_token, second_worker.job_token)

    def test_loading_new_video_clears_selected_analysis_subtitle(self):
        self.controller.loadVideoFile("/tmp/a.mp4")
        first_worker = self._workers_of_type(FakeSubtitleWorker)[0]
        self.controller._on_subtitle_discovery_finished(
            first_worker.job_token,
            {
                "input_path": first_worker.input_path,
                "candidates": [
                    {
                        "source": "external",
                        "file_path": "/tmp/a.fra.srt",
                        "language_name": "French",
                        "is_text_readable": True,
                    }
                ],
            },
        )
        self.assertNotEqual(self.controller.selectedAnalysisSubtitleId, "")

        self.controller.loadVideoFile("/tmp/b.mkv")

        self.assertEqual(self.controller.selectedAnalysisSubtitleId, "")
        self.assertEqual(self.controller.selectedAnalysisSubtitle, {})
        self.assertEqual(self.controller.subtitleStatus, "Subtitle: Detecting...")
        self.assertEqual(self.controller.activePreviewSubtitleTrackIndex, -1)

    def test_keyframe_indexing_runs_off_caller_thread_and_completes(self):
        app = QCoreApplication.instance() or QCoreApplication([])
        pool = QThreadPool()
        probe_started = threading.Event()
        release_probe = threading.Event()
        probe_thread_ids = []

        def keyframe_probe(_input_path, **_kwargs):
            probe_thread_ids.append(threading.get_ident())
            probe_started.set()
            release_probe.wait(timeout=2)
            return [10.0, 0.0, 5.0]

        service = KeyframeService(keyframe_probe=keyframe_probe)
        controller = AppController(
            video_import_service=FakeVideoImportService(),
            thread_pool=pool,
            worker_factory=FakeExportWorker,
            prepare_worker_factory=FakePrepareWorker,
            settings_service=FakeSettingsService(),
            keyframe_service=service,
            subtitle_service=SubtitleService(
                embedded_inspection=lambda _path: [],
                external_discovery=lambda _path: [],
            ),
        )

        try:
            controller.loadVideoFile("/tmp/a.mp4")

            self.assertTrue(probe_started.wait(timeout=1))
            self.assertEqual(controller.keyframeState, "loading")
            self.assertNotEqual(probe_thread_ids, [threading.get_ident()])

            release_probe.set()
            deadline = time.monotonic() + 2
            while controller.keyframeState == "loading" and time.monotonic() < deadline:
                app.processEvents()
                time.sleep(0.01)

            self.assertEqual(controller.keyframeState, "ready")
            self.assertEqual(controller.keyframeCount, 3)
            self.assertEqual(controller.keyframeTimestamps, [0.0, 5.0, 10.0])
            self.assertEqual(service.keyframe_timestamps, [0.0, 5.0, 10.0])
        finally:
            release_probe.set()
            pool.waitForDone(2000)
            app.processEvents()

    def test_restore_last_video_loads_existing_settings_path(self):
        controller = AppController(
            video_import_service=FakeVideoImportService(),
            thread_pool=FakeThreadPool(),
            worker_factory=FakeExportWorker,
            prepare_worker_factory=FakePrepareWorker,
            settings_service=FakeSettingsService(last_video=Path("/tmp/a.mp4")),
            subtitle_worker_factory=FakeSubtitleWorker,
        )

        controller.restoreLastVideo()

        self.assertEqual(controller.videoName, "a.mp4")
        self.assertEqual(controller.selectedVideoPath, str(Path("/tmp/a.mp4")))

    def test_load_video_file_invalid_does_not_crash(self):
        self.controller.loadVideoFile("invalid")

        self.assertEqual(self.controller.projectStatus, "Selected video file does not exist")

    def test_select_available_video_loads_by_index(self):
        self.controller.loadFolder("folder")
        self.controller.selectAvailableVideo(0)

        self.assertEqual(self.controller.videoName, "a.mp4")
        self.assertEqual(self.controller.selectedVideoPath, "/tmp/a.mp4")

    def test_select_available_video_invalid_index_sets_status(self):
        self.controller.selectAvailableVideo(10)

        self.assertEqual(self.controller.projectStatus, "Invalid video selection")

    def test_load_video_files_deduplicates_list_populates_recents_and_loads_first(self):
        self.controller.loadVideoFiles(["/tmp/a.mp4", "/tmp/b.mkv", "/tmp/a.mp4", "/tmp/bad.txt"])

        self.assertEqual([video["path"] for video in self.controller.availableVideos], ["/tmp/a.mp4", "/tmp/b.mkv"])
        self.assertEqual(self.controller.selectedVideoPath, "/tmp/a.mp4")
        self.assertEqual(
            [item["path"] for item in self.controller.recentFiles],
            [str(Path("/tmp/a.mp4")), str(Path("/tmp/b.mkv"))],
        )
        self.assertEqual(
            self.controller.projectStatus,
            "Loaded 2 video(s); skipped 1 unsupported or missing file(s).",
        )

    def test_open_recent_file_removes_missing_entry_without_crashing(self):
        missing_path = Path(tempfile.gettempdir()) / "missing_recent_video.mp4"
        self.settings_service.add_recent_videos([missing_path])

        self.controller.openRecentFile(str(missing_path))

        self.assertEqual(self.controller.recentFiles, [])
        self.assertEqual(self.controller.projectStatus, "Recent file no longer exists.")

    def test_clear_recent_files_keeps_current_video_loaded(self):
        self.controller.loadVideoFile("/tmp/a.mp4")

        self.controller.clearRecentFiles()

        self.assertEqual(self.controller.recentFiles, [])
        self.assertEqual(self.controller.selectedVideoPath, "/tmp/a.mp4")

    def test_clear_video_resets_properties(self):
        self.controller.loadVideoFile("/tmp/a.mp4")
        self.controller.clearVideo()

        self.assertEqual(self.controller.videoUrl, "")
        self.assertEqual(self.controller.videoName, "No video selected")
        self.assertEqual(self.controller.subtitleStatus, "Subtitle: Not detected")
        self.assertEqual(self.controller.subtitleDetectionState, "idle")
        self.assertEqual(self.controller.subtitleCandidates, [])
        self.assertEqual(self.controller.analysisSubtitleOptions, [])
        self.assertEqual(self.controller.selectedAnalysisSubtitleId, "")
        self.assertEqual(self.controller.activePreviewSubtitleTrackIndex, -1)
        self.assertEqual(self.controller.projectStatus, "Ready")
        self.assertEqual(self.controller.selectedVideoPath, "")

    def test_start_lossless_export_updates_state_and_starts_worker(self):
        self.controller.startLosslessExport("/tmp/a.mp4", "/tmp/a_export.mp4")

        self.assertTrue(self.controller.exportBusy)
        self.assertEqual(self.controller.exportProgress, 0)
        self.assertEqual(self.controller.exportStatus, "Preparing export...")
        self.assertEqual(len(self.thread_pool.workers), 1)

    def test_start_lossless_export_blocks_duplicate_job(self):
        self.controller.startLosslessExport("/tmp/a.mp4", "/tmp/a_export.mp4")
        self.controller.startLosslessExport("/tmp/a.mp4", "/tmp/a_export.mp4")

        self.assertEqual(len(self.thread_pool.workers), 1)
        self.assertEqual(self.controller.exportStatus, "This export is already running.")

    def test_export_finished_cleans_up_running_job(self):
        self.controller.startLosslessExport("/tmp/a.mp4", "/tmp/a_export.mp4")

        self.controller._on_export_finished("export:/tmp/a.mp4:/tmp/a_export.mp4", "/tmp/a_export.mp4")

        self.assertFalse(self.controller.exportBusy)
        self.assertEqual(self.controller.exportProgress, 100)
        self.assertEqual(self.controller.exportStatus, "Export completed: /tmp/a_export.mp4")

    def test_export_error_cleans_up_running_job(self):
        self.controller.startLosslessExport("/tmp/a.mp4", "/tmp/a_export.mp4")

        self.controller._on_export_error("export:/tmp/a.mp4:/tmp/a_export.mp4", "bad input")

        self.assertFalse(self.controller.exportBusy)
        self.assertEqual(self.controller.exportStatus, "Export failed: bad input")

    def test_prepare_export_job_updates_state_and_starts_worker(self):
        self.controller.prepareExportJob("/tmp/a.mp4", "")

        self.assertTrue(self.controller.backendPreparationBusy)
        self.assertEqual(self.controller.backendPreparationProgress, 0)
        self.assertEqual(self.controller.backendPreparationStatus, "Starting backend preparation")
        self.assertEqual(len(self.thread_pool.workers), 1)
        self.assertIsInstance(self.thread_pool.workers[0], FakePrepareWorker)

    def test_prepare_export_job_finished_records_job_metadata(self):
        self.controller.prepareExportJob("/tmp/a.mp4", "")
        result = {
            "export_job": {"job_id": "export_1"},
            "json_artifacts": {"export_job_json_path": "data/json/export_jobs/export_1.json"},
        }

        self.controller._on_backend_preparation_finished("prepare_export:/tmp/a.mp4:", result)

        self.assertFalse(self.controller.backendPreparationBusy)
        self.assertEqual(self.controller.backendPreparationProgress, 100)
        self.assertEqual(self.controller.backendPreparationStatus, "Preparation completed")
        self.assertEqual(self.controller.currentExportJobId, "export_1")
        self.assertEqual(self.controller.currentExportJobJsonPath, "data/json/export_jobs/export_1.json")

    def test_export_cuts_to_json_file(self):
        self.controller.loadVideoFile("/tmp/a.mp4")
        cuts = [
            {
                "start": "00:00:10",
                "end": "00:00:20",
                "reason": "Manual cut",
                "tags": "manual",
                "source": "Manual",
                "score": "--",
            }
        ]

        with tempfile.TemporaryDirectory() as tmp_dir:
            output_path = Path(tmp_dir) / "cuts.json"
            self.controller.exportCutsToPath(cuts, str(output_path))

            payload = json.loads(output_path.read_text(encoding="utf-8"))

        self.assertEqual(payload["version"], 1)
        self.assertEqual(payload["video"]["name"], "a.mp4")
        self.assertEqual(payload["cuts"], cuts)
        self.assertEqual(self.controller.projectStatus, "Exported 1 cut(s) to cuts.json")

    def test_import_cuts_from_json_file_accepts_wrapped_payload(self):
        payload = {
            "version": 1,
            "cuts": [
                {
                    "start": "00:00:10",
                    "end": "00:00:20",
                    "reason": "Scene",
                    "tags": "tag",
                    "source": "AI",
                    "score": "0.80",
                }
            ],
        }

        with tempfile.TemporaryDirectory() as tmp_dir:
            input_path = Path(tmp_dir) / "cuts.json"
            input_path.write_text(json.dumps(payload), encoding="utf-8")

            cuts = self.controller.importCutsFromPath(str(input_path))

        self.assertEqual(cuts, payload["cuts"])
        self.assertEqual(self.controller.projectStatus, "Imported 1 cut(s) from cuts.json")

    def test_import_cuts_from_json_file_rejects_reversed_range(self):
        payload = [{"start": "00:00:20", "end": "00:00:10"}]

        with tempfile.TemporaryDirectory() as tmp_dir:
            input_path = Path(tmp_dir) / "cuts.json"
            input_path.write_text(json.dumps(payload), encoding="utf-8")

            with self.assertRaisesRegex(ValueError, "start before end"):
                self.controller.importCutsFromPath(str(input_path))


if __name__ == "__main__":
    unittest.main()
