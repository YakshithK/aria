from __future__ import annotations

import asyncio
import json
import time
from collections.abc import Callable
from typing import Any

from cua.backends.cdp import CDPBackend
from cua.models import Action


class LocalConductor:
    def __init__(
        self,
        cdp_backend: CDPBackend | None = None,
        sleep: Callable[[float], None] = time.sleep,
    ) -> None:
        self.cdp_backend = cdp_backend or CDPBackend(port=9222, app="Chrome")
        self.sleep = sleep

    async def get_current_state(self, scope: str) -> str:
        if scope != "focused+registry":
            raise ValueError(f"Unsupported state scope: {scope}")
        semantic_map = await asyncio.to_thread(self.cdp_backend.observe)
        return semantic_map.model_dump_json()

    async def execute(self, action: Action) -> Any:
        try:
            return await self._execute(action)
        except Exception as exc:
            return {"ok": False, "error": str(exc)}

    async def _execute(self, action: Action) -> Any:
        if action.type == "observe_window":
            return await self.get_current_state(scope="focused+registry")
        if action.type == "focus_window":
            return {"ok": True, "action": "focus_window", "target_id": action.target_id}
        if action.type == "set_value":
            text = (action.payload or {}).get("text")
            if not isinstance(text, str):
                return {"ok": False, "error": "set_value requires payload.text"}
            return await asyncio.to_thread(
                self.cdp_backend.set_value,
                str(action.target_id),
                text,
            )
        if action.type == "type":
            text = (action.payload or {}).get("text")
            if not isinstance(text, str):
                return {"ok": False, "error": "type requires payload.text"}
            return await asyncio.to_thread(self.cdp_backend.insert_text, text)
        if action.type == "navigate":
            url = (action.payload or {}).get("url")
            if not isinstance(url, str):
                return {"ok": False, "error": "navigate requires payload.url"}
            return await asyncio.to_thread(self.cdp_backend.navigate, url)
        if action.type == "invoke":
            return await asyncio.to_thread(self.cdp_backend.invoke, str(action.target_id))
        if action.type == "scroll":
            payload = action.payload or {}
            return await asyncio.to_thread(
                self.cdp_backend.scroll,
                int(payload.get("x", 0)),
                int(payload.get("y", 0)),
                int(payload.get("delta_x", 0)),
                int(payload.get("delta_y", 400)),
            )
        if action.type == "key_combo":
            keys = (action.payload or {}).get("keys")
            if not isinstance(keys, list) or not all(isinstance(key, str) for key in keys):
                return {"ok": False, "error": "key_combo requires payload.keys"}
            return await asyncio.to_thread(self.cdp_backend.key_combo, keys)
        if action.type == "wait_for":
            return await asyncio.to_thread(self._wait_for, action)
        raise NotImplementedError(f"Action not implemented yet: {action.type}")

    def _wait_for(self, action: Action) -> dict[str, Any]:
        target_id = str(action.target_id)
        payload = action.payload or {}
        timeout = float(payload.get("timeout", 5.0))
        interval = float(payload.get("interval", 0.1))
        deadline = time.monotonic() + timeout
        while True:
            semantic_map = self.cdp_backend.observe()
            data = json.loads(semantic_map.model_dump_json())
            if target_id in data.get("elements", {}):
                return {"ok": True, "target_id": target_id}
            if time.monotonic() >= deadline:
                return {"ok": False, "error": "timeout", "target_id": target_id}
            self.sleep(interval)
