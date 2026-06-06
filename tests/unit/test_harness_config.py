from pathlib import Path

from aria.harness.config import (
    DEFAULT_CONFIG_PATH,
    HarnessConfig,
    ModelConfig,
    SafetyConfig,
    TraceConfig,
    default_config_path,
    load_harness_config,
    save_harness_config,
)


def test_default_config_requires_approval_and_uses_hackclub_vision_model():
    config = HarnessConfig()

    assert config.actor.provider == "hackclub"
    assert config.actor.model == "bytedance/ui-tars-1.5-7b"
    assert config.actor.api_key_env == "HACKCLUB_API_KEY"
    assert config.verifier.provider == "hackclub"
    assert config.planner.provider == "hackclub"
    assert config.safety.approval_mode == "always"
    assert config.safety.allow_destructive_actions is False
    assert config.safety.max_turns_per_subtask == 3
    assert config.safety.max_subtasks == 8
    assert config.trace.output_dir == Path(".aria/runs")
    assert config.trace.keep_images is True


def test_config_loads_from_json_file(tmp_path):
    path = tmp_path / "config.json"
    path.write_text(
        "{"
        '"actor":{"provider":"openai","model":"gpt-4.1-mini","api_key_env":"OPENAI_API_KEY"},'
        '"verifier":{"provider":"openai","model":"gpt-4.1-mini","api_key_env":"OPENAI_API_KEY"},'
        '"planner":{"provider":"openai","model":"gpt-4.1-mini","api_key_env":"OPENAI_API_KEY"},'
        '"safety":{"approval_mode":"always","max_turns_per_subtask":3,"max_subtasks":8,'
        '"allow_destructive_actions":false},'
        '"trace":{"output_dir":".aria/runs","keep_images":true}'
        "}"
    )

    config = load_harness_config(path)

    assert config.actor.model == "gpt-4.1-mini"
    assert config.verifier.model == "gpt-4.1-mini"
    assert config.planner.model == "gpt-4.1-mini"
    assert config.safety.approval_mode == "always"
    assert config.trace.output_dir == Path(".aria/runs")


def test_config_save_creates_parent_directory_and_round_trips(tmp_path):
    path = tmp_path / ".aria" / "config.json"
    config = HarnessConfig(
        actor=ModelConfig(provider="openai", model="actor-model"),
        verifier=ModelConfig(provider="openai", model="verifier-model"),
        planner=ModelConfig(provider="openai", model="planner-model"),
        safety=SafetyConfig(max_turns_per_subtask=4),
        trace=TraceConfig(output_dir=Path(".aria/runs")),
    )

    save_harness_config(path, config)

    loaded = load_harness_config(path)
    assert loaded.actor.model == "actor-model"
    assert loaded.verifier.model == "verifier-model"
    assert loaded.planner.model == "planner-model"
    assert loaded.safety.max_turns_per_subtask == 4


def test_default_config_path_is_local_aria_config():
    assert DEFAULT_CONFIG_PATH == Path(".aria/config.json")
    assert default_config_path() == Path(".aria/config.json")
