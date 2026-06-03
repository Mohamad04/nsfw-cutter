def decide_subtitle_action(embedded_streams: list[dict], external_subtitles: list[dict]) -> dict:
    embedded_count = len(embedded_streams)
    external_count = len(external_subtitles)

    if embedded_count > 0:
        return {
            "embedded_subtitles_detected": True,
            "embedded_count": embedded_count,
            "external_subtitles_detected": external_count > 0,
            "external_count": external_count,
            "selected_external_subtitle_path": None,
            "action": "keep_embedded",
            "reason": "Embedded subtitles already exist; external subtitle will not be auto-added.",
        }

    if external_count > 0:
        return {
            "embedded_subtitles_detected": False,
            "embedded_count": 0,
            "external_subtitles_detected": True,
            "external_count": external_count,
            "selected_external_subtitle_path": external_subtitles[0]["path"],
            "action": "add_external",
            "reason": "No embedded subtitles detected; matching external subtitle will be added later.",
        }

    return {
        "embedded_subtitles_detected": False,
        "embedded_count": 0,
        "external_subtitles_detected": False,
        "external_count": 0,
        "selected_external_subtitle_path": None,
        "action": "none",
        "reason": "No embedded or matching external subtitles detected.",
    }
