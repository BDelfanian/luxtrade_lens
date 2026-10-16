import os

import httpx
import openai
import pytest

from luxtrade.agents import llm
from luxtrade.agents.scenario import AnswerVerdicts, FollowUps, ScenarioAnswer, ScenarioPlan
from luxtrade.agents.spec import CustomSQL, InsightOutput, Interpretation, OptimiserOutput


def _walk(node, path="$"):
    if isinstance(node, dict):
        assert "default" not in node, path
        if "$ref" in node:
            assert len(node) == 1, path
        if "properties" in node:
            assert set(node["required"]) == set(node["properties"]), path
            assert node["additionalProperties"] is False, path
        for key, value in node.items():
            _walk(value, f"{path}.{key}")
    elif isinstance(node, list):
        for i, value in enumerate(node):
            _walk(value, f"{path}[{i}]")


SCHEMAS = [
    Interpretation,
    OptimiserOutput,
    InsightOutput,
    CustomSQL,
    ScenarioPlan,
    FollowUps,
    ScenarioAnswer,
    AnswerVerdicts,
]


@pytest.mark.parametrize("schema", SCHEMAS)
def test_strict_schema_follows_openai_rules(schema):
    _walk(llm.strict_schema(schema))


def test_strict_schema_keeps_a_property_named_title():
    # "title" is also a JSON-schema keyword; only the keyword is dropped (seen on real data:
    # the scenario plan's title went missing and every plan failed validation)
    schema = llm.strict_schema(ScenarioPlan)
    assert "title" in schema["properties"] and "title" in schema["required"]
    assert "title" not in schema["properties"]["title"]


@pytest.fixture
def clean_env(monkeypatch):
    for var in (
        "LUXTRADE_LLM_PROVIDER",
        "LUXTRADE_LLM_MODEL",
        "OPENAI_API_KEY",
        "ANTHROPIC_API_KEY",
        "ANTHROPIC_AUTH_TOKEN",
    ):
        monkeypatch.delenv(var, raising=False)
    monkeypatch.setattr(llm, "load_env_file", lambda: None)
    return monkeypatch


def test_default_provider_is_openai_gpt_4_1_mini(clean_env):
    clean_env.setenv("OPENAI_API_KEY", "sk-test")
    model = llm.default_llm()
    assert isinstance(model, llm.OpenAILLM) and model.model == "gpt-4.1-mini"


def test_provider_and_model_can_be_switched(clean_env):
    clean_env.setenv("LUXTRADE_LLM_PROVIDER", "anthropic")
    clean_env.setenv("ANTHROPIC_API_KEY", "sk-ant-test")
    clean_env.setenv("LUXTRADE_LLM_MODEL", "claude-sonnet-4-6")
    model = llm.default_llm()
    assert isinstance(model, llm.AnthropicLLM) and model.model == "claude-sonnet-4-6"


def test_missing_key_means_offline(clean_env):
    assert llm.default_llm() is None
    clean_env.setenv("LUXTRADE_LLM_PROVIDER", "anthropic")
    clean_env.setenv("OPENAI_API_KEY", "sk-test")  # the other provider's key doesn't count
    assert llm.default_llm() is None


def test_unknown_provider_is_rejected(clean_env):
    clean_env.setenv("LUXTRADE_LLM_PROVIDER", "mystery")
    with pytest.raises(ValueError):
        llm.default_llm()


def _raising_client(exc):
    class Completions:
        def create(self, **kwargs):
            raise exc

    class Chat:
        completions = Completions()

    class Client:
        chat = Chat()

    return Client()


def test_out_of_credit_is_reported_clearly(clean_env):
    clean_env.setenv("OPENAI_API_KEY", "sk-test")
    model = llm.OpenAILLM()
    response = httpx.Response(429, request=httpx.Request("POST", "https://api.openai.com"))
    exc = openai.RateLimitError(
        "quota",
        response=response,
        body={"type": "insufficient_quota", "code": "credit_balance_exhausted"},
    )
    model.client = _raising_client(exc)
    with pytest.raises(llm.LLMError, match="no credit left"):
        model.parse(step="interpret", system="s", user="u", schema=InsightOutput)


def test_env_file_values_override_old_environment_values(tmp_path, monkeypatch):
    env = tmp_path / ".env"
    env.write_text("OPENAI_API_KEY=sk-new\nANTHROPIC_API_KEY=\n", encoding="utf-8")
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("OPENAI_API_KEY", "sk-old")
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant-keep")
    llm.load_env_file()

    assert os.environ["OPENAI_API_KEY"] == "sk-new"  # .env wins
    assert os.environ["ANTHROPIC_API_KEY"] == "sk-ant-keep"  # empty entry erases nothing
