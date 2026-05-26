class AISettings:
    def __init__(self, accessor):
        self._accessor = accessor

    def get_user_prompt(self) -> str:
        return self._accessor.reload().user_prompt

    def set_user_prompt(self, prompt: str):
        return self._accessor.update(user_prompt=prompt)

    def get_provider(self) -> str:
        return str(self._accessor.reload().ai_provider)

    def set_provider(self, provider: str):
        return self._accessor.update(ai_provider=provider)

    def get_model_name(self) -> str:
        return self._accessor.reload().ai_model_name

    def set_model_name(self, model_name: str):
        return self._accessor.update(ai_model_name=model_name)

    def get_batch_size(self) -> int:
        return self._accessor.reload().batch_size

    def set_batch_size(self, batch_size: int):
        return self._accessor.update(batch_size=batch_size)

    def get_enable_gpu(self) -> bool:
        return self._accessor.reload().enable_gpu

    def set_enable_gpu(self, enabled: bool):
        return self._accessor.update(enable_gpu=enabled)

    def get_confidence_threshold(self) -> float:
        return self._accessor.reload().confidence_threshold

    def set_confidence_threshold(self, value: float):
        return self._accessor.update(confidence_threshold=value)
