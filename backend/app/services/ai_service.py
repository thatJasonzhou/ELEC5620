from abc import ABC, abstractmethod
from typing import Any

from openai import AsyncOpenAI

from app.config import Settings


class AIConfigurationError(RuntimeError):
    pass


class AIService(ABC):
    @abstractmethod
    async def generate(self, prompt: str, output_schema: dict[str, Any] | None = None) -> str:
        raise NotImplementedError


class MockAIService(AIService):
    async def generate(self, prompt: str, output_schema: dict[str, Any] | None = None) -> str:
        del prompt, output_schema
        return "Mock AI result for local development and automated tests."


class OpenAIService(AIService):
    def __init__(self, api_key: str, model: str) -> None:
        if not api_key or not model:
            raise AIConfigurationError(
                "OPENAI_API_KEY and OPENAI_MODEL are required when AI_PROVIDER=openai."
            )
        self._client = AsyncOpenAI(api_key=api_key)
        self._model = model

    async def generate(self, prompt: str, output_schema: dict[str, Any] | None = None) -> str:
        del output_schema
        response = await self._client.responses.create(model=self._model, input=prompt)
        return response.output_text


def create_ai_service(settings: Settings) -> AIService:
    if settings.ai_provider == "openai":
        return OpenAIService(settings.openai_api_key, settings.openai_model)
    return MockAIService()

