"""Provider adapters: turn a prompt into generated solution text.

One small interface (`Adapter`): given a prompt, return the model's response
text plus the exact model identifier the provider reported. API keys are read
from environment variables only (`ANTHROPIC_API_KEY`, `OPENAI_API_KEY`) and
are never written, printed, or logged. An adapter with a missing SDK or key
reports itself unavailable; the matrix skips it and continues.

`LocalAdapter` is the no-API-keys fallback: it reads pre-generated solutions
from a directory tree `<root>/<task>/<condition>/sample-<n>.py`.
"""

from __future__ import annotations

import os
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol


@dataclass(frozen=True)
class GenerationRequest:
    """One sample to generate."""

    prompt: str
    task: str
    condition: str
    sample: int  # 1-based
    temperature: float


@dataclass(frozen=True)
class GenerationResult:
    """A model response, persisted verbatim by the matrix."""

    text: str  # raw response text
    model_id: str  # exact identifier as the provider returned it


class Adapter(Protocol):
    """Minimal provider interface."""

    name: str

    def unavailable_reason(self) -> str | None:
        """None if usable, else a human-readable reason to skip this model."""
        ...

    def generate(self, request: GenerationRequest) -> GenerationResult:
        """Produce one solution for the request."""
        ...


def extract_code(text: str) -> str:
    """Pull the solution out of a response: largest fenced code block, else all."""
    fences = re.findall(r"```(?:python|py)?\n(.*?)```", text, flags=re.DOTALL)
    if fences:
        return max(fences, key=len).strip() + "\n"
    return text.strip() + "\n"


class AnthropicAdapter:
    """Generates via the Anthropic Messages API. Key: ANTHROPIC_API_KEY."""

    def __init__(self, model: str) -> None:
        self.model = model
        self.name = f"anthropic:{model}"

    def unavailable_reason(self) -> str | None:
        try:
            import anthropic  # noqa: F401
        except ImportError:
            return "anthropic SDK not installed (pip install -r evals/requirements.txt)"
        if not os.environ.get("ANTHROPIC_API_KEY"):
            return "ANTHROPIC_API_KEY not set"
        return None

    def generate(self, request: GenerationRequest) -> GenerationResult:
        import anthropic

        client = anthropic.Anthropic()
        response = client.messages.create(
            model=self.model,
            max_tokens=2048,
            temperature=request.temperature,
            messages=[{"role": "user", "content": request.prompt}],
        )
        text = "".join(block.text for block in response.content if block.type == "text")
        return GenerationResult(text=text, model_id=response.model)


class OpenAIAdapter:
    """Generates via an OpenAI-compatible Chat Completions API.

    Serves both api.openai.com (key: OPENAI_API_KEY) and, via ``base_url``,
    OpenAI-compatible gateways such as OpenRouter (key: OPENROUTER_API_KEY).
    """

    def __init__(
        self,
        model: str,
        provider: str = "openai",
        base_url: str | None = None,
        key_env: str = "OPENAI_API_KEY",
    ) -> None:
        self.model = model
        self.name = f"{provider}:{model}"
        self.base_url = base_url
        self.key_env = key_env

    def unavailable_reason(self) -> str | None:
        try:
            import openai  # noqa: F401
        except ImportError:
            return "openai SDK not installed (pip install -r evals/requirements.txt)"
        if not os.environ.get(self.key_env):
            return f"{self.key_env} not set"
        return None

    def generate(self, request: GenerationRequest) -> GenerationResult:
        import openai

        client = openai.OpenAI(base_url=self.base_url, api_key=os.environ[self.key_env])
        response = client.chat.completions.create(
            model=self.model,
            temperature=request.temperature,
            messages=[{"role": "user", "content": request.prompt}],
        )
        text = response.choices[0].message.content or ""
        return GenerationResult(text=text, model_id=response.model)


class LocalAdapter:
    """Reads pre-generated solutions from `<root>/<task>/<condition>/sample-<n>.py`.

    The documented fallback for running the benchmark without any API keys:
    generate solutions elsewhere, drop them into the tree, and score them here.
    """

    def __init__(self, root: str | Path) -> None:
        self.root = Path(root)
        self.name = f"local:{self.root.name}"

    def unavailable_reason(self) -> str | None:
        if not self.root.is_dir():
            return f"local solutions directory not found: {self.root}"
        return None

    def generate(self, request: GenerationRequest) -> GenerationResult:
        path = (
            self.root / request.task / request.condition / f"sample-{request.sample}.py"
        )
        if not path.exists():
            raise FileNotFoundError(f"no pre-generated solution at {path}")
        return GenerationResult(text=path.read_text(), model_id=self.name)


def build_adapter(spec: str) -> Adapter:
    """Build an adapter from a --models spec: provider:argument."""
    provider, _, arg = spec.partition(":")
    if not arg:
        raise ValueError(f"--models spec needs provider:argument, got {spec!r}")
    if provider == "anthropic":
        return AnthropicAdapter(arg)
    if provider == "openai":
        return OpenAIAdapter(arg)
    if provider == "openrouter":
        return OpenAIAdapter(
            arg,
            provider="openrouter",
            base_url="https://openrouter.ai/api/v1",
            key_env="OPENROUTER_API_KEY",
        )
    if provider == "local":
        return LocalAdapter(arg)
    raise ValueError(
        f"unknown provider {provider!r} in {spec!r};"
        " use anthropic:, openai:, openrouter:, local:"
    )
