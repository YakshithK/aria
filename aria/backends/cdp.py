from __future__ import annotations

import asyncio
import json
import os
from datetime import UTC, datetime
from typing import Any, Protocol

import httpx
import websockets

from aria.models import Element, SemanticMap, Window


class CDPError(RuntimeError):
    pass


class PortConflictError(CDPError):
    pass


class CDPNotAvailableError(CDPError):
    pass


class CDPClient(Protocol):
    def list_targets(self) -> list[dict[str, Any]]:
        ...

    def get_full_ax_tree(self, target: dict[str, Any]) -> list[dict[str, Any]]:
        ...

    def get_dom_interactives(self, target: dict[str, Any]) -> list[dict[str, Any]]:
        ...

    def set_value(self, target: dict[str, Any], backend_node_id: int, text: str) -> Any:
        ...

    def set_value_dom(
        self,
        target: dict[str, Any],
        dom_target: dict[str, Any],
        text: str,
    ) -> Any:
        ...

    def invoke(self, target: dict[str, Any], backend_node_id: int) -> Any:
        ...

    def invoke_dom(self, target: dict[str, Any], dom_target: dict[str, Any]) -> Any:
        ...

    def scroll(
        self,
        target: dict[str, Any],
        x: int,
        y: int,
        delta_x: int,
        delta_y: int,
    ) -> Any:
        ...

    def key_combo(self, target: dict[str, Any], keys: list[str]) -> Any:
        ...

    def insert_text(self, target: dict[str, Any], text: str) -> Any:
        ...

    def insert_text_dom(
        self,
        target: dict[str, Any],
        dom_target: dict[str, Any],
        text: str,
    ) -> Any:
        ...

    def navigate(self, target: dict[str, Any], url: str) -> Any:
        ...


class PortRegistry:
    def __init__(self) -> None:
        self._ports: dict[int, str] = {}

    def register(self, app: str, port: int) -> None:
        owner = self._ports.get(port)
        if owner is not None and owner != app:
            raise PortConflictError(f"Port {port} already registered for {owner}")
        self._ports[port] = app


def _ax_value(raw: dict[str, Any], key: str, default: Any = "") -> Any:
    value = raw.get(key)
    if isinstance(value, dict):
        return value.get("value", default)
    if value is None:
        return default
    return value


def _property_value(node: dict[str, Any], name: str, default: Any = None) -> Any:
    for prop in node.get("properties") or []:
        if prop.get("name") == name:
            return _ax_value(prop, "value", default)
    return default


def _bounds(node: dict[str, Any]) -> tuple[int, int, int, int]:
    bounds = node.get("bounds") or {}
    return (
        int(bounds.get("x", 0)),
        int(bounds.get("y", 0)),
        int(bounds.get("width", 0)),
        int(bounds.get("height", 0)),
    )


def _actions_for_role(role: str) -> list[str]:
    actions = []
    if role in {"button", "link", "menuitem", "checkbox", "radio"}:
        actions.append("invoke")
    if role in {"textbox", "searchbox", "combobox"}:
        actions.append("set_value")
    return actions


def _element_id(target_id: str, node_id: int | str) -> str:
    return f"cdp:{target_id}:nodeId_{node_id}"


def parse_ax_tree(nodes: list[dict[str, Any]], target_id: str) -> dict[str, Element]:
    elements: dict[str, Element] = {}
    included_node_ids = {
        node.get("nodeId")
        for node in nodes
        if node.get("nodeId") is not None and not node.get("ignored")
    }
    for node in nodes:
        if node.get("ignored"):
            continue
        node_id = node.get("nodeId")
        if node_id is None:
            continue
        role = str(_ax_value(node, "role", ""))
        name = str(_ax_value(node, "name", ""))
        value = _ax_value(node, "value", None)
        actions = _actions_for_role(role)
        child_ids = [
            _element_id(target_id, child_id)
            for child_id in node.get("childIds") or []
            if child_id in included_node_ids
        ]
        elements[_element_id(target_id, node_id)] = Element(
            id=_element_id(target_id, node_id),
            role=role,
            name=name,
            value=str(value) if value is not None else None,
            bounds=_bounds(node),
            enabled=not bool(_property_value(node, "disabled", False)),
            focused=bool(_property_value(node, "focused", False)),
            actions=actions,
            children=child_ids,
        )
    return elements


def backend_dom_node_ids(
    nodes: list[dict[str, Any]],
    target_id: str,
) -> dict[str, int]:
    ids = {}
    for node in nodes:
        node_id = node.get("nodeId")
        backend_dom_node_id = node.get("backendDOMNodeId")
        if node_id is not None and backend_dom_node_id is not None and not node.get("ignored"):
            ids[_element_id(target_id, node_id)] = int(backend_dom_node_id)
    return ids


def filter_elements(
    elements: dict[str, Element],
    root_ids: list[str],
    *,
    max_depth: int = 8,
    max_count: int = 500,
) -> dict[str, Element]:
    filtered: dict[str, Element] = {}
    queue = [(root_id, 0) for root_id in root_ids if root_id in elements]
    seen: set[str] = set()

    while queue and len(filtered) < max_count:
        element_id, depth = queue.pop(0)
        if element_id in seen or depth > max_depth:
            continue
        seen.add(element_id)
        element = elements[element_id]
        if element.name or element.actions or element_id in root_ids:
            filtered[element_id] = element
        for child_id in element.children:
            queue.append((child_id, depth + 1))

    return filtered


_CHROME_TITLES = {"tab bar", "new tab", "devtools", "extensions"}


_BLANK_URL_PATTERNS = ("/blank?", "/blank#", "about:blank")

# Notion utility/chrome pages that are never the content page the agent should act on.
# quick-search is a full-SPA search overlay — if it's open alongside a real page,
# the real page should always be preferred.
_NOTION_UTILITY_URL_PATTERNS = ("/quick-search",)


def _is_placeholder_target(target: dict[str, Any]) -> bool:
    """Return True for startup/restore/blank page targets that have no real content."""
    url = str(target.get("url", ""))
    if any(pat in url for pat in _BLANK_URL_PATTERNS):
        return True
    if any(pat in url for pat in _NOTION_UTILITY_URL_PATTERNS):
        return True
    return False


def select_active_target(
    targets: list[dict[str, Any]],
    *,
    window_id: int | None,
    title: str | None,
) -> dict[str, Any] | None:
    pages = [target for target in targets if target.get("type") == "page"]
    if window_id is not None:
        for target in pages:
            if target.get("windowId") == window_id:
                return target
    if title:
        lower_title = title.lower()
        for target in pages:
            if lower_title in str(target.get("title", "")).lower():
                return target
    usable_pages = [target for target in pages if target.get("webSocketDebuggerUrl")]
    content_pages = [
        target for target in usable_pages
        if str(target.get("title", "")).strip().lower() not in _CHROME_TITLES
    ]
    candidate_pool = content_pages or usable_pages
    # Prefer non-placeholder targets; fall back to placeholders only if nothing else available
    real_pages = [t for t in candidate_pool if not _is_placeholder_target(t)]
    named_pages = [
        target for target in (real_pages or candidate_pool)
        if str(target.get("title", "")).strip()
    ]
    if named_pages:
        return named_pages[0]
    if real_pages:
        return real_pages[0]
    if usable_pages:
        return usable_pages[0]
    return None


def select_targets_ranked(
    targets: list[dict[str, Any]],
    *,
    title: str | None,
) -> list[dict[str, Any]]:
    """Return all candidate page targets ordered best-first (for fallback probing).

    Ordering priority:
      1. Real (non-placeholder) pages whose title matches the app name
      2. Other real pages
      3. Placeholder pages (blank/restore URLs) as a last resort
    """
    pages = [t for t in targets if t.get("type") == "page" and t.get("webSocketDebuggerUrl")]
    content_pages = [
        t for t in pages
        if str(t.get("title", "")).strip().lower() not in _CHROME_TITLES
    ]
    pool = content_pages or pages
    real = [t for t in pool if not _is_placeholder_target(t)]
    placeholder = [t for t in pool if _is_placeholder_target(t)]

    if title:
        lower = title.lower()
        real_match = [t for t in real if lower in str(t.get("title", "")).lower()]
        real_other = [t for t in real if lower not in str(t.get("title", "")).lower()]
        return [*real_match, *real_other, *placeholder]

    return [*real, *placeholder]


class HttpWebSocketCDPClient:
    def __init__(
        self,
        port: int,
        host: str = "127.0.0.1",
        response_timeout: float = 5.0,
    ) -> None:
        self.port = port
        self.host = host
        self.response_timeout = response_timeout

    def list_targets(self) -> list[dict[str, Any]]:
        url = f"http://{self.host}:{self.port}/json/list"
        try:
            response = httpx.get(url, timeout=5.0)
            response.raise_for_status()
        except httpx.HTTPError as exc:
            raise CDPNotAvailableError(
                f"CDP is not available at {url}. Launch the app with "
                f"--remote-debugging-port={self.port}."
            ) from exc
        return response.json()

    def get_full_ax_tree(self, target: dict[str, Any]) -> list[dict[str, Any]]:
        websocket_url = target.get("webSocketDebuggerUrl")
        if not websocket_url:
            raise CDPNotAvailableError("Selected CDP target has no WebSocket URL.")
        return asyncio.run(self._get_full_ax_tree(websocket_url))

    def get_dom_interactives(self, target: dict[str, Any]) -> list[dict[str, Any]]:
        websocket_url = target.get("webSocketDebuggerUrl")
        if not websocket_url:
            raise CDPNotAvailableError("Selected CDP target has no WebSocket URL.")
        return asyncio.run(self._get_dom_interactives(websocket_url))

    def set_value(self, target: dict[str, Any], backend_node_id: int, text: str) -> Any:
        websocket_url = target.get("webSocketDebuggerUrl")
        if not websocket_url:
            raise CDPNotAvailableError("Selected CDP target has no WebSocket URL.")
        return asyncio.run(self._set_value(websocket_url, backend_node_id, text))

    def set_value_dom(
        self,
        target: dict[str, Any],
        dom_target: dict[str, Any],
        text: str,
    ) -> Any:
        websocket_url = target.get("webSocketDebuggerUrl")
        if not websocket_url:
            raise CDPNotAvailableError("Selected CDP target has no WebSocket URL.")
        return asyncio.run(self._set_value_dom(websocket_url, dom_target, text))

    def invoke(self, target: dict[str, Any], backend_node_id: int) -> Any:
        websocket_url = target.get("webSocketDebuggerUrl")
        if not websocket_url:
            raise CDPNotAvailableError("Selected CDP target has no WebSocket URL.")
        return asyncio.run(self._invoke(websocket_url, backend_node_id))

    def invoke_dom(self, target: dict[str, Any], dom_target: dict[str, Any]) -> Any:
        websocket_url = target.get("webSocketDebuggerUrl")
        if not websocket_url:
            raise CDPNotAvailableError("Selected CDP target has no WebSocket URL.")
        return asyncio.run(self._invoke_dom(websocket_url, dom_target))

    def scroll(
        self,
        target: dict[str, Any],
        x: int,
        y: int,
        delta_x: int,
        delta_y: int,
    ) -> Any:
        websocket_url = target.get("webSocketDebuggerUrl")
        if not websocket_url:
            raise CDPNotAvailableError("Selected CDP target has no WebSocket URL.")
        return asyncio.run(self._scroll(websocket_url, x, y, delta_x, delta_y))

    def key_combo(self, target: dict[str, Any], keys: list[str]) -> Any:
        websocket_url = target.get("webSocketDebuggerUrl")
        if not websocket_url:
            raise CDPNotAvailableError("Selected CDP target has no WebSocket URL.")
        return asyncio.run(self._key_combo(websocket_url, keys))

    def insert_text(self, target: dict[str, Any], text: str) -> Any:
        websocket_url = target.get("webSocketDebuggerUrl")
        if not websocket_url:
            raise CDPNotAvailableError("Selected CDP target has no WebSocket URL.")
        return asyncio.run(self._insert_text(websocket_url, text))

    def insert_text_dom(
        self,
        target: dict[str, Any],
        dom_target: dict[str, Any],
        text: str,
    ) -> Any:
        websocket_url = target.get("webSocketDebuggerUrl")
        if not websocket_url:
            raise CDPNotAvailableError("Selected CDP target has no WebSocket URL.")
        return asyncio.run(self._insert_text_dom(websocket_url, dom_target, text))

    def navigate(self, target: dict[str, Any], url: str) -> Any:
        websocket_url = target.get("webSocketDebuggerUrl")
        if not websocket_url:
            raise CDPNotAvailableError("Selected CDP target has no WebSocket URL.")
        return asyncio.run(self._navigate(websocket_url, url))

    async def _get_full_ax_tree(self, websocket_url: str) -> list[dict[str, Any]]:
        async with websockets.connect(websocket_url, open_timeout=5, max_size=None) as websocket:
            await websocket.send(json.dumps({"id": 1, "method": "Accessibility.enable"}))
            await self._recv_response(websocket, 1)
            last_nodes: list[dict[str, Any]] = []
            for attempt in range(5):
                request_id = attempt + 2
                await websocket.send(
                    json.dumps(
                        {"id": request_id, "method": "Accessibility.getFullAXTree"}
                    )
                )
                raw = await self._recv_response(websocket, request_id)
                last_nodes = raw.get("result", {}).get("nodes", [])
                if _ax_tree_has_useful_nodes(last_nodes):
                    return last_nodes
                await asyncio.sleep(0.25)
            return last_nodes

    async def _get_dom_interactives(self, websocket_url: str) -> list[dict[str, Any]]:
        async with websockets.connect(websocket_url, open_timeout=5, max_size=None) as websocket:
            await websocket.send(
                json.dumps(
                    {
                        "id": 1,
                        "method": "Runtime.evaluate",
                        "params": {
                            "expression": _DOM_INTERACTIVE_SCRIPT,
                            "returnByValue": True,
                            "awaitPromise": True,
                            "allowUnsafeEvalBlockedByCSP": True,
                        },
                    }
                )
            )
            raw = await self._recv_response(websocket, 1)
            result_envelope = raw.get("result", {})
            if "exceptionDetails" in result_envelope or "error" in raw:
                return []
            items = result_envelope.get("result", {}).get("value", [])
            return items if isinstance(items, list) else []

    async def _set_value(
        self,
        websocket_url: str,
        backend_node_id: int,
        text: str,
    ) -> Any:
        async with websockets.connect(websocket_url, open_timeout=5, max_size=None) as websocket:
            await websocket.send(
                json.dumps(
                    {
                        "id": 1,
                        "method": "DOM.resolveNode",
                        "params": {"backendNodeId": backend_node_id},
                    }
                )
            )
            resolved = await self._recv_json(websocket)
            if "error" in resolved:
                raise CDPError(str(resolved["error"]))
            object_id = resolved["result"]["object"]["objectId"]
            await websocket.send(
                json.dumps(
                    {
                        "id": 2,
                        "method": "Runtime.callFunctionOn",
                        "params": {
                            "objectId": object_id,
                            "functionDeclaration": (
                                "function(value) {"
                                "this.focus();"
                                "if ('value' in this) { this.value = value; }"
                                "else { this.textContent = value; }"
                                "this.dispatchEvent(new Event('input', { bubbles: true }));"
                                "this.dispatchEvent(new Event('change', { bubbles: true }));"
                                "return true;"
                                "}"
                            ),
                            "arguments": [{"value": text}],
                            "awaitPromise": True,
                        },
                    }
                )
            )
            result = await self._recv_json(websocket)
            if "error" in result:
                raise CDPError(str(result["error"]))
            return {"ok": True}

    async def _set_value_dom(
        self,
        websocket_url: str,
        dom_target: dict[str, Any],
        text: str,
    ) -> Any:
        async with websockets.connect(websocket_url, open_timeout=5, max_size=None) as websocket:
            await websocket.send(
                json.dumps(
                    {
                        "id": 1,
                        "method": "Runtime.evaluate",
                        "params": {
                            "expression": _dom_target_script(
                                dom_target,
                                (
                                    "const setNativeValue = (node, value) => {"
                                    "const proto = node instanceof HTMLTextAreaElement ? "
                                    "HTMLTextAreaElement.prototype : HTMLInputElement.prototype;"
                                    "const descriptor = Object.getOwnPropertyDescriptor(proto, 'value');"
                                    "if (descriptor && descriptor.set) descriptor.set.call(node, value);"
                                    "else node.value = value;"
                                    "};"
                                    "if ('value' in el) {"
                                    "setNativeValue(el, payload.text);"
                                    "el.dispatchEvent(new InputEvent('beforeinput', { bubbles: true, inputType: 'insertText', data: payload.text }));"
                                    "el.dispatchEvent(new InputEvent('input', { bubbles: true, inputType: 'insertText', data: payload.text }));"
                                    "} else {"
                                    "el.textContent = payload.text;"
                                    "el.dispatchEvent(new InputEvent('input', { bubbles: true, inputType: 'insertText', data: payload.text }));"
                                    "}"
                                    "el.dispatchEvent(new Event('change', { bubbles: true }));"
                                ),
                                {"text": text},
                            ),
                            "returnByValue": True,
                            "awaitPromise": True,
                        },
                    }
                )
            )
            raw = await self._recv_response(websocket, 1)
            if raw.get("result", {}).get("result", {}).get("value") is not True:
                raise CDPError(f"DOM element not found: {dom_target}")
            return {"ok": True}

    async def _navigate(self, websocket_url: str, url: str) -> Any:
        async with websockets.connect(websocket_url, open_timeout=5, max_size=None) as websocket:
            await websocket.send(
                json.dumps(
                    {
                        "id": 1,
                        "method": "Page.navigate",
                        "params": {"url": url},
                    }
                )
            )
            result = await self._recv_json(websocket)
            if "error" in result:
                raise CDPError(str(result["error"]))
            return {"ok": True}

    async def _insert_text(self, websocket_url: str, text: str) -> Any:
        async with websockets.connect(websocket_url, open_timeout=5, max_size=None) as websocket:
            # Input.insertText silently discards text when nothing editable is focused.
            # Check first so the caller gets a real error instead of a false ok.
            await websocket.send(
                json.dumps(
                    {
                        "id": 1,
                        "method": "Runtime.evaluate",
                        "params": {
                            "expression": (
                                "(() => {"
                                "const a = document.activeElement;"
                                "return !!(a && a !== document.body && "
                                "a !== document.documentElement && "
                                "(a.isContentEditable || 'value' in a));"
                                "})()"
                            ),
                            "returnByValue": True,
                        },
                    }
                )
            )
            focus_check = await self._recv_response(websocket, 1)
            is_focused = focus_check.get("result", {}).get("result", {}).get("value", False)
            if not is_focused:
                return {
                    "ok": False,
                    "error": (
                        "No editable element is focused in this page. "
                        "Call invoke on a text block element first to place the cursor, "
                        "then call type."
                    ),
                }
            await websocket.send(
                json.dumps(
                    {
                        "id": 2,
                        "method": "Input.insertText",
                        "params": {"text": text},
                    }
                )
            )
            await self._recv_response(websocket, 2)
            return {"ok": True}

    async def _insert_text_dom(
        self,
        websocket_url: str,
        dom_target: dict[str, Any],
        text: str,
    ) -> Any:
        async with websockets.connect(websocket_url, open_timeout=5, max_size=None) as websocket:
            if "\n" in text:
                await websocket.send(
                    json.dumps(
                        {
                            "id": 1,
                            "method": "Runtime.evaluate",
                            "params": {
                                "expression": _dom_target_script(
                                    dom_target,
                                    (
                                        "if (!(el.isContentEditable || 'value' in el)) return false;"
                                        "if (el.isContentEditable) {"
                                        "const range = document.createRange();"
                                        "range.selectNodeContents(el);"
                                        "range.collapse(false);"
                                        "const selection = window.getSelection();"
                                        "selection.removeAllRanges();"
                                        "selection.addRange(range);"
                                        "} else if (typeof el.setSelectionRange === 'function') {"
                                        "const end = String(el.value || '').length;"
                                        "el.setSelectionRange(end, end);"
                                        "}"
                                        "const data = new DataTransfer();"
                                        "data.setData('text/plain', payload.text);"
                                        "const paste = new ClipboardEvent('paste', {"
                                        "bubbles: true,"
                                        "cancelable: true,"
                                        "clipboardData: data"
                                        "});"
                                        "const handled = !el.dispatchEvent(paste);"
                                        "if (!handled) {"
                                        "document.execCommand('insertText', false, payload.text);"
                                        "}"
                                    ),
                                    {"text": text},
                                ),
                                "returnByValue": True,
                                "awaitPromise": True,
                            },
                        }
                    )
                )
                pasted = await self._recv_response(websocket, 1)
                if pasted.get("result", {}).get("result", {}).get("value") is not True:
                    return {
                        "ok": False,
                        "error": f"DOM multiline paste failed: {dom_target}",
                    }
                return {"ok": True}

            await websocket.send(
                json.dumps(
                    {
                        "id": 1,
                        "method": "Runtime.evaluate",
                        "params": {
                            "expression": _dom_target_script(
                                dom_target,
                                (
                                    "if (!(el.isContentEditable || 'value' in el)) return false;"
                                    "if (el.isContentEditable) {"
                                    "const range = document.createRange();"
                                    "range.selectNodeContents(el);"
                                    "range.collapse(false);"
                                    "const selection = window.getSelection();"
                                    "selection.removeAllRanges();"
                                    "selection.addRange(range);"
                                    "} else if (typeof el.setSelectionRange === 'function') {"
                                    "const end = String(el.value || '').length;"
                                    "el.setSelectionRange(end, end);"
                                    "}"
                                ),
                            ),
                            "returnByValue": True,
                            "awaitPromise": True,
                        },
                    }
                )
            )
            focused = await self._recv_response(websocket, 1)
            if focused.get("result", {}).get("result", {}).get("value") is not True:
                return {
                    "ok": False,
                    "error": f"DOM element is not editable or could not be focused: {dom_target}",
                }
            await websocket.send(
                json.dumps(
                    {
                        "id": 2,
                        "method": "Input.insertText",
                        "params": {"text": text},
                    }
                )
            )
            await self._recv_response(websocket, 2)
            return {"ok": True}

    async def _invoke(self, websocket_url: str, backend_node_id: int) -> Any:
        async with websockets.connect(websocket_url, open_timeout=5, max_size=None) as websocket:
            object_id = await self._resolve_object_id(websocket, backend_node_id)
            await websocket.send(
                json.dumps(
                    {
                        "id": 2,
                        "method": "Runtime.callFunctionOn",
                        "params": {
                            "objectId": object_id,
                            "functionDeclaration": (
                                "function() { this.focus(); this.click(); return true; }"
                            ),
                            "awaitPromise": True,
                        },
                    }
                )
            )
            result = await self._recv_json(websocket)
            if "error" in result:
                raise CDPError(str(result["error"]))
            return {"ok": True}

    async def _invoke_dom(self, websocket_url: str, dom_target: dict[str, Any]) -> Any:
        async with websockets.connect(websocket_url, open_timeout=5, max_size=None) as websocket:
            await websocket.send(
                json.dumps(
                    {
                        "id": 1,
                        "method": "Runtime.evaluate",
                        "params": {
                            "expression": (
                                _dom_target_script(
                                    dom_target,
                                    "el.click();",
                                )
                            ),
                            "returnByValue": True,
                            "awaitPromise": True,
                        },
                    }
                )
            )
            raw = await self._recv_response(websocket, 1)
            if raw.get("result", {}).get("result", {}).get("value") is not True:
                raise CDPError(f"DOM element not found: {dom_target}")
            return {"ok": True}

    async def _scroll(
        self,
        websocket_url: str,
        x: int,
        y: int,
        delta_x: int,
        delta_y: int,
    ) -> Any:
        async with websockets.connect(websocket_url, open_timeout=5, max_size=None) as websocket:
            await websocket.send(
                json.dumps(
                    {
                        "id": 1,
                        "method": "Input.dispatchMouseEvent",
                        "params": {
                            "type": "mouseWheel",
                            "x": x,
                            "y": y,
                            "deltaX": delta_x,
                            "deltaY": delta_y,
                        },
                    }
                )
            )
            result = await self._recv_json(websocket)
            if "error" in result:
                raise CDPError(str(result["error"]))
            return {"ok": True}

    async def _key_combo(self, websocket_url: str, keys: list[str]) -> Any:
        normalized_keys = [_normalize_key(key) for key in keys]
        async with websockets.connect(websocket_url, open_timeout=5, max_size=None) as websocket:
            events = [(key, "keyDown") for key in normalized_keys] + [
                (key, "keyUp") for key in reversed(normalized_keys)
            ]
            modifiers = _modifiers_for_keys(normalized_keys)
            for index, (key, event_type) in enumerate(events, start=1):
                await websocket.send(
                    json.dumps(
                        {
                            "id": index,
                            "method": "Input.dispatchKeyEvent",
                            "params": {
                                "type": event_type,
                                "key": key,
                                "code": _code_for_key(key),
                                "windowsVirtualKeyCode": _virtual_key_code(key),
                                "nativeVirtualKeyCode": _virtual_key_code(key),
                                "modifiers": modifiers,
                            },
                        }
                    )
                )
                result = await self._recv_json(websocket)
                if "error" in result:
                    raise CDPError(str(result["error"]))
            return {"ok": True}

    async def _resolve_object_id(self, websocket: Any, backend_node_id: int) -> str:
        await websocket.send(
            json.dumps(
                {
                    "id": 1,
                    "method": "DOM.resolveNode",
                    "params": {"backendNodeId": backend_node_id},
                }
            )
        )
        resolved = await self._recv_json(websocket)
        if "error" in resolved:
            raise CDPError(str(resolved["error"]))
        return str(resolved["result"]["object"]["objectId"])

    async def _recv_response(self, websocket: Any, request_id: int) -> dict[str, Any]:
        while True:
            raw = await self._recv_json(websocket)
            if raw.get("id") != request_id:
                continue
            if "error" in raw:
                raise CDPError(str(raw["error"]))
            return raw

    async def _recv_json(self, websocket: Any) -> dict[str, Any]:
        try:
            message = await asyncio.wait_for(
                websocket.recv(),
                timeout=self.response_timeout,
            )
        except TimeoutError as exc:
            raise CDPError(
                f"Timed out waiting for CDP WebSocket response after "
                f"{self.response_timeout:.1f}s."
            ) from exc
        return json.loads(message)


class CDPBackend:
    def __init__(
        self,
        port: int,
        app: str,
        client: CDPClient | None = None,
    ) -> None:
        self.port = port
        self.app = app
        self.client = client or HttpWebSocketCDPClient(port)
        self._targets_by_id: dict[str, dict[str, Any]] = {}
        self._backend_node_ids: dict[str, int] = {}
        self._dom_targets: dict[str, dict[str, Any]] = {}
        self._active_target_id: str | None = None

    def _observe_target(self, target: dict[str, Any]) -> SemanticMap:
        raw_nodes = self.client.get_full_ax_tree(target)
        target_id = str(target["id"])
        self._active_target_id = target_id
        self._targets_by_id[target_id] = target
        self._backend_node_ids.update(backend_dom_node_ids(raw_nodes, target_id=target_id))
        elements = parse_ax_tree(raw_nodes, target_id=target_id)
        root_ids = _root_element_ids(elements)
        filtered = filter_elements(elements, root_ids=root_ids)
        should_merge_dom = _semantic_map_is_sparse(filtered, root_ids) or self.app.lower() in {
            "discord",
            "notion",
        }
        if should_merge_dom:
            dom_elements, dom_targets = dom_interactives_to_elements(
                self.client.get_dom_interactives(target),
                target_id=target_id,
            )
            if root_ids and dom_elements:
                root = elements[root_ids[0]]
                merged_children = list(dict.fromkeys([*root.children, *dom_elements]))
                elements[root_ids[0]] = root.model_copy(update={"children": merged_children})
                filtered = {
                    **filtered,
                    root_ids[0]: elements[root_ids[0]],
                    **dom_elements,
                }
                self._dom_targets.update(dom_targets)
        if __debug__ and os.environ.get("ARIA_DEBUG_STATE"):
            import sys
            print(f"\n[DEBUG {self.app}] url={target.get('url', '?')}", file=sys.stderr)
            print(f"[DEBUG {self.app}] {len(filtered)} elements:", file=sys.stderr)
            for eid, el in filtered.items():
                print(f"  {eid.split(':')[-1]:12s}  role={el.role:12s}  name={el.name[:60]!r}", file=sys.stderr)
        window_id_value = f"cdp:{self.app.lower()}:{target['id']}"
        return SemanticMap(
            timestamp=datetime.now(UTC),
            focused_window=window_id_value,
            windows=[
                Window(
                    id=window_id_value,
                    app=self.app,
                    title=str(target.get("title", "")),
                    backend="cdp",
                    focused=True,
                    minimized=False,
                    bounds=(0, 0, 0, 0),
                    root_elements=root_ids,
                )
            ],
            elements=filtered,
            clipboard=None,
        )

    def observe(
        self,
        *,
        window_id: int | None = None,
        title: str | None = None,
    ) -> SemanticMap:
        targets = self.client.list_targets()

        # Exact window_id match: only caller that knows the specific target.
        if window_id is not None:
            target = select_active_target(targets, window_id=window_id, title=None)
            if target is None:
                raise CDPError("No matching active CDP page target found.")
            return self._observe_target(target)

        # Always use ranked selection so placeholder targets are deprioritised.
        # title is used only for ordering, not for hard filtering.
        candidates = select_targets_ranked(targets, title=title)
        if not candidates:
            raise CDPError("No matching active CDP page target found.")


        last_map: SemanticMap | None = None
        for candidate in candidates:
            try:
                smap = self._observe_target(candidate)
                if smap.elements:
                    return smap
                last_map = smap
            except Exception:
                continue

        if last_map is not None:
            return last_map
        raise CDPError("No matching active CDP page target found.")

    def get_window_stub(self) -> Window | None:
        """Return minimal window metadata via HTTP only — no WebSocket, no DOM scraping."""
        try:
            targets = self.client.list_targets()
            ranked = select_targets_ranked(targets, title=self.app)
            target = ranked[0] if ranked else None
            if target is None:
                return None
            window_id_value = f"cdp:{self.app.lower()}:{target['id']}"
            return Window(
                id=window_id_value,
                app=self.app,
                title=str(target.get("title", "")),
                backend="cdp",
                focused=False,
                minimized=False,
                bounds=(0, 0, 0, 0),
                root_elements=[],
            )
        except Exception:
            return None

    def set_value(self, target_id: str, text: str) -> Any:
        target_key = _target_key_from_element_id(target_id)
        target = self._targets_by_id.get(target_key)
        backend_node_id = self._backend_node_ids.get(target_id)
        dom_target = self._dom_targets.get(target_id)
        if target is not None and dom_target is not None:
            _ensure_dom_action(target_id, dom_target, "set_value")
            return _with_target_metadata(
                self.client.set_value_dom(target, dom_target, text),
                dom_target,
            )
        if target is None or backend_node_id is None:
            raise CDPError(f"Element {target_id} is not cached; observe before acting.")
        return self.client.set_value(target, backend_node_id, text)

    def invoke(self, target_id: str) -> Any:
        target_key = _target_key_from_element_id(target_id)
        target = self._targets_by_id.get(target_key)
        backend_node_id = self._backend_node_ids.get(target_id)
        dom_target = self._dom_targets.get(target_id)
        if target is not None and dom_target is not None:
            _ensure_dom_action(target_id, dom_target, "invoke")
            return _with_target_metadata(
                self.client.invoke_dom(target, dom_target),
                dom_target,
            )
        if target is None or backend_node_id is None:
            raise CDPError(f"Element {target_id} is not cached; observe before acting.")
        return self.client.invoke(target, backend_node_id)

    def scroll(
        self,
        x: int = 0,
        y: int = 0,
        delta_x: int = 0,
        delta_y: int = 400,
    ) -> Any:
        target = self._active_target()
        return self.client.scroll(target, x, y, delta_x, delta_y)

    def key_combo(self, keys: list[str]) -> Any:
        target = self._active_target()
        return self.client.key_combo(target, keys)

    def insert_text(self, text: str, *, target_id: str | None = None) -> Any:
        if target_id is not None:
            target_key = _target_key_from_element_id(target_id)
            target = self._targets_by_id.get(target_key)
            dom_target = self._dom_targets.get(target_id)
            if target is not None and dom_target is not None:
                return _with_target_metadata(
                    self.client.insert_text_dom(target, dom_target, text),
                    dom_target,
                )
        target = self._active_target()
        return self.client.insert_text(target, text)

    def navigate(self, url: str) -> Any:
        target = self._active_target()
        return self.client.navigate(target, url)

    def _active_target(self) -> dict[str, Any]:
        if self._active_target_id is None:
            raise CDPError("No active target cached; observe before acting.")
        return self._targets_by_id[self._active_target_id]


def _root_element_ids(elements: dict[str, Element]) -> list[str]:
    child_ids = {child_id for element in elements.values() for child_id in element.children}
    roots = [element_id for element_id in elements if element_id not in child_ids]
    return roots[:1]


def dom_interactives_to_elements(
    items: list[dict[str, Any]],
    *,
    target_id: str,
) -> tuple[dict[str, Element], dict[str, dict[str, Any]]]:
    elements: dict[str, Element] = {}
    dom_targets: dict[str, dict[str, Any]] = {}
    for index, item in enumerate(items[:500]):
        selector = str(item.get("selector") or "")
        name = str(item.get("name") or "").strip()
        role = str(item.get("role") or "generic")
        if not selector or not name:
            continue
        element_id = f"cdp:{target_id}:dom_{index}"
        bounds = item.get("bounds") or [0, 0, 0, 0]
        actions = item.get("actions") or _actions_for_role(role)
        elements[element_id] = Element(
            id=element_id,
            role=role,
            name=name,
            value=item.get("value"),
            bounds=(int(bounds[0]), int(bounds[1]), int(bounds[2]), int(bounds[3])),
            enabled=bool(item.get("enabled", True)),
            focused=False,
            actions=list(actions),
            children=[],
        )
        dom_targets[element_id] = {
            "selector": selector,
            "role": role,
            "name": name,
            "value": item.get("value"),
            "actions": list(actions),
        }
    return elements, dom_targets


def _semantic_map_is_sparse(elements: dict[str, Element], root_ids: list[str]) -> bool:
    return len(elements) <= len(root_ids)



def _with_target_metadata(result: Any, dom_target: dict[str, Any]) -> Any:
    if not isinstance(result, dict):
        return result
    return {
        **result,
        "target": {
            "selector": dom_target.get("selector"),
            "role": dom_target.get("role"),
            "name": dom_target.get("name"),
            "value": dom_target.get("value"),
        },
    }


def _ensure_dom_action(target_id: str, dom_target: dict[str, Any], action: str) -> None:
    actions = dom_target.get("actions") or []
    if action not in actions:
        raise CDPError(
            f"Element {target_id} role={dom_target.get('role')} "
            f"name={dom_target.get('name')!r} does not support {action}; "
            f"available actions: {actions}"
        )


def _ax_tree_has_useful_nodes(nodes: list[dict[str, Any]]) -> bool:
    for node in nodes:
        if node.get("ignored"):
            continue
        role = str(_ax_value(node, "role", ""))
        if role != "RootWebArea":
            return True
        if node.get("childIds"):
            return True
    return False


_DOM_INTERACTIVE_SCRIPT = r"""
(() => {
  const cssEscape = window.CSS && CSS.escape ? CSS.escape : (value) => String(value).replace(/["\\#.:,[\]>+~*^$|= ]/g, "\\$&");
  function selectorFor(el) {
    if (el.id) return "#" + cssEscape(el.id);
    const parts = [];
    let node = el;
    while (node && node.nodeType === Node.ELEMENT_NODE && parts.length < 6) {
      let part = node.localName.toLowerCase();
      if (node.classList && node.classList.length) {
        part += "." + Array.from(node.classList).slice(0, 2).map(cssEscape).join(".");
      }
      const parent = node.parentElement;
      if (parent) {
        const sameTag = Array.from(parent.children).filter(child => child.localName === node.localName);
        if (sameTag.length > 1) part += `:nth-of-type(${sameTag.indexOf(node) + 1})`;
      }
      parts.unshift(part);
      node = parent;
    }
    return parts.join(" > ");
  }
  function roleFor(el) {
    const explicit = el.getAttribute("role");
    if (explicit) return explicit;
    if (el.getAttribute("contenteditable") === "true") return "textbox";
    const tag = el.localName.toLowerCase();
    if (tag === "a") return "link";
    if (tag === "button") return "button";
    if (tag === "input") {
      const type = (el.getAttribute("type") || "text").toLowerCase();
      if (type === "search") return "searchbox";
      if (["button", "submit", "reset"].includes(type)) return "button";
      return "textbox";
    }
    if (tag === "textarea") return "textbox";
    if (tag === "select") return "combobox";
    return "generic";
  }
  function nameFor(el) {
    const text = (el.getAttribute("aria-label") || el.innerText || el.value || el.textContent || el.title || "").trim().replace(/\s+/g, " ");
    if (!text && el.getAttribute("contenteditable") === "true") return "(text block)";
    return text;
  }
  function hiddenVisualAncestor(el) {
    let node = el;
    while (node && node.nodeType === Node.ELEMENT_NODE) {
      if (Array.from(node.classList || []).some(name => name.toLowerCase().includes("hiddenvisually"))) {
        return node;
      }
      node = node.parentElement;
    }
    return null;
  }
  function closestClickable(el) {
    return el.closest("button, a[href], [role='button'], [role='link'], input, textarea, select, [contenteditable='true']") || el;
  }
  const seen = new Set();
  function recordFor(labelEl, clickEl, role, actions) {
    const name = nameFor(labelEl) || nameFor(clickEl);
    const rect = clickEl.getBoundingClientRect();
    if (!name || rect.width <= 0 || rect.height <= 0 || clickEl.disabled) return null;
    const key = `${role}:${name}`;
    if (seen.has(key)) return null;
    seen.add(key);
    return {
      selector: selectorFor(clickEl),
      role,
      name,
      value: clickEl.href || clickEl.value || null,
      bounds: [Math.round(rect.x), Math.round(rect.y), Math.round(rect.width), Math.round(rect.height)],
      enabled: !clickEl.disabled,
      actions
    };
  }
  const interactiveRecords = Array.from(document.querySelectorAll("a[href], button, input, textarea, select, [role='button'], [role='link'], [contenteditable='true']"))
    .filter(el => {
      const rect = el.getBoundingClientRect();
      if (rect.width <= 0 || rect.height <= 0 || el.disabled || !nameFor(el)) return false;
      // Filter Notion search-popup result links (contain qid= query param) — these are
      // overlay links that interfere with page content and should never be acted on.
      if (el.tagName === 'A' && el.href && el.href.includes('qid=')) return false;
      return true;
    })
    .slice(0, 350)
    .map(el => {
      const hidden = hiddenVisualAncestor(el);
      const clickEl = hidden && hidden.parentElement ? closestClickable(hidden.parentElement) : el;
      const role = roleFor(clickEl);
      const actions = (role === "link" || role === "button") ? ["invoke"]
        : clickEl.getAttribute("contenteditable") === "true" ? ["invoke", "set_value"]
        : ["set_value"];
      return recordFor(el, clickEl, role, actions);
    })
    .filter(Boolean);
  const textRecords = Array.from(document.querySelectorAll("[id^='message-content-'], [role='article'], [role='listitem'], p, li, h1, h2, h3"))
    .map(el => recordFor(el, el, "text", []))
    .filter(Boolean)
    .filter(item => item.name.length <= 800)
    .slice(0, 150);
  return [...interactiveRecords, ...textRecords].slice(0, 500);
})()
"""


def _dom_target_script(
    dom_target: dict[str, Any],
    action_body: str,
    payload: dict[str, Any] | None = None,
) -> str:
    return (
        "(() => {"
        f"const target = {json.dumps(dom_target)};"
        f"const payload = {json.dumps(payload or {})};"
        "const nameFor = (el) => (el.getAttribute('aria-label') || el.innerText || el.value || el.textContent || el.title || '').trim().replace(/\\s+/g, ' ');"
        "const roleFor = (el) => {"
        "const explicit = el.getAttribute('role');"
        "if (explicit) return explicit;"
        "const tag = el.localName.toLowerCase();"
        "if (tag === 'a') return 'link';"
        "if (tag === 'button') return 'button';"
        "if (tag === 'input') {"
        "const type = (el.getAttribute('type') || 'text').toLowerCase();"
        "if (type === 'search') return 'searchbox';"
        "if (['button', 'submit', 'reset'].includes(type)) return 'button';"
        "return 'textbox';"
        "}"
        "if (tag === 'textarea') return 'textbox';"
        "if (tag === 'select') return 'combobox';"
        "return 'generic';"
        "};"
        "let el = target.selector ? document.querySelector(target.selector) : null;"
        "if (!el) {"
        "const candidates = Array.from(document.querySelectorAll('a[href], button, input, textarea, select, [role=\"button\"], [role=\"link\"]'));"
        "el = candidates.find((candidate) => roleFor(candidate) === target.role && nameFor(candidate) === target.name && (!target.value || candidate.href === target.value || candidate.value === target.value)) || null;"
        "}"
        "if (!el) return false;"
        "el.scrollIntoView({block: 'center', inline: 'center'});"
        "el.focus();"
        f"{action_body}"
        "return true;"
        "})()"
    )


def _target_key_from_element_id(element_id: str) -> str:
    parts = element_id.split(":")
    if len(parts) < 3 or parts[0] != "cdp":
        raise CDPError(f"Invalid CDP element id: {element_id}")
    return parts[1]


def _modifiers_for_keys(keys: list[str]) -> int:
    modifiers = 0
    normalized = {key.lower() for key in keys}
    if "alt" in normalized:
        modifiers |= 1
    if "control" in normalized or "ctrl" in normalized:
        modifiers |= 2
    if "meta" in normalized or "command" in normalized or "win" in normalized:
        modifiers |= 4
    if "shift" in normalized:
        modifiers |= 8
    return modifiers


def _code_for_key(key: str) -> str:
    if len(key) == 1 and key.isalpha():
        return f"Key{key.upper()}"
    if len(key) == 1 and key.isdigit():
        return f"Digit{key}"
    return key


def _normalize_key(key: str) -> str:
    aliases = {
        "ctrl": "Control",
        "control": "Control",
        "shift": "Shift",
        "alt": "Alt",
        "meta": "Meta",
        "command": "Meta",
        "cmd": "Meta",
        "win": "Meta",
        "enter": "Enter",
        "return": "Enter",
        "escape": "Escape",
        "esc": "Escape",
        "tab": "Tab",
        "backspace": "Backspace",
        "delete": "Delete",
        "arrowleft": "ArrowLeft",
        "left": "ArrowLeft",
        "arrowup": "ArrowUp",
        "up": "ArrowUp",
        "arrowright": "ArrowRight",
        "right": "ArrowRight",
        "arrowdown": "ArrowDown",
        "down": "ArrowDown",
    }
    return aliases.get(key.lower(), key)


def _virtual_key_code(key: str) -> int:
    aliases = {
        "Control": 17,
        "Ctrl": 17,
        "Shift": 16,
        "Alt": 18,
        "Meta": 91,
        "Enter": 13,
        "Escape": 27,
        "Esc": 27,
        "Tab": 9,
        "Backspace": 8,
        "Delete": 46,
        "ArrowLeft": 37,
        "ArrowUp": 38,
        "ArrowRight": 39,
        "ArrowDown": 40,
    }
    if key in aliases:
        return aliases[key]
    if len(key) == 1:
        return ord(key.upper())
    return 0
