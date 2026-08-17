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

import ast
import os
import re
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol

# Both adapters generate under the same ceiling: a provider-default cap on one
# side and an explicit cap on the other would make truncation risk differ by
# provider, which is not a property of the models being compared.
MAX_TOKENS = 2048


@dataclass(frozen=True)
class GenerationRequest:
    """One sample to generate."""

    prompt: str
    task: str
    condition: str
    sample: int  # 1-based
    temperature: float


class EmptyCompletionError(RuntimeError):
    """The provider returned no content.

    Raised rather than returned: an empty completion is a failure of the API
    call, not a solution the model wrote. Scoring it as a model failure is how
    a gateway hiccup gets published as a model's pass rate.
    """


@dataclass(frozen=True)
class GenerationResult:
    """A model response, persisted verbatim by the matrix."""

    text: str  # raw response text
    model_id: str  # exact identifier as the provider returned it
    finish_reason: str | None = None  # so truncation is visible after the fact


class Adapter(Protocol):
    """Minimal provider interface."""

    name: str

    def unavailable_reason(self) -> str | None:
        """None if usable, else a human-readable reason to skip this model."""
        ...

    def generate(self, request: GenerationRequest) -> GenerationResult:
        """Produce one solution for the request."""
        ...


_FENCE = re.compile(r"```(.*?)```", re.DOTALL)
_LANG_TAG = re.compile(r"^(?:python3|python|py)", re.IGNORECASE)
_LANG_ONLY = re.compile(r"(?:python3|python|py)", re.IGNORECASE)


def _defines_app(source: str) -> bool:
    """Does this parse as Python and assign a module-level `app`?"""
    try:
        tree = ast.parse(source)
    except SyntaxError:
        return False
    return any(
        isinstance(node, ast.Assign)
        and any(
            isinstance(target, ast.Name) and target.id == "app"
            for target in node.targets
        )
        for node in ast.walk(tree)
    )


def _candidates(block: str) -> list[str]:
    """Plausible readings of one fenced block, best-effort first.

    The opening fence is not always well formed. A model that emits
    ```` ```pythonfrom fastapi import ... ```` wrote correct code behind a
    missing newline, so a reading that drops the glued-on language tag has to
    be tried too — otherwise the harness's parsing bug is scored as the
    model's syntax error.
    """
    body = block.lstrip("\n")
    first, newline, rest = body.partition("\n")
    readings = []
    if newline and _LANG_ONLY.fullmatch(first.strip()):
        readings.append(rest)  # ```python\n<code>  — the ordinary shape
    readings.append(body)  # ```\n<code>  — no language tag
    glued = _LANG_TAG.sub("", body, count=1)
    if glued != body:
        readings.append(glued)  # ```pythonfrom ...  — tag glued to the code
    return [reading.strip() for reading in readings if reading.strip()]


def extract_code(text: str) -> str:
    """Pull `app.py` out of a response.

    Prefers the *last* block that parses and defines `app`: a response often
    re-lists the provided `helpers.py` next to its answer, and that listing can
    be the longer of the two, so "largest block" silently saves the wrong file.
    Falls back to the largest block, then to the whole response.
    """
    blocks = [block for block in _FENCE.findall(text) if block.strip()]
    if not blocks:
        return text.strip() + "\n"

    for block in reversed(blocks):
        for reading in _candidates(block):
            if _defines_app(reading):
                return reading + "\n"

    return max((block.strip() for block in blocks), key=len) + "\n"


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
            max_tokens=MAX_TOKENS,
            temperature=request.temperature,
            messages=[{"role": "user", "content": request.prompt}],
        )
        text = "".join(block.text for block in response.content if block.type == "text")
        if not text.strip():
            raise EmptyCompletionError(f"{self.name} returned no content")
        return GenerationResult(
            text=text,
            model_id=response.model,
            finish_reason=response.stop_reason,
        )


class OpenAIAdapter:
    """Generates via an OpenAI-compatible Chat Completions API.

    Serves both api.openai.com (key: OPENAI_API_KEY) and, via ``base_url``,
    OpenAI-compatible gateways such as OpenRouter (key: OPENROUTER_API_KEY).

    Paces requests and retries transient failures. Both are load-bearing for
    the published numbers, not conveniences: OpenRouter's WAF rejects burst
    traffic, and an unretried empty completion gets written out as an empty
    `app.py` and scored as if the model had failed the task.
    """

    def __init__(
        self,
        model: str,
        provider: str = "openai",
        base_url: str | None = None,
        key_env: str = "OPENAI_API_KEY",
        min_interval: float = 0.0,
        max_retries: int = 4,
    ) -> None:
        self.model = model
        self.name = f"{provider}:{model}"
        self.base_url = base_url
        self.key_env = key_env
        self.min_interval = min_interval
        self.max_retries = max_retries
        self._last_request = 0.0

    def _throttle(self) -> None:
        """Hold `min_interval` seconds between requests to this provider."""
        if self.min_interval <= 0:
            return
        elapsed = time.monotonic() - self._last_request
        if elapsed < self.min_interval:
            time.sleep(self.min_interval - elapsed)

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

        last_error: Exception | None = None
        for attempt in range(self.max_retries + 1):
            self._throttle()
            try:
                response = client.chat.completions.create(
                    model=self.model,
                    max_tokens=MAX_TOKENS,
                    temperature=request.temperature,
                    messages=[{"role": "user", "content": request.prompt}],
                )
                choice = response.choices[0]
                text = choice.message.content or ""
                if not text.strip():
                    raise EmptyCompletionError(
                        f"{self.name} returned no content"
                        f" (finish_reason={choice.finish_reason})"
                    )
                return GenerationResult(
                    text=text,
                    model_id=response.model,
                    finish_reason=choice.finish_reason,
                )
            except Exception as exc:  # noqa: BLE001 - retried, then re-raised
                last_error = exc
                if attempt == self.max_retries:
                    break
                # Exponential backoff from the pacing interval, so a throttled
                # gateway is given progressively more room.
                time.sleep(max(self.min_interval, 1.0) * 2**attempt)
            finally:
                self._last_request = time.monotonic()

        raise RuntimeError(
            f"{self.name} failed after {self.max_retries + 1} attempt(s): {last_error}"
        ) from last_error


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


# OpenRouter's WAF 403s burst traffic, so its adapter paces by default. The
# published run's interval is recorded in results.json, because a timing
# threshold measured on a throttled machine is not the same measurement.
OPENROUTER_MIN_INTERVAL = 6.0


def build_adapter(spec: str, min_interval: float | None = None) -> Adapter:
    """Build an adapter from a --models spec: provider:argument."""
    provider, _, arg = spec.partition(":")
    if not arg:
        raise ValueError(f"--models spec needs provider:argument, got {spec!r}")
    if provider == "anthropic":
        return AnthropicAdapter(arg)
    if provider == "openai":
        return OpenAIAdapter(arg, min_interval=min_interval or 0.0)
    if provider == "openrouter":
        return OpenAIAdapter(
            arg,
            provider="openrouter",
            base_url="https://openrouter.ai/api/v1",
            key_env="OPENROUTER_API_KEY",
            min_interval=(
                OPENROUTER_MIN_INTERVAL if min_interval is None else min_interval
            ),
        )
    if provider == "local":
        return LocalAdapter(arg)
    raise ValueError(
        f"unknown provider {provider!r} in {spec!r};"
        " use anthropic:, openai:, openrouter:, local:"
    )
