import json
from pathlib import Path


class CutsIo:
    def __init__(self, normalizer):
        self._normalizer = normalizer

    def export_to_path(
        self,
        cuts,
        file_path: str,
        video_name: str,
        selected_video_path: str,
    ) -> tuple[int, Path]:
        normalized_cuts = [self._normalizer(cut) for cut in cuts]
        if not normalized_cuts:
            raise ValueError("No cuts to export")

        output_path = Path(file_path)
        if output_path.suffix.lower() != ".json":
            output_path = output_path.with_suffix(".json")

        payload = {
            "version": 1,
            "video": {
                "name": video_name,
                "path": selected_video_path,
            },
            "cuts": normalized_cuts,
        }

        output_path.write_text(
            json.dumps(payload, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        return len(normalized_cuts), output_path

    def import_from_path(self, file_path: str) -> tuple[list[dict], Path]:
        input_path = Path(file_path)
        if not input_path.is_file():
            raise ValueError("Selected cuts JSON file does not exist")

        try:
            payload = json.loads(input_path.read_text(encoding="utf-8"))
        except json.JSONDecodeError as exc:
            raise ValueError(f"Invalid cuts JSON: {exc.msg}") from exc

        raw_cuts = payload.get("cuts") if isinstance(payload, dict) else payload
        if not isinstance(raw_cuts, list):
            raise ValueError("Cuts JSON must contain a cuts array")

        return [self._normalizer(cut) for cut in raw_cuts], input_path
