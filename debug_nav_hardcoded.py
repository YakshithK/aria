"""
Hardcoded deterministic navigation to Canopy #general.
No LLM. Shows the semantic map at each step so we know what's there to click.
Run from Windows PowerShell: python debug_nav_hardcoded.py
"""
import asyncio
import json

from aria.app_discovery import discover_cdp_backends
from aria.conductor.local import LocalConductor
from aria.models import Action


def show_elements(state_json: str, label: str) -> dict:
    data = json.loads(state_json)
    elements = data.get("elements", {})
    url = data.get("url", "?")
    print(f"\n{'='*60}")
    print(f"[{label}] url={url}")
    print(f"[{label}] {len(elements)} elements:")
    for eid, el in elements.items():
        role = el.get("role", "")
        name = el.get("name", "")
        # Show interactive + any text with "canopy" or "general" in the name
        if role in ("button", "link", "combobox", "textbox", "listitem", "option") or \
           any(k.lower() in name.lower() for k in ["canopy", "general", "quick", "search", "switcher"]):
            print(f"  {eid:12s} role={role:12s} name={name!r}")
    return elements


async def main():
    backends = discover_cdp_backends(
        ["discord"],
        on_status=lambda m: print(f"[disc] {m}"),
    )
    conductor = LocalConductor(cdp_backends=backends)

    async def do(action_type: str, target_id: str | None = None, payload: dict | None = None):
        action = Action(type=action_type, target_id=target_id, payload=payload)
        result = await conductor.execute(action)
        print(f"  -> {action_type}({target_id}) = {result}")
        return result

    # --- STEP 0: observe initial state ---
    state = await conductor.get_current_state(scope="focused+registry")
    elements = show_elements(state, "INITIAL")

    # --- STEP 1: invoke the quick-switcher button (dom_8 = 'Find or start a conversation') ---
    print("\n[STEP 1] Invoking quick-switcher button (dom_8)...")
    qs_button = next(
        (eid for eid, el in elements.items() if el.get("name") == "Find or start a conversation"),
        None,
    )
    if qs_button:
        await do("invoke", qs_button)
    else:
        print("  WARNING: quick-switcher button not found, trying key_combo Ctrl+K")
        await do("key_combo", payload={"keys": ["ctrl", "k"]})

    await asyncio.sleep(1.0)
    state = await conductor.get_current_state(scope="focused+registry")
    elements = show_elements(state, "AFTER OPEN SWITCHER")

    # --- STEP 2: type into whatever is focused (quick switcher auto-focuses after open) ---
    print(f"\n[STEP 2] Typing 'Canopy general' into focused input...")
    await do("type", payload={"text": "Canopy general"})

    await asyncio.sleep(1.0)
    state = await conductor.get_current_state(scope="focused+registry")
    elements = show_elements(state, "AFTER TYPING 'Canopy general'")

    # --- STEP 3: keyboard-navigate to first result and select it ---
    # Quick-switcher results don't appear in the CDP accessibility tree.
    # Use Arrow Down to highlight the first result, then Enter to navigate.
    print(f"\n[STEP 3] Selecting first result via ArrowDown + Enter...")
    await asyncio.sleep(0.5)
    await do("key_combo", payload={"keys": ["ArrowDown"]})
    await asyncio.sleep(0.3)
    await do("key_combo", payload={"keys": ["Enter"]})
    await asyncio.sleep(1.5)

    state = await conductor.get_current_state(scope="focused+registry")
    elements = show_elements(state, "AFTER SELECTING RESULT")

    # --- STEP 4: read the last message ---
    data = json.loads(state)
    url = data.get("url", "")
    elements = data.get("elements", {})
    text_elements = [
        (eid, el.get("name", ""))
        for eid, el in elements.items()
        if el.get("role") == "text" and el.get("name")
    ]
    print(f"\n[STEP 4] Current URL: {url}")
    print(f"[STEP 4] Text elements ({len(text_elements)}):")
    for eid, name in text_elements[-10:]:
        print(f"  {eid}: {name!r}")


if __name__ == "__main__":
    asyncio.run(main())
