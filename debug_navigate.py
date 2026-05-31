"""
Minimal navigation test: focus Discord, open quick-switcher, navigate to
Canopy #general, read the last message. No orchestrator, no Notion.
Run from Windows PowerShell:
    python debug_navigate.py
"""
import asyncio
import json

from aria.app_discovery import discover_cdp_backends
from aria.conductor.local import LocalConductor
from aria.planner import OllamaPlanner


TASK = (
    "In Discord, navigate to the #general channel in the Canopy server "
    "and read the most recent message. Report the exact message text.\n\n"
    "Steps:\n"
    "1. Press Ctrl+K to open the quick-switcher search modal\n"
    "2. Type 'Canopy general' into the search input\n"
    "3. Click the #general result under the Canopy server\n"
    "4. Read and report the most recent message visible in the channel\n\n"
    "Success condition: the most recent message text from Canopy #general is known."
)


async def main() -> None:
    backends = discover_cdp_backends(
        ["discord"],
        on_status=lambda msg: print(f"[discovery] {msg}"),
    )
    print(f"Connected to: {', '.join(b.app for b in backends)}\n")

    conductor = LocalConductor(cdp_backends=backends)
    planner = OllamaPlanner(conductor=conductor)

    print("=== RUNNING TASK ===")
    print(TASK)
    print()

    result = await planner.run_task(TASK)

    print("\n=== RESULT ===")
    print(json.dumps(result, indent=2))

    msg = result.get("message", "")
    if msg:
        print(f"\n=== LAST MESSAGE ===\n{msg}")


if __name__ == "__main__":
    asyncio.run(main())
