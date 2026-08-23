from __future__ import annotations

import gc
import json
import logging
import os
from copy import deepcopy
from dataclasses import dataclass
from importlib.util import find_spec
from pathlib import Path
from time import monotonic
from typing import Any

from pydantic import ValidationError

from core.paths import get_model_cache_dir
from services.analysis.cancellation import CancellationToken
from services.analysis.contracts import (
    AnalysisSettings,
    ProviderDiagnostics,
    VisualBatch,
    VLMReviewItem,
    VLMReviewResponse,
    VLMReviewResult,
    VLMWireResponse,
)
from services.analysis.providers.base import (
    VLMProviderError,
    VLMProviderInferenceError,
    VLMProviderTimeoutError,
    VLMProviderUnavailableError,
    VLMQuantizationError,
    VLMStructuredOutputError,
)

logger = logging.getLogger(__name__)

# Bound each sampled frame to 128-256 Qwen visual tokens. Without this cap, an
# eight-frame 1080p batch can create a quadratic attention allocation far beyond
# an 8 GiB consumer GPU even when model layers are correctly offloaded.
_QWEN_MIN_PIXELS = 128 * 28 * 28
_QWEN_MAX_PIXELS = 256 * 28 * 28
_MAX_GENERATION_TOKENS = 192
_MAX_REPAIR_TOKENS = 128
_MAX_DIAGNOSTIC_OUTPUT_CHARS = 16_000
_MAX_REPAIR_INPUT_CHARS = 8_000


@dataclass(frozen=True)
class _GenerationAttempt:
    text: str
    token_count: int
    stop_reason: str


class LocalQwenVLProvider:
    """Lazy local Qwen provider with bounded, grammar-constrained generation."""

    def __init__(self, model_cache_dir: str | Path | None = None) -> None:
        self.model_cache_dir = (
            Path(model_cache_dir) if model_cache_dir is not None else get_model_cache_dir()
        )
        self._loaded_key: tuple[str, str, bool, str] | None = None
        self._model = None
        self._processor = None
        self._tokenizer_data = None
        self._device = "cpu"
        self.warnings: list[str] = []
        self.diagnostics = ProviderDiagnostics()

    @property
    def model_id(self) -> str:
        if self._loaded_key is None:
            return "Qwen/Qwen2.5-VL-3B-Instruct"
        return self._loaded_key[0]

    def review_batch(
        self,
        batch: VisualBatch,
        settings: AnalysisSettings,
        cancellation: CancellationToken,
    ) -> VLMReviewResult:
        started_at = monotonic()
        deadline = started_at + settings.batch_timeout_seconds
        cancellation.raise_if_cancelled()
        self._ensure_loaded(settings, cancellation)
        cancellation.raise_if_cancelled()
        wire_schema = _wire_schema_for_batch(batch)

        try:
            visual_inputs = self._prepare_visual_inputs(batch)
            first_attempt = self._generate(
                visual_inputs,
                cancellation,
                deadline,
                max_new_tokens=min(settings.max_new_tokens, _MAX_GENERATION_TOKENS),
                wire_schema=wire_schema,
            )
        except VLMProviderError:
            raise
        except Exception as exc:
            raise VLMProviderInferenceError(
                f"Local Qwen VLM inference failed ({type(exc).__name__})."
            ) from exc

        cancellation.raise_if_cancelled()
        repaired_output = ""
        repaired = False
        stop_reason = first_attempt.stop_reason
        try:
            wire_response = _validate_wire_output(first_attempt.text, batch)
        except VLMStructuredOutputError as first_error:
            if monotonic() >= deadline:
                raise VLMProviderTimeoutError(
                    "Local Qwen VLM exceeded the per-batch generation deadline.",
                    raw_output=_bounded_output(first_attempt.text),
                    stop_reason="timeout",
                ) from first_error
            try:
                # This second pass contains text only. In particular, it does not call
                # process_vision_info or send the batch images through the vision encoder.
                repair_inputs = self._prepare_repair_inputs(first_attempt.text)
                repair_attempt = self._generate(
                    repair_inputs,
                    cancellation,
                    deadline,
                    max_new_tokens=min(
                        settings.repair_max_new_tokens,
                        _MAX_REPAIR_TOKENS,
                    ),
                    wire_schema=wire_schema,
                )
                repaired_output = repair_attempt.text
                wire_response = _validate_wire_output(repaired_output, batch)
                repaired = True
                stop_reason = "repaired"
            except VLMProviderTimeoutError as exc:
                raise VLMProviderTimeoutError(
                    str(exc),
                    raw_output=_bounded_output(first_attempt.text),
                    repaired_output=_bounded_output(getattr(exc, "raw_output", "")),
                    stop_reason="timeout",
                ) from exc
            except VLMStructuredOutputError as repair_error:
                raise VLMStructuredOutputError(
                    "Qwen returned invalid structured JSON after one text-only repair.",
                    raw_output=_bounded_output(first_attempt.text),
                    repaired_output=_bounded_output(repaired_output),
                    stop_reason=repair_attempt.stop_reason,
                ) from repair_error
            except VLMProviderError as exc:
                if not exc.raw_output:
                    exc.raw_output = _bounded_output(first_attempt.text)
                if not exc.repaired_output:
                    exc.repaired_output = _bounded_output(repaired_output)
                raise
            except Exception as exc:
                raise VLMProviderInferenceError(
                    f"Local Qwen JSON repair failed ({type(exc).__name__}).",
                    raw_output=_bounded_output(first_attempt.text),
                    repaired_output=_bounded_output(repaired_output),
                    stop_reason="repair_failed",
                ) from exc

        try:
            response = _wire_response_to_review(wire_response, batch)
            _validate_batch_bounds(response, batch)
        except VLMProviderError as exc:
            if not exc.raw_output:
                exc.raw_output = _bounded_output(first_attempt.text)
            if not exc.repaired_output:
                exc.repaired_output = _bounded_output(repaired_output)
            raise
        except (ValidationError, ValueError) as exc:
            raise VLMStructuredOutputError(
                "Qwen structured output could not be converted to batch timestamps.",
                raw_output=_bounded_output(first_attempt.text),
                repaired_output=_bounded_output(repaired_output),
                stop_reason="conversion_failed",
            ) from exc

        return VLMReviewResult(
            response=response,
            raw_output=_bounded_output(first_attempt.text),
            repaired_output=_bounded_output(repaired_output),
            repaired=repaired,
            elapsed_seconds=max(0.0, monotonic() - started_at),
            stop_reason=stop_reason,
            diagnostics=self.diagnostics,
        )

    def _prepare_visual_inputs(self, batch: VisualBatch):
        messages = _messages_for_batch(batch)
        try:
            from qwen_vl_utils import process_vision_info
        except ImportError as exc:
            raise VLMProviderUnavailableError(
                "qwen-vl-utils is unavailable. Install requirements-ai.txt before "
                "running video analysis."
            ) from exc

        prompt = self._processor.apply_chat_template(
            messages,
            tokenize=False,
            add_generation_prompt=True,
        )
        image_inputs, video_inputs = process_vision_info(messages)
        inputs = self._processor(
            text=[prompt],
            images=image_inputs,
            videos=video_inputs,
            padding=True,
            return_tensors="pt",
        )
        return inputs.to(self._device)

    def _prepare_repair_inputs(self, raw_output: str):
        messages = _repair_messages(raw_output)
        prompt = self._processor.apply_chat_template(
            messages,
            tokenize=False,
            add_generation_prompt=True,
        )
        inputs = self._processor(
            text=[prompt],
            padding=True,
            return_tensors="pt",
        )
        return inputs.to(self._device)

    def _generate(
        self,
        inputs,
        cancellation: CancellationToken,
        deadline: float,
        *,
        max_new_tokens: int,
        wire_schema: dict,
    ) -> _GenerationAttempt:
        if monotonic() >= deadline:
            raise VLMProviderTimeoutError(
                "Local Qwen VLM exceeded the per-batch generation deadline.",
                stop_reason="timeout",
            )
        tokenizer = getattr(self._processor, "tokenizer", self._processor)
        if self._tokenizer_data is None:
            self._tokenizer_data = _build_lmfe_tokenizer_data(tokenizer)
        prefix_allowed_tokens_fn = _build_schema_prefix_allowed_tokens_fn(
            self._tokenizer_data,
            wire_schema,
            initial_prompt_length=_input_sequence_length(inputs.input_ids),
        )
        stopping_criteria, deadline_criteria = _generation_stopping_criteria(
            cancellation,
            deadline,
        )
        eos_token_ids = _eos_token_ids(tokenizer)
        generation_kwargs: dict[str, Any] = {
            **inputs,
            "max_new_tokens": max_new_tokens,
            "do_sample": False,
            "use_cache": True,
            "prefix_allowed_tokens_fn": prefix_allowed_tokens_fn,
            "stopping_criteria": stopping_criteria,
        }
        if eos_token_ids:
            generation_kwargs["eos_token_id"] = eos_token_ids
        pad_token_id = getattr(tokenizer, "pad_token_id", None)
        if pad_token_id is not None:
            generation_kwargs["pad_token_id"] = pad_token_id

        try:
            generated_ids = self._model.generate(**generation_kwargs)
            trimmed_ids = [
                output_ids[len(input_ids) :]
                for input_ids, output_ids in zip(
                    inputs.input_ids,
                    generated_ids,
                    strict=True,
                )
            ]
            output_text = self._processor.batch_decode(
                trimmed_ids,
                skip_special_tokens=True,
                clean_up_tokenization_spaces=False,
            )[0]
        except VLMProviderError:
            raise
        except Exception as exc:
            raise VLMProviderInferenceError(
                f"Local Qwen generation failed ({type(exc).__name__})."
            ) from exc

        cancellation.raise_if_cancelled()
        token_count = len(trimmed_ids[0]) if trimmed_ids else 0
        if deadline_criteria.expired:
            raise VLMProviderTimeoutError(
                "Local Qwen VLM exceeded the per-batch generation deadline.",
                raw_output=_bounded_output(output_text),
                stop_reason="timeout",
            )
        stop_reason = "token_limit" if token_count >= max_new_tokens else "completed"
        return _GenerationAttempt(output_text, token_count, stop_reason)

    def check_ready(
        self,
        settings: AnalysisSettings,
        cancellation: CancellationToken,
    ) -> None:
        """Check dependencies and local cache without loading weights or decoding media."""
        cancellation.raise_if_cancelled()
        missing = [
            module_name
            for module_name in (
                "torch",
                "transformers",
                "qwen_vl_utils",
                "lmformatenforcer",
            )
            if find_spec(module_name) is None
        ]
        if missing:
            raise VLMProviderUnavailableError(
                "The local Qwen VLM dependencies are unavailable "
                f"({', '.join(missing)}). Install requirements-ai.txt before analysis."
            )
        if settings.quantization_mode == "4bit" and find_spec("bitsandbytes") is None:
            raise VLMQuantizationError(
                "4-bit Qwen was explicitly requested, but bitsandbytes is unavailable. "
                "Install requirements-ai.txt or select automatic quantization."
            )
        if _environment_flag("NSFW_CUTTER_AI_ALLOW_MODEL_DOWNLOAD"):
            return

        try:
            from huggingface_hub import try_to_load_from_cache
        except ImportError as exc:
            raise VLMProviderUnavailableError(
                "huggingface-hub is unavailable. Install requirements-ai.txt before analysis."
            ) from exc

        required_files = (
            "config.json",
            "model.safetensors.index.json",
            "preprocessor_config.json",
            "tokenizer_config.json",
            "tokenizer.json",
        )
        cached_files = {}
        for filename in required_files:
            cancellation.raise_if_cancelled()
            cached_files[filename] = _cached_model_file(
                try_to_load_from_cache,
                settings,
                self.model_cache_dir,
                filename,
            )
        try:
            index_payload = json.loads(
                cached_files["model.safetensors.index.json"].read_text(encoding="utf-8")
            )
            shard_names = sorted(set((index_payload.get("weight_map") or {}).values()))
        except (OSError, json.JSONDecodeError, AttributeError, TypeError, ValueError) as exc:
            raise VLMProviderUnavailableError(
                f"The cached local Qwen model '{settings.model_id}' is incomplete."
            ) from exc
        if not shard_names:
            raise VLMProviderUnavailableError(
                f"The cached local Qwen model '{settings.model_id}' has no weight shards."
            )
        for shard_name in shard_names:
            cancellation.raise_if_cancelled()
            _cached_model_file(
                try_to_load_from_cache,
                settings,
                self.model_cache_dir,
                str(shard_name),
            )

    def _ensure_loaded(
        self,
        settings: AnalysisSettings,
        cancellation: CancellationToken,
    ) -> None:
        loaded_key = (
            settings.model_id,
            settings.model_revision,
            settings.use_gpu,
            settings.quantization_mode,
        )
        if self._loaded_key == loaded_key:
            return
        self.check_ready(settings, cancellation)
        try:
            import torch
            from transformers import (
                AutoProcessor,
                BitsAndBytesConfig,
                Qwen2_5_VLForConditionalGeneration,
            )
        except ImportError as exc:
            raise VLMProviderUnavailableError(
                "The local Qwen VLM dependencies are unavailable. Install "
                "requirements-ai.txt before running video analysis."
            ) from exc

        allow_download = _environment_flag("NSFW_CUTTER_AI_ALLOW_MODEL_DOWNLOAD")
        use_cuda = bool(settings.use_gpu and torch.cuda.is_available())
        if settings.quantization_mode == "4bit" and not use_cuda:
            raise VLMQuantizationError(
                "4-bit Qwen requires a CUDA GPU, but CUDA is unavailable or disabled."
            )
        self._device = "cuda" if use_cuda else "cpu"
        self.warnings = []
        if settings.use_gpu and not use_cuda:
            warning = "CUDA is unavailable; Qwen VLM is using the slow CPU fallback."
            logger.warning(warning)
            self.warnings.append(warning)
        elif not settings.use_gpu:
            self.warnings.append("Qwen VLM is using CPU mode; local analysis will be slow.")
        common_kwargs = {
            "cache_dir": str(self.model_cache_dir),
            "revision": settings.model_revision,
            "local_files_only": not allow_download,
        }
        cancellation.raise_if_cancelled()
        try:
            processor = AutoProcessor.from_pretrained(
                settings.model_id,
                min_pixels=_QWEN_MIN_PIXELS,
                max_pixels=_QWEN_MAX_PIXELS,
                **common_kwargs,
            )
        except Exception as exc:
            raise VLMProviderUnavailableError(
                _model_load_error(settings.model_id, allow_download, exc)
            ) from exc
        cancellation.raise_if_cancelled()

        try:
            if use_cuda:
                model, quantization = _load_preferred_qwen_model(
                    Qwen2_5_VLForConditionalGeneration,
                    BitsAndBytesConfig,
                    torch,
                    settings,
                    common_kwargs,
                    warnings=self.warnings,
                )
            else:
                model = _load_qwen_model(
                    Qwen2_5_VLForConditionalGeneration,
                    torch,
                    settings,
                    common_kwargs,
                    use_cuda=False,
                )
                quantization = "none"
        except VLMProviderError:
            raise
        except Exception as exc:
            raise VLMProviderUnavailableError(
                _model_load_error(settings.model_id, allow_download, exc)
            ) from exc
        cancellation.raise_if_cancelled()

        if use_cuda and _uses_cpu_offload(model):
            self.warnings.append(
                "Qwen VLM is using the GPU with CPU layer offload because available "
                "VRAM cannot hold the FP16 model."
            )

        self._processor = processor
        self._model = model
        self._tokenizer_data = None
        self._loaded_key = loaded_key
        self.diagnostics = _provider_diagnostics(
            model,
            torch,
            use_cuda=use_cuda,
            quantization=quantization,
        )


def _load_preferred_qwen_model(
    model_class,
    bitsandbytes_config_class,
    torch,
    settings,
    common_kwargs,
    *,
    warnings: list[str],
    bitsandbytes_available: bool | None = None,
):
    """Try all-GPU NF4 first, then the safe FP16 Accelerate placement in auto mode."""
    use_4bit = settings.quantization_mode in {"auto", "4bit"}
    available = (
        find_spec("bitsandbytes") is not None
        if bitsandbytes_available is None
        else bitsandbytes_available
    )
    if use_4bit and available:
        try:
            quantization_config = bitsandbytes_config_class(
                load_in_4bit=True,
                bnb_4bit_quant_type="nf4",
                bnb_4bit_use_double_quant=True,
                bnb_4bit_compute_dtype=torch.float16,
            )
            model = _load_qwen_model(
                model_class,
                torch,
                settings,
                common_kwargs,
                use_cuda=True,
                quantization_config=quantization_config,
                all_gpu=True,
            )
            return model, "bitsandbytes-nf4"
        except Exception as exc:
            _release_failed_cuda_load(torch)
            if settings.quantization_mode == "4bit":
                raise VLMQuantizationError(
                    "4-bit Qwen was explicitly requested but initialization failed "
                    f"({type(exc).__name__})."
                ) from exc
            warnings.append(
                "4-bit all-GPU Qwen initialization failed; using FP16 GPU/CPU "
                f"placement ({type(exc).__name__})."
            )
    elif use_4bit and settings.quantization_mode == "4bit":
        raise VLMQuantizationError(
            "4-bit Qwen was explicitly requested, but bitsandbytes is unavailable."
        )
    elif use_4bit:
        warnings.append(
            "bitsandbytes is unavailable; using FP16 Qwen with automatic GPU/CPU placement."
        )

    model = _load_qwen_model(
        model_class,
        torch,
        settings,
        common_kwargs,
        use_cuda=True,
    )
    return model, "none"


def _load_qwen_model(
    model_class,
    torch,
    settings,
    common_kwargs,
    *,
    use_cuda: bool,
    quantization_config=None,
    all_gpu: bool = False,
):
    load_kwargs = {
        **common_kwargs,
        "torch_dtype": torch.float16 if use_cuda else torch.float32,
        "low_cpu_mem_usage": True,
    }
    if use_cuda and quantization_config is not None:
        load_kwargs.update(
            quantization_config=quantization_config,
            device_map={"": 0} if all_gpu else "auto",
        )
    elif use_cuda:
        # FP16 is the compatibility fallback. Accelerate fills the GPU first and
        # offloads only overflow layers instead of silently moving all inference to CPU.
        load_kwargs.update(
            device_map="auto",
            max_memory=_inference_memory_budget(torch),
            offload_state_dict=True,
        )

    model = model_class.from_pretrained(settings.model_id, **load_kwargs)
    if not use_cuda:
        model.to("cpu")
    model.eval()
    return model


def _release_failed_cuda_load(torch) -> None:
    gc.collect()
    try:
        torch.cuda.empty_cache()
    except Exception:
        logger.debug("Unable to empty CUDA cache after a failed quantized load", exc_info=True)


def _inference_memory_budget(torch) -> dict[int | str, int]:
    import psutil

    # Initialize CUDA before measuring free memory; CUDA kernels and the desktop
    # display already consume part of the nominal VRAM on Windows/WDDM.
    torch.empty(1, device="cuda")
    free_vram, total_vram = torch.cuda.mem_get_info(0)
    vram_headroom = max(1536 * 1024**2, int(total_vram * 0.20))
    gpu_budget = max(512 * 1024**2, int(free_vram) - vram_headroom)

    available_ram = int(psutil.virtual_memory().available)
    cpu_headroom = max(2 * 1024**3, int(available_ram * 0.20))
    cpu_budget = max(2 * 1024**3, available_ram - cpu_headroom)
    return {0: gpu_budget, "cpu": cpu_budget}


def _uses_cpu_offload(model) -> bool:
    device_map = getattr(model, "hf_device_map", {})
    return any(str(device).casefold() == "cpu" for device in device_map.values())


def _provider_diagnostics(model, torch, *, use_cuda: bool, quantization: str):
    device_map = getattr(model, "hf_device_map", {}) or {}
    cpu_layer_count = sum(
        1 for device in device_map.values() if str(device).casefold() == "cpu"
    )
    gpu_layer_count = sum(
        1
        for device in device_map.values()
        if str(device).casefold() in {"0", "cuda", "cuda:0"}
        or device == 0
    )
    if not device_map:
        # Some Transformers 5 quantized loaders place the complete model on CUDA
        # but do not retain `hf_device_map`; represent that whole-model placement
        # as one unit rather than incorrectly reporting zero GPU layers.
        gpu_layer_count = 1 if use_cuda else 0
        cpu_layer_count = 0 if use_cuda else 1
    if not use_cuda:
        device_mode = "cpu"
    elif cpu_layer_count:
        device_mode = "hybrid"
    else:
        device_mode = "cuda"
    device_name = ""
    if use_cuda:
        try:
            device_name = str(torch.cuda.get_device_name(0))
        except (AttributeError, RuntimeError):
            device_name = "CUDA GPU"
    return ProviderDiagnostics(
        device_mode=device_mode,
        device_name=device_name,
        precision="float16" if use_cuda else "float32",
        quantization=quantization,
        gpu_layer_count=gpu_layer_count,
        cpu_layer_count=cpu_layer_count,
    )


def _model_load_error(model_id: str, allow_download: bool, error: Exception) -> str:
    if allow_download:
        return (
            f"Unable to load local Qwen model '{model_id}' "
            f"({type(error).__name__})."
        )
    return (
        f"Local Qwen model '{model_id}' is not available in the user model cache. "
        "Download it during setup or set NSFW_CUTTER_AI_ALLOW_MODEL_DOWNLOAD=1 "
        "for an explicit first-run download."
    )


def _cached_model_file(cache_lookup, settings, cache_dir: Path, filename: str) -> Path:
    cached = cache_lookup(
        settings.model_id,
        filename,
        cache_dir=str(cache_dir),
        revision=settings.model_revision,
    )
    if not isinstance(cached, str) or not Path(cached).is_file():
        raise VLMProviderUnavailableError(
            f"Local Qwen model '{settings.model_id}' is not available at the pinned "
            "revision in the user model cache. Set "
            "NSFW_CUTTER_AI_ALLOW_MODEL_DOWNLOAD=1 for an explicit setup download."
        )
    return Path(cached)


def _messages_for_batch(batch: VisualBatch) -> list[dict]:
    frame_map = ", ".join(
        f"frame {index + 1}={frame.timestamp_seconds:.3f}s"
        for index, frame in enumerate(batch.frames)
    )
    display_kind = (
        "The single image is a contact sheet whose numbered panels are frames 1 through "
        f"{len(batch.frames)}. "
        if batch.contact_sheet_path is not None
        else f"The {len(batch.frames)} images are frames 1 through {len(batch.frames)}. "
    )
    instructions = (
        "Review only these frames for possible NSFW visual evidence. Visual evidence is "
        "required; dialogue or captions alone are insufficient. "
        + display_kind
        + "Use only nudity, sexual_activity, sexual_context, or uncertain. Return one "
        "JSON object and no prose. Return at most four suggestions, or an empty array. "
        "Frame numbers are one-based. first_frame and last_frame bound the visible event; "
        "evidence_frames must be within that range. Use a confidence from 0.0 to 1.0 and "
        "a neutral reason of no more than eight words. Every suggestion must contain, in "
        "order, category, confidence, first_frame, last_frame, evidence_frames, and reason. "
        "When there is no visual evidence, return exactly {\"suggestions\":[]}. "
        f"Frame mapping: {frame_map}."
    )
    if batch.contact_sheet_path is not None:
        content = [{"type": "image", "image": str(batch.contact_sheet_path)}]
    else:
        content = [
            {"type": "image", "image": str(frame.path)} for frame in batch.frames
        ]
    content.append({"type": "text", "text": instructions})
    return [{"role": "user", "content": content}]


def _repair_messages(raw_output: str) -> list[dict]:
    bounded_raw = str(raw_output or "")[:_MAX_REPAIR_INPUT_CHARS]
    instructions = (
        "Repair the candidate into exactly one JSON object matching the required schema. "
        "Preserve its category, confidence, frame numbers, and reason; do not add visual "
        "claims. Remove prose and unknown fields. If no complete suggestion can be "
        "recovered, return {\"suggestions\":[]}. Candidate follows:\n"
        + bounded_raw
    )
    return [
        {
            "role": "user",
            "content": [{"type": "text", "text": instructions}],
        }
    ]


def _validate_wire_output(output_text: str, batch: VisualBatch | None = None) -> VLMWireResponse:
    try:
        payload_text = _first_json_object(output_text)
        response = VLMWireResponse.model_validate_json(payload_text)
        if batch is not None:
            frame_count = len(batch.frames)
            for suggestion in response.suggestions:
                referenced_frames = [
                    suggestion.first_frame,
                    suggestion.last_frame,
                    *suggestion.evidence_frames,
                ]
                if any(frame > frame_count for frame in referenced_frames):
                    raise ValueError("wire response references a frame outside the batch")
        return response
    except (json.JSONDecodeError, ValidationError, ValueError) as exc:
        raise VLMStructuredOutputError(
            "Qwen returned structured JSON that did not match the compact wire schema.",
            raw_output=_bounded_output(output_text),
            stop_reason="invalid_schema",
        ) from exc


def _wire_schema_for_batch(batch: VisualBatch) -> dict:
    """Narrow the static contract so constrained decoding cannot invent frame IDs."""
    schema = deepcopy(VLMWireResponse.model_json_schema())
    frame_count = len(batch.frames)
    suggestion_schema = schema["$defs"]["VLMWireSuggestion"]
    properties = suggestion_schema["properties"]
    properties["first_frame"]["maximum"] = frame_count
    properties["last_frame"]["maximum"] = frame_count
    evidence_schema = properties["evidence_frames"]
    evidence_schema["maxItems"] = min(frame_count, 8)
    evidence_schema["items"].update(minimum=1, maximum=frame_count)
    return schema


def _wire_response_to_review(
    wire_response: VLMWireResponse,
    batch: VisualBatch,
) -> VLMReviewResponse:
    if batch.end_seconds <= batch.start_seconds:
        raise ValueError("visual batch must have a non-zero interval")
    items: list[VLMReviewItem] = []
    for suggestion in wire_response.suggestions:
        first_timestamp = batch.frames[suggestion.first_frame - 1].timestamp_seconds
        last_timestamp = batch.frames[suggestion.last_frame - 1].timestamp_seconds
        start_seconds = max(batch.start_seconds, first_timestamp - 0.5)
        end_seconds = min(batch.end_seconds, last_timestamp + 0.5)
        if end_seconds <= start_seconds:
            start_seconds = batch.start_seconds
            end_seconds = batch.end_seconds
        evidence_timestamps = [
            batch.frames[frame_number - 1].timestamp_seconds
            for frame_number in suggestion.evidence_frames
        ]
        items.append(
            VLMReviewItem(
                category=suggestion.category,
                confidence=suggestion.confidence,
                start_seconds=float(start_seconds),
                end_seconds=float(end_seconds),
                evidence_timestamps=[float(value) for value in evidence_timestamps],
                reason=suggestion.reason,
                needs_review=True,
            )
        )
    return VLMReviewResponse(suggestions=items)


def _validate_output(output_text: str) -> VLMReviewResponse:
    """Validate the legacy rich response shape for compatibility with existing callers."""
    try:
        payload_text = _first_json_object(output_text)
        return VLMReviewResponse.model_validate_json(payload_text)
    except (json.JSONDecodeError, ValidationError, ValueError) as exc:
        raise VLMStructuredOutputError(
            "Qwen returned structured JSON that did not match the required schema.",
            raw_output=_bounded_output(output_text),
            stop_reason="invalid_schema",
        ) from exc


def _first_json_object(value: str) -> str:
    text = str(value or "").strip()
    decoder = json.JSONDecoder()
    for index, character in enumerate(text):
        if character != "{":
            continue
        try:
            _payload, end_index = decoder.raw_decode(text[index:])
        except json.JSONDecodeError:
            continue
        return text[index : index + end_index]
    raise ValueError("response did not contain a JSON object")


def _validate_batch_bounds(response: VLMReviewResponse, batch: VisualBatch) -> None:
    lower_bound = batch.start_seconds
    upper_bound = batch.end_seconds
    for suggestion in response.suggestions:
        if (
            suggestion.start_seconds < lower_bound
            or suggestion.end_seconds > upper_bound
            or any(
                timestamp < lower_bound or timestamp > upper_bound
                for timestamp in suggestion.evidence_timestamps
            )
        ):
            raise VLMStructuredOutputError(
                "Qwen returned an interval outside the reviewed batch"
            )


def _build_lmfe_tokenizer_data(tokenizer):
    """Build LM Format Enforcer data without its Transformers-4-only adapter.

    lm-format-enforcer 0.11.3 imports a tokenizer class from a location removed in
    Transformers 5. Its public core API remains compatible, so this small adapter
    keeps schema enforcement working without monkey-patching either dependency.
    """
    try:
        from lmformatenforcer import TokenEnforcerTokenizerData
    except ImportError as exc:
        raise VLMProviderUnavailableError(
            "lm-format-enforcer is unavailable. Install requirements-ai.txt before analysis."
        ) from exc

    try:
        token_zero = tokenizer.encode("0", add_special_tokens=False)[-1]
    except TypeError:
        token_zero = tokenizer.encode("0")[-1]
    special_ids = set(getattr(tokenizer, "all_special_ids", []))
    regular_tokens: list[tuple[int, str, bool]] = []
    for token_id in range(len(tokenizer)):
        if token_id in special_ids:
            continue
        decoded_after_zero = tokenizer.decode([token_zero, token_id])[1:]
        decoded_regular = tokenizer.decode([token_id])
        is_word_start = len(decoded_after_zero) > len(decoded_regular)
        regular_tokens.append((token_id, decoded_after_zero, is_word_start))

    def decode(tokens: list[int]) -> str:
        return tokenizer.decode(tokens).rstrip("�")

    eos_ids = _eos_token_ids(tokenizer)
    if not eos_ids:
        raise VLMProviderUnavailableError("The Qwen tokenizer has no EOS token.")
    return TokenEnforcerTokenizerData(
        regular_tokens,
        decode,
        eos_ids,
        False,
        len(tokenizer),
    )


def _build_schema_prefix_allowed_tokens_fn(
    tokenizer_data,
    schema: dict,
    *,
    initial_prompt_length: int = 0,
):
    try:
        from lmformatenforcer import JsonSchemaParser, TokenEnforcer
    except ImportError as exc:
        raise VLMProviderUnavailableError(
            "lm-format-enforcer is unavailable. Install requirements-ai.txt before analysis."
        ) from exc
    parser = JsonSchemaParser(schema)
    token_enforcer = TokenEnforcer(tokenizer_data, parser)
    # Fix the JSON key order and whitespace so Qwen spends its short output budget
    # on evidence rather than exploring equivalent serializations.
    token_enforcer.root_parser.config.force_json_field_order = True
    token_enforcer.root_parser.config.max_consecutive_whitespaces = 1
    token_enforcer.root_parser.config.max_json_array_length = 8

    def allowed_tokens(_batch_id: int, sent) -> list[int]:
        token_sequence = sent.tolist() if hasattr(sent, "tolist") else list(sent)
        generated_sequence = token_sequence[initial_prompt_length:]
        return token_enforcer.get_allowed_tokens(generated_sequence).allowed_tokens

    # Keep the enforcer alive and make it inspectable in focused tests.
    allowed_tokens.token_enforcer = token_enforcer  # type: ignore[attr-defined]
    return allowed_tokens


def _input_sequence_length(input_ids) -> int:
    shape = getattr(input_ids, "shape", None)
    if shape is not None and len(shape) >= 2:
        return int(shape[-1])
    if not input_ids:
        return 0
    return len(input_ids[0])


def _eos_token_ids(tokenizer) -> list[int]:
    result: list[int] = []
    eos_token_id = getattr(tokenizer, "eos_token_id", None)
    if isinstance(eos_token_id, int) and eos_token_id >= 0:
        result.append(eos_token_id)
    elif isinstance(eos_token_id, (list, tuple)):
        result.extend(token for token in eos_token_id if isinstance(token, int) and token >= 0)
    try:
        im_end_id = tokenizer.convert_tokens_to_ids("<|im_end|>")
    except (AttributeError, TypeError, ValueError):
        im_end_id = None
    unknown_id = getattr(tokenizer, "unk_token_id", None)
    if isinstance(im_end_id, int) and im_end_id >= 0 and im_end_id != unknown_id:
        result.append(im_end_id)
    return list(dict.fromkeys(result))


def _generation_stopping_criteria(
    cancellation: CancellationToken,
    deadline: float,
):
    from transformers import StoppingCriteria, StoppingCriteriaList

    class CancellationCriteria(StoppingCriteria):
        def __call__(self, input_ids, scores, **kwargs) -> bool:
            return cancellation.is_cancelled

    class DeadlineCriteria(StoppingCriteria):
        def __init__(self, monotonic_deadline: float) -> None:
            self.deadline = monotonic_deadline
            self.expired = False

        def __call__(self, input_ids, scores, **kwargs) -> bool:
            self.expired = monotonic() >= self.deadline
            return self.expired

    deadline_criteria = DeadlineCriteria(deadline)
    return (
        StoppingCriteriaList([CancellationCriteria(), deadline_criteria]),
        deadline_criteria,
    )


def _cancellation_stopping_criteria(cancellation: CancellationToken):
    """Compatibility helper retained for callers that only need cancellation."""
    from transformers import StoppingCriteria, StoppingCriteriaList

    class CancellationCriteria(StoppingCriteria):
        def __call__(self, input_ids, scores, **kwargs) -> bool:
            return cancellation.is_cancelled

    return StoppingCriteriaList([CancellationCriteria()])


def _bounded_output(value: str) -> str:
    return str(value or "")[:_MAX_DIAGNOSTIC_OUTPUT_CHARS]


def _environment_flag(name: str) -> bool:
    return os.environ.get(name, "").strip().casefold() in {"1", "true", "yes", "on"}
