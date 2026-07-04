FAST_CUTTING_MODE = "fast_cutting"
SMART_CUTTING_MODE = "smart_cutting"
SUPPORTED_CUTTING_MODES = frozenset({FAST_CUTTING_MODE, SMART_CUTTING_MODE})


class ExportRouterService:
    def __init__(self, fast_export_start, smart_export_start, fast_segment_mapper):
        self.fast_export_start = fast_export_start
        self.smart_export_start = smart_export_start
        self.fast_segment_mapper = fast_segment_mapper

    def start(
        self,
        cutting_mode: str,
        input_path: str,
        segments,
        output_dir: str,
        export_mode: str,
        callbacks,
    ) -> bool:
        mode = str(cutting_mode or FAST_CUTTING_MODE).strip().lower()
        if mode not in SUPPORTED_CUTTING_MODES:
            raise ValueError(f"Unsupported cutting mode: {cutting_mode}")
        if mode == SMART_CUTTING_MODE:
            return self._start_smart_cutting(input_path, segments, output_dir, export_mode, callbacks)
        return self._start_fast_cutting(input_path, segments, output_dir, export_mode, callbacks)

    def _start_fast_cutting(
        self,
        input_path: str,
        segments,
        output_dir: str,
        export_mode: str,
        callbacks,
    ) -> bool:
        parsed_segments = []
        for index, segment in enumerate(segments or [], start=1):
            parsed_segments.append(self.fast_segment_mapper(index, segment))
        return self.fast_export_start(input_path, parsed_segments, output_dir, export_mode, callbacks)

    def _start_smart_cutting(
        self,
        input_path: str,
        segments,
        output_dir: str,
        export_mode: str,
        callbacks,
    ) -> bool:
        return self.smart_export_start(input_path, list(segments or []), output_dir, export_mode, callbacks)
