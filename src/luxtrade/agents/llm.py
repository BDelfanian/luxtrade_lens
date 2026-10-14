"""The only place that calls an LLM (GUIDELINES §1.1): structured calls validated by Pydantic.

``AnthropicLLM`` uses Claude Sonnet 4.6 by default (``LUXTRADE_LLM_MODEL`` overrides it).
``FakeLLM`` returns scripted responses so tests never touch the network.
"""

import logging
import os
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Protocol, TypeVar

from pydantic import BaseModel

from luxtrade.config import LLM_MODEL, LLM_TIMEOUT_S

logger = logging.getLogger(__name__)
T = TypeVar("T", bound=BaseModel)


class LLMError(RuntimeError):
    """The LLM could not produce a valid answer (network, refusal, invalid output)."""


@dataclass
class LLMUsage:
    """Cost and latency of one call, recorded in the run record's trace."""

    step: str
    model: str
    input_tokens: int = 0
    output_tokens: int = 0
    cache_read_tokens: int = 0
    ms: int = 0


class StructuredLLM(Protocol):
    """A model that returns a validated Pydantic object."""

    model: str
    usage: list[LLMUsage]

    def parse(
        self, *, step: str, system: str, user: str, schema: type[T], effort: str = "low"
    ) -> T:
        """Return an instance of ``schema`` or raise ``LLMError``."""
        ...


class AnthropicLLM:
    """Claude via the official ``anthropic`` SDK with structured outputs."""

    def __init__(self, model: str = LLM_MODEL, timeout_s: float = LLM_TIMEOUT_S) -> None:
        import anthropic

        self._anthropic = anthropic
        self.client = anthropic.Anthropic(timeout=timeout_s, max_retries=2)
        self.model = model
        self.usage: list[LLMUsage] = []

    def parse(
        self, *, step: str, system: str, user: str, schema: type[T], effort: str = "low"
    ) -> T:
        """One structured call; the stable system prompt is cached."""
        t0 = time.perf_counter()
        try:
            response = self.client.messages.parse(
                model=self.model,
                max_tokens=8000,
                system=[{"type": "text", "text": system, "cache_control": {"type": "ephemeral"}}],
                messages=[{"role": "user", "content": user}],
                thinking={"type": "adaptive"},
                output_config={"effort": effort},
                output_format=schema,
            )
        except self._anthropic.APIConnectionError as exc:
            raise LLMError(f"network error: {exc}") from exc
        except self._anthropic.RateLimitError as exc:
            raise LLMError("rate limited, try again shortly") from exc
        except self._anthropic.APIStatusError as exc:
            raise LLMError(f"API error {exc.status_code}: {exc.message}") from exc
        ms = int(1000 * (time.perf_counter() - t0))
        u = response.usage
        self.usage.append(
            LLMUsage(
                step=step,
                model=self.model,
                input_tokens=u.input_tokens,
                output_tokens=u.output_tokens,
                cache_read_tokens=getattr(u, "cache_read_input_tokens", 0) or 0,
                ms=ms,
            )
        )
        logger.info(
            "llm %s: %d in / %d out tokens, %d ms", step, u.input_tokens, u.output_tokens, ms
        )
        if response.stop_reason == "refusal":
            raise LLMError("the model declined this request")
        if response.stop_reason == "max_tokens":
            raise LLMError("the model's answer was cut off")
        if response.parsed_output is None:
            raise LLMError("the model returned no valid structured output")
        return response.parsed_output


@dataclass
class FakeLLM:
    """Scripted LLM for tests.

    ``responses[step]`` is an object, a list (consumed in order), an exception or a callable.
    """

    responses: dict[str, object] = field(default_factory=dict)
    model: str = "fake"
    usage: list[LLMUsage] = field(default_factory=list)
    calls: list[tuple[str, str]] = field(default_factory=list)

    def parse(
        self, *, step: str, system: str, user: str, schema: type[T], effort: str = "low"
    ) -> T:
        """Return the scripted response for ``step``."""
        self.calls.append((step, user))
        self.usage.append(LLMUsage(step=step, model=self.model))
        if step not in self.responses:
            raise LLMError(f"no scripted response for {step}")
        resp = self.responses[step]
        if isinstance(resp, list):
            if not resp:
                raise LLMError(f"scripted responses for {step} exhausted")
            resp = resp.pop(0)
        if isinstance(resp, Exception):
            raise resp
        if callable(resp) and not isinstance(resp, BaseModel):
            resp = resp(user)
        return schema.model_validate(resp.model_dump() if isinstance(resp, BaseModel) else resp)


def default_llm() -> StructuredLLM | None:
    """The configured LLM, or None when no Anthropic credentials are available (offline mode)."""
    try:
        from dotenv import load_dotenv

        load_dotenv()
    except ImportError:  # pragma: no cover - python-dotenv is a dependency
        pass
    if not (os.environ.get("ANTHROPIC_API_KEY") or os.environ.get("ANTHROPIC_AUTH_TOKEN")):
        return None
    return AnthropicLLM()


Factory = Callable[[], StructuredLLM | None]
