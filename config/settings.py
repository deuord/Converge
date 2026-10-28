# 配置层:读 models.yaml + .env + 环境变量覆写;类型安全,漏配启动报错
# yaml 里 key 写 ${VAR} 占位,真实值只放 .env(不进 git,见 plan §7.1)
import os
import re
from functools import lru_cache
from pathlib import Path

import yaml
from dotenv import load_dotenv
from pydantic import BaseModel
from pydantic_settings import BaseSettings, SettingsConfigDict

PROJECT_ROOT = Path(__file__).resolve().parent.parent
MODELS_YAML = PROJECT_ROOT / "config" / "models.yaml"


class ModelConfig(BaseModel):
    """单个模型的连接配置(yaml 里 models 列表的一项)"""

    name: str
    provider: str
    api_key: str
    base_url: str
    model: str


class Settings(BaseSettings):
    """全局配置:default 指向 models 里某一项的 name"""

    default: str
    models: list[ModelConfig]
    # env 里的值(如 AGENT_MAX_STEPS)可覆写字段;extra="ignore" 忽略无关环境变量
    model_config = SettingsConfigDict(extra="ignore")

    def get_model(self, name: str | None = None) -> ModelConfig:
        """按名字取模型;不传取默认。chat_stream 从这里拿 base_url/api_key"""
        target = name or self.default
        for m in self.models:
            if m.name == target:
                return m
        raise ValueError(f"模型不存在: {target}")


_VAR_PATTERN = re.compile(r"\$\{(\w+)\}")


def _expand_env(text: str) -> str:
    """把 yaml 文本里的 ${VAR} 替换成环境变量值。
    未设置的变量直接报错——漏配要在启动时炸,不要等调 LLM 才 401"""

    def repl(m: re.Match) -> str:
        var = m.group(1)
        val = os.environ.get(var)
        if val is None:
            raise RuntimeError(f"models.yaml 引用了未设置的环境变量 {var},请检查 .env")
        return val

    return _VAR_PATTERN.sub(repl, text)


@lru_cache
def get_settings() -> Settings:
    """全局配置单例:第一次调用时加载 .env + yaml,之后复用(lru_cache 缓存)"""
    # 先加载 .env 到环境变量,_expand_env 才能读到 key
    load_dotenv(PROJECT_ROOT / ".env")
    raw = _expand_env(MODELS_YAML.read_text(encoding="utf-8"))
    return Settings(**yaml.safe_load(raw))
