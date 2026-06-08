from types import SimpleNamespace

from aria.harness.usage import (
    ModelUsage,
    extract_model_usage,
    summarize_usage,
    usage_to_trace_dict,
)


def test_extract_model_usage_from_dict_response():
    response = {
        "id": "chatcmpl-test",
        "usage": {
            "prompt_tokens": 12,
            "completion_tokens": 5,
            "total_tokens": 17,
        },
    }

    usage = extract_model_usage(
        response,
        provider="hackclub",
        model="bytedance/ui-tars-1.5-7b",
        role="actor",
    )

    assert usage == ModelUsage(
        provider="hackclub",
        model="bytedance/ui-tars-1.5-7b",
        role="actor",
        prompt_tokens=12,
        completion_tokens=5,
        total_tokens=17,
        estimated_cost_usd=None,
        usage_available=True,
        cost_estimated=False,
    )


def test_extract_model_usage_from_object_response():
    response = SimpleNamespace(
        usage=SimpleNamespace(
            prompt_tokens=20,
            completion_tokens=7,
            total_tokens=27,
        )
    )

    usage = extract_model_usage(
        response,
        provider="openai",
        model="gpt-test",
        role="verifier",
    )

    assert usage.provider == "openai"
    assert usage.model == "gpt-test"
    assert usage.role == "verifier"
    assert usage.prompt_tokens == 20
    assert usage.completion_tokens == 7
    assert usage.total_tokens == 27
    assert usage.usage_available is True
    assert usage.estimated_cost_usd is None
    assert usage.cost_estimated is False


def test_extract_model_usage_marks_usage_unavailable_when_absent():
    usage = extract_model_usage(
        {"id": "chatcmpl-test"},
        provider="groq",
        model="llama-test",
        role="planner",
    )

    assert usage.provider == "groq"
    assert usage.model == "llama-test"
    assert usage.role == "planner"
    assert usage.prompt_tokens is None
    assert usage.completion_tokens is None
    assert usage.total_tokens is None
    assert usage.usage_available is False
    assert usage.cost_estimated is False


def test_extract_model_usage_derives_total_tokens_when_missing():
    usage = extract_model_usage(
        {
            "usage": {
                "prompt_tokens": 8,
                "completion_tokens": 3,
            }
        },
        provider="hackclub",
        model="test-model",
        role="actor",
    )

    assert usage.prompt_tokens == 8
    assert usage.completion_tokens == 3
    assert usage.total_tokens == 11
    assert usage.usage_available is True


def test_summarize_usage_totals_roles_and_missing_calls():
    usages = [
        ModelUsage(
            provider="hackclub",
            model="planner-model",
            role="planner",
            prompt_tokens=10,
            completion_tokens=2,
            total_tokens=12,
            estimated_cost_usd=0.001,
            usage_available=True,
            cost_estimated=True,
        ),
        ModelUsage(
            provider="hackclub",
            model="actor-model",
            role="actor",
            prompt_tokens=20,
            completion_tokens=4,
            total_tokens=24,
            estimated_cost_usd=0.002,
            usage_available=True,
            cost_estimated=True,
        ),
        ModelUsage(
            provider="hackclub",
            model="verifier-model",
            role="verifier",
            usage_available=False,
        ),
    ]

    assert summarize_usage(usages) == {
        "total_prompt_tokens": 30,
        "total_completion_tokens": 6,
        "total_tokens": 36,
        "estimated_cost_usd": 0.003,
        "calls_by_role": {
            "planner": 1,
            "actor": 1,
            "verifier": 1,
        },
        "missing_usage_calls": 1,
        "usage_available": False,
    }


def test_summarize_usage_without_cost_estimates_leaves_cost_unknown():
    summary = summarize_usage(
        [
            ModelUsage(
                provider="hackclub",
                model="actor-model",
                role="actor",
                prompt_tokens=20,
                completion_tokens=4,
                total_tokens=24,
                usage_available=True,
            )
        ]
    )

    assert summary["estimated_cost_usd"] is None
    assert summary["usage_available"] is True


def test_usage_to_trace_dict_serializes_single_usage_and_list():
    usage = ModelUsage(
        provider="hackclub",
        model="actor-model",
        role="actor",
        prompt_tokens=20,
        completion_tokens=4,
        total_tokens=24,
        usage_available=True,
    )

    assert usage_to_trace_dict(usage) == {
        "provider": "hackclub",
        "model": "actor-model",
        "role": "actor",
        "prompt_tokens": 20,
        "completion_tokens": 4,
        "total_tokens": 24,
        "usage_available": True,
        "cost_estimated": False,
    }
    assert usage_to_trace_dict([usage]) == [usage_to_trace_dict(usage)]
