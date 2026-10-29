# tests/test_settings.py — 配置层:${VAR} 展开 + 模型查找(纯单元)
import pytest

from config.settings import ModelConfig, Settings, _expand_env


def test_expand_env_replaces_var(monkeypatch):
    monkeypatch.setenv("TEST_CFG_KEY", "hello")
    assert _expand_env("api_key: ${TEST_CFG_KEY}") == "api_key: hello"


def test_expand_env_missing_var_fails_fast():
    # 漏配要在启动时炸,不要等调 LLM 才 401
    with pytest.raises(RuntimeError, match="NOT_SET_ANYWHERE"):
        _expand_env("${NOT_SET_ANYWHERE}")


def _settings() -> Settings:
    return Settings(
        default="a",
        models=[
            ModelConfig(name="a", provider="openai", api_key="k", base_url="u", model="m"),
        ],
    )


def test_get_model_default():
    s = _settings()
    assert s.get_model().name == "a"
    assert s.get_model("a").model == "m"


def test_get_model_missing():
    with pytest.raises(ValueError, match="模型不存在"):
        _settings().get_model("nope")
