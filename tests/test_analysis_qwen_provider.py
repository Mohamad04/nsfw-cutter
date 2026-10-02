import unittest
from typing import ClassVar

from services.analysis.contracts import AnalysisSettings
from services.analysis.providers.base import VLMQuantizationError
from services.analysis.providers.qwen import (
    _load_preferred_qwen_model,
    _load_qwen_model,
    _uses_cpu_offload,
)


class _FakeCuda:
    @staticmethod
    def mem_get_info(_device):
        return 7 * 1024**3, 8 * 1024**3


class _FakeTorch:
    float16 = "float16"
    float32 = "float32"
    cuda = _FakeCuda()

    @staticmethod
    def empty(_size, *, device):
        if device != "cuda":
            raise AssertionError("CUDA must be initialized before measuring memory")
        return object()


class _FakeModel:
    def __init__(self):
        self.to_calls = []
        self.eval_called = False
        self.hf_device_map = {"visual": 0, "language.layers.0": "cpu"}

    def to(self, device):
        self.to_calls.append(device)
        return self

    def eval(self):
        self.eval_called = True
        return self


class _FakeModelClass:
    calls: ClassVar[list[tuple[str, dict]]] = []

    @classmethod
    def from_pretrained(cls, model_id, **kwargs):
        cls.calls.append((model_id, kwargs))
        return _FakeModel()


class _FailFirstModelClass(_FakeModelClass):
    attempts = 0

    @classmethod
    def from_pretrained(cls, model_id, **kwargs):
        cls.calls.append((model_id, kwargs))
        cls.attempts += 1
        if cls.attempts == 1:
            raise RuntimeError("quantized load failed")
        return _FakeModel()


class _FakeBitsAndBytesConfig:
    calls: ClassVar[list[dict]] = []

    def __init__(self, **kwargs):
        self.calls.append(kwargs)
        self.kwargs = kwargs


class QwenModelLoadingTests(unittest.TestCase):
    def setUp(self):
        _FakeModelClass.calls = []
        _FailFirstModelClass.calls = []
        _FailFirstModelClass.attempts = 0
        _FakeBitsAndBytesConfig.calls = []
        self.settings = AnalysisSettings(use_gpu=True)
        self.common_kwargs = {
            "cache_dir": "model-cache",
            "revision": self.settings.model_revision,
            "local_files_only": True,
        }

    def test_cuda_load_uses_automatic_gpu_first_layer_offload(self):
        model = _load_qwen_model(
            _FakeModelClass,
            _FakeTorch,
            self.settings,
            self.common_kwargs,
            use_cuda=True,
        )

        _model_id, kwargs = _FakeModelClass.calls[0]
        self.assertEqual(kwargs["device_map"], "auto")
        self.assertTrue(kwargs["offload_state_dict"])
        self.assertEqual(kwargs["torch_dtype"], "float16")
        self.assertGreater(kwargs["max_memory"][0], 0)
        self.assertGreater(kwargs["max_memory"]["cpu"], 0)
        self.assertEqual(model.to_calls, [])
        self.assertTrue(model.eval_called)
        self.assertTrue(_uses_cpu_offload(model))

    def test_cpu_load_moves_the_complete_model_to_cpu(self):
        model = _load_qwen_model(
            _FakeModelClass,
            _FakeTorch,
            AnalysisSettings(use_gpu=False),
            self.common_kwargs,
            use_cuda=False,
        )

        _model_id, kwargs = _FakeModelClass.calls[0]
        self.assertNotIn("device_map", kwargs)
        self.assertEqual(kwargs["torch_dtype"], "float32")
        self.assertEqual(model.to_calls, ["cpu"])

    def test_auto_mode_prefers_nf4_with_the_complete_model_on_gpu(self):
        warnings = []
        model, quantization = _load_preferred_qwen_model(
            _FakeModelClass,
            _FakeBitsAndBytesConfig,
            _FakeTorch,
            self.settings,
            self.common_kwargs,
            warnings=warnings,
            bitsandbytes_available=True,
        )

        _model_id, kwargs = _FakeModelClass.calls[0]
        self.assertEqual(quantization, "bitsandbytes-nf4")
        self.assertEqual(kwargs["device_map"], {"": 0})
        self.assertIn("quantization_config", kwargs)
        self.assertNotIn("max_memory", kwargs)
        self.assertEqual(
            _FakeBitsAndBytesConfig.calls[0]["bnb_4bit_quant_type"],
            "nf4",
        )
        self.assertEqual(warnings, [])
        self.assertTrue(model.eval_called)

    def test_auto_mode_falls_back_to_fp16_accelerate_after_nf4_failure(self):
        warnings = []
        _model, quantization = _load_preferred_qwen_model(
            _FailFirstModelClass,
            _FakeBitsAndBytesConfig,
            _FakeTorch,
            self.settings,
            self.common_kwargs,
            warnings=warnings,
            bitsandbytes_available=True,
        )

        self.assertEqual(quantization, "none")
        self.assertEqual(len(_FailFirstModelClass.calls), 2)
        _model_id, fallback_kwargs = _FailFirstModelClass.calls[1]
        self.assertEqual(fallback_kwargs["device_map"], "auto")
        self.assertNotIn("quantization_config", fallback_kwargs)
        self.assertTrue(any("4-bit" in warning for warning in warnings))

    def test_explicit_4bit_mode_never_silently_falls_back(self):
        settings = AnalysisSettings(use_gpu=True, quantization_mode="4bit")

        with self.assertRaises(VLMQuantizationError):
            _load_preferred_qwen_model(
                _FakeModelClass,
                _FakeBitsAndBytesConfig,
                _FakeTorch,
                settings,
                self.common_kwargs,
                warnings=[],
                bitsandbytes_available=False,
            )


if __name__ == "__main__":
    unittest.main()
