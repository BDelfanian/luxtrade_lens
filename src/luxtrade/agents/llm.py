"""The only place that calls an LLM (GUIDELINES §1.1): structured calls validated by Pydantic.

Two providers behind one interface, chosen by ``LUXTRADE_LLM_PROVIDER`` (default ``openai``):
- ``OpenAILLM``: ``gpt-4.1-mini`` by default, strict JSON-schema structured outputs.
- ``AnthropicLLM``: ``claude-sonnet-4-6`` by default, structured outputs + adaptive thinking.
``LUXTRADE_LLM_MODEL`` overrides the model. ``FakeLLM`` returns scripted responses for tests.
"""

import logging
import os
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Protocol, TypeVar

from pydantic import BaseModel, ValidationError

from luxtrade.config import (
    LLM_DEFAULT_MODELS,
    LLM_DEFAULT_PROVIDER,
    LLM_KEY_VARS,
    LLM_TIMEOUT_S,
    ROOT_DIR,
)

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

    def __init__(
        self, model: str = LLM_DEFAULT_MODELS["anthropic"], timeout_s: float = LLM_TIMEOUT_S
    ) -> None:
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


def strict_schema(schema: type[BaseModel]) -> dict:
    """JSON schema in OpenAI strict form: every property required, no extras, no defaults."""

    def fix(node: object) -> object:
        if isinstance(node, dict):
            if "$ref" in node:
                return {"$ref": node["$ref"]}  # strict mode allows no siblings next to $ref
            node = {k: fix(v) for k, v in node.items() if k not in ("default", "title")}
            if "properties" in node:
                node["required"] = list(node["properties"])
                node["additionalProperties"] = False
            return node
        if isinstance(node, list):
            return [fix(v) for v in node]
        return node

    return fix(schema.model_json_schema())


class OpenAILLM:
    """OpenAI chat completions with strict structured outputs (``response_format``)."""

    def __init__(
        self, model: str = LLM_DEFAULT_MODELS["openai"], timeout_s: float = LLM_TIMEOUT_S
    ) -> None:
        import openai

        self._openai = openai
        self.client = openai.OpenAI(timeout=timeout_s, max_retries=2)
        self.model = model
        self.usage: list[LLMUsage] = []

    def parse(
        self, *, step: str, system: str, user: str, schema: type[T], effort: str = "low"
    ) -> T:
        """One structured call at temperature 0. ``effort`` is ignored (not a reasoning model)."""
        t0 = time.perf_counter()
        try:
            response = self.client.chat.completions.create(
                model=self.model,
                temperature=0,
                max_completion_tokens=6000,
                messages=[{"role": "system", "content": system}, {"role": "user", "content": user}],
                response_format={
                    "type": "json_schema",
                    "json_schema": {
                        "name": schema.__name__,
                        "schema": strict_schema(schema),
                        "strict": True,
                    },
                },
            )
        except self._openai.APIConnectionError as exc:
            raise LLMError(f"network error: {exc}") from exc
        except self._openai.RateLimitError as exc:
            body = exc.body if isinstance(exc.body, dict) else {}
            if body.get("type") == "insufficient_quota" or body.get("code") == "insufficient_quota":
                raise LLMError(
                    "the OpenAI account has no credit left: add credit at "
                    "platform.openai.com/settings/organization/billing"
                ) from exc
            raise LLMError("rate limited, try again shortly") from exc
        except self._openai.APIStatusError as exc:
            raise LLMError(f"API error {exc.status_code}: {exc.message}") from exc
        ms = int(1000 * (time.perf_counter() - t0))
        u = response.usage
        cached = getattr(getattr(u, "prompt_tokens_details", None), "cached_tokens", 0) or 0
        self.usage.append(
            LLMUsage(
                step=step,
                model=self.model,
                input_tokens=u.prompt_tokens,
                output_tokens=u.completion_tokens,
                cache_read_tokens=cached,
                ms=ms,
            )
        )
        logger.info(
            "llm %s: %d in / %d out tokens, %d ms", step, u.prompt_tokens, u.completion_tokens, ms
        )
        choice = response.choices[0]
        if choice.message.refusal:
            raise LLMError(f"the model declined this request: {choice.message.refusal}")
        if choice.finish_reason == "length":
            raise LLMError("the model's answer was cut off")
        try:
            return schema.model_validate_json(choice.message.content or "")
        except ValidationError as exc:
            raise LLMError(f"the model returned invalid structured output: {exc}") from exc


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


def load_env_file() -> None:
    """Apply non-empty `.env` values; they win over older values in the environment.

    ``.env`` is the project's explicit configuration, so a new key there must replace an old one
    set as a system variable. Empty entries (``OPENAI_API_KEY=``) never erase a variable.
    """
    from dotenv import dotenv_values, find_dotenv

    path = find_dotenv(usecwd=True) or str(ROOT_DIR / ".env")
    for key, value in dotenv_values(path).items():
        if value:
            os.environ[key] = value


def default_llm() -> StructuredLLM | None:
    """The configured LLM, or None when the provider's key is missing (offline mode)."""
    load_env_file()
    provider = os.environ.get("LUXTRADE_LLM_PROVIDER", LLM_DEFAULT_PROVIDER).strip().lower()
    if provider not in LLM_DEFAULT_MODELS:
        raise ValueError(f"LUXTRADE_LLM_PROVIDER must be one of {sorted(LLM_DEFAULT_MODELS)}")
    if not any(os.environ.get(var) for var in LLM_KEY_VARS[provider]):
        return None
    model = os.environ.get("LUXTRADE_LLM_MODEL") or LLM_DEFAULT_MODELS[provider]
    return OpenAILLM(model) if provider == "openai" else AnthropicLLM(model)


Factory = Callable[[], StructuredLLM | None]
