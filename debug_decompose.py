import json

from aria.conductor.groq_client import GroqClient
from aria.planner import OllamaChatClient, OLLAMA_MODEL
from aria.conductor.orchestrator import DECOMPOSE_PROMPT, DECOMPOSE_SYSTEM, PLAN_TOOL, Subtask

try:
    client = GroqClient()
except KeyError:
    client = OllamaChatClient(model=OLLAMA_MODEL)
task = "Find the most recent message in #general in the Canopy server and write a one-line summary of it in a new Notion page called Discord Log"

print("=== CLIENT ===")
print(type(client).__name__, getattr(client, "model", OLLAMA_MODEL))
print()
print("=== SENDING TO MODEL ===")
print(DECOMPOSE_PROMPT.format(task=task))
print()

try:
    response = client.create_completion(
        model=getattr(client, "model", OLLAMA_MODEL),
        messages=[
            {"role": "system", "content": DECOMPOSE_SYSTEM},
            {"role": "user", "content": DECOMPOSE_PROMPT.format(task=task)},
        ],
        tools=[PLAN_TOOL],
        tool_choice={"type": "function", "function": {"name": "plan"}},
        timeout=120,
        extra_body={"think": False},
    )
    message = response.choices[0].message
    print("=== FULL MESSAGE ===")
    print("role:", message.role)
    print("content:", repr(message.content))
    print("tool_calls:", repr(message.tool_calls))
    print("finish_reason:", response.choices[0].finish_reason)
    print()
    print("=== PARSED SUBTASKS ===")
    tool_calls = message.tool_calls or []
    if not tool_calls:
        raise RuntimeError("Planning model did not call the plan tool.")
    call = tool_calls[0]
    data = json.loads(call.function.arguments)
    subtasks = [Subtask(**item) for item in data["subtasks"]]
    for s in subtasks:
        print(f"  Step {s.step}: {s.task}")
        print(f"  Done when: {s.success_condition}")
        print()
except Exception as e:
    print(f"=== EXCEPTION ===")
    print(type(e).__name__, e)
