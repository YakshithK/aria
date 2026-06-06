from __future__ import annotations

import json
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, Field


ApprovalMode = Literal["always", "never", "on_risk"]
DEFAULT_CONFIG_PATH = Path(".aria/config.json")
DEFAULT_GROQ_VISION_MODEL = "meta-llama/llama-4-scout-17b-16e-instruct"
DEFAULT_HACKCLUB_VISION_MODEL = "bytedance/ui-tars-1.5-7b"


class ModelConfig(BaseModel):
    provider: str = "hackclub"
    model: str = DEFAULT_HACKCLUB_VISION_MODEL
    api_key_env: str = "HACKCLUB_API_KEY"


class SafetyConfig(BaseModel):
    approval_mode: ApprovalMode = "always"
    max_turns_per_subtask: int = Field(default=3, ge=1, le=10)
    max_subtasks: int = Field(default=8, ge=1, le=50)
    allow_destructive_actions: bool = False


class TraceConfig(BaseModel):
    output_dir: Path = Path(".aria/runs")
    keep_images: bool = True


class HarnessConfig(BaseModel):
    actor: ModelConfig = Field(default_factory=ModelConfig)
    verifier: ModelConfig = Field(default_factory=ModelConfig)
    planner: ModelConfig = Field(default_factory=ModelConfig)
    safety: SafetyConfig = Field(default_factory=SafetyConfig)
    trace: TraceConfig = Field(default_factory=TraceConfig)


def default_config_path() -> Path:
    return DEFAULT_CONFIG_PATH


def load_harness_config(path: Path = DEFAULT_CONFIG_PATH) -> HarnessConfig:
    return HarnessConfig.model_validate(json.loads(path.read_text()))


def save_harness_config(path: Path, config: HarnessConfig) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(config.model_dump(mode="json"), indent=2, ensure_ascii=True) + "\n"
    )
