from __future__ import annotations

import asyncio
import json
from datetime import UTC, datetime
from typing import Any, Protocol

import httpx
import websockets

from cua.models import Element, SemanticMap, Window


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
    if len(pages) == 1 and window_id is None and title is None:
        return pages[0]
    return None


class HttpWebSocketCDPClient:
    def __init__(self, port: int, host: str = "127.0.0.1") -> None:
        self.port = port
        self.host = host

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

    def navigate(self, target: dict[str, Any], url: str) -> Any:
        websocket_url = target.get("webSocketDebuggerUrl")
        if not websocket_url:
            raise CDPNotAvailableError("Selected CDP target has no WebSocket URL.")
        return asyncio.run(self._navigate(websocket_url, url))

    async def _get_full_ax_tree(self, websocket_url: str) -> list[dict[str, Any]]:
        async with websockets.connect(websocket_url, open_timeout=5) as websocket:
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
        async with websockets.connect(websocket_url, open_timeout=5) as websocket:
            await websocket.send(
                json.dumps(
                    {
                        "id": 1,
                        "method": "Runtime.evaluate",
                        "params": {
                            "expression": _DOM_INTERACTIVE_SCRIPT,
                            "returnByValue": True,
                            "awaitPromise": True,
                        },
                    }
                )
            )
            raw = await self._recv_response(websocket, 1)
            return raw.get("result", {}).get("result", {}).get("value", [])

    async def _set_value(
        self,
        websocket_url: str,
        backend_node_id: int,
        text: str,
    ) -> Any:
        async with websockets.connect(websocket_url, open_timeout=5) as websocket:
            await websocket.send(
                json.dumps(
                    {
                        "id": 1,
                        "method": "DOM.resolveNode",
                        "params": {"backendNodeId": backend_node_id},
                    }
                )
            )
            resolved = json.loads(await websocket.recv())
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
            result = json.loads(await websocket.recv())
            if "error" in result:
                raise CDPError(str(result["error"]))
            return {"ok": True}

    async def _set_value_dom(
        self,
        websocket_url: str,
        dom_target: dict[str, Any],
        text: str,
    ) -> Any:
        async with websockets.connect(websocket_url, open_timeout=5) as websocket:
            await websocket.send(
                json.dumps(
                    {
                        "id": 1,
                        "method": "Runtime.evaluate",
                        "params": {
                            "expression": _dom_target_script(
                                dom_target,
                                (
                                    "if ('value' in el) { el.value = payload.text; } "
                                    "else { el.textContent = payload.text; } "
                                    "el.dispatchEvent(new Event('input', { bubbles: true }));"
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
        async with websockets.connect(websocket_url, open_timeout=5) as websocket:
            await websocket.send(
                json.dumps(
                    {
                        "id": 1,
                        "method": "Page.navigate",
                        "params": {"url": url},
                    }
                )
            )
            result = json.loads(await websocket.recv())
            if "error" in result:
                raise CDPError(str(result["error"]))
            return {"ok": True}

    async def _insert_text(self, websocket_url: str, text: str) -> Any:
        async with websockets.connect(websocket_url, open_timeout=5) as websocket:
            await websocket.send(
                json.dumps(
                    {
                        "id": 1,
                        "method": "Input.insertText",
                        "params": {"text": text},
                    }
                )
            )
            result = json.loads(await websocket.recv())
            if "error" in result:
                raise CDPError(str(result["error"]))
            return {"ok": True}

    async def _invoke(self, websocket_url: str, backend_node_id: int) -> Any:
        async with websockets.connect(websocket_url, open_timeout=5) as websocket:
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
            result = json.loads(await websocket.recv())
            if "error" in result:
                raise CDPError(str(result["error"]))
            return {"ok": True}

    async def _invoke_dom(self, websocket_url: str, dom_target: dict[str, Any]) -> Any:
        async with websockets.connect(websocket_url, open_timeout=5) as websocket:
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
        async with websockets.connect(websocket_url, open_timeout=5) as websocket:
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
            result = json.loads(await websocket.recv())
            if "error" in result:
                raise CDPError(str(result["error"]))
            return {"ok": True}

    async def _key_combo(self, websocket_url: str, keys: list[str]) -> Any:
        async with websockets.connect(websocket_url, open_timeout=5) as websocket:
            events = [(key, "keyDown") for key in keys] + [
                (key, "keyUp") for key in reversed(keys)
            ]
            modifiers = _modifiers_for_keys(keys)
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
                result = json.loads(await websocket.recv())
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
        resolved = json.loads(await websocket.recv())
        if "error" in resolved:
            raise CDPError(str(resolved["error"]))
        return str(resolved["result"]["object"]["objectId"])

    async def _recv_response(self, websocket: Any, request_id: int) -> dict[str, Any]:
        while True:
            raw = json.loads(await websocket.recv())
            if raw.get("id") != request_id:
                continue
            if "error" in raw:
                raise CDPError(str(raw["error"]))
            return raw


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

    def observe(
        self,
        *,
        window_id: int | None = None,
        title: str | None = None,
    ) -> SemanticMap:
        targets = self.client.list_targets()
        target = select_active_target(targets, window_id=window_id, title=title)
        if target is None:
            raise CDPError("No matching active CDP page target found.")

        raw_nodes = self.client.get_full_ax_tree(target)
        target_id = str(target["id"])
        self._active_target_id = target_id
        self._targets_by_id[target_id] = target
        self._backend_node_ids.update(backend_dom_node_ids(raw_nodes, target_id=target_id))
        elements = parse_ax_tree(raw_nodes, target_id=target_id)
        root_ids = _root_element_ids(elements)
        filtered = filter_elements(elements, root_ids=root_ids)
        if _semantic_map_is_sparse(filtered, root_ids):
            dom_elements, dom_targets = dom_interactives_to_elements(
                self.client.get_dom_interactives(target),
                target_id=target_id,
            )
            if root_ids and dom_elements:
                root = elements[root_ids[0]]
                elements[root_ids[0]] = root.model_copy(update={"children": list(dom_elements)})
                filtered = {
                    root_ids[0]: elements[root_ids[0]],
                    **dom_elements,
                }
                self._dom_targets.update(dom_targets)
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

    def set_value(self, target_id: str, text: str) -> Any:
        target_key = _target_key_from_element_id(target_id)
        target = self._targets_by_id.get(target_key)
        backend_node_id = self._backend_node_ids.get(target_id)
        dom_target = self._dom_targets.get(target_id)
        if target is not None and dom_target is not None:
            return self.client.set_value_dom(target, dom_target, text)
        if target is None or backend_node_id is None:
            raise CDPError(f"Element {target_id} is not cached; observe before acting.")
        return self.client.set_value(target, backend_node_id, text)

    def invoke(self, target_id: str) -> Any:
        target_key = _target_key_from_element_id(target_id)
        target = self._targets_by_id.get(target_key)
        backend_node_id = self._backend_node_ids.get(target_id)
        dom_target = self._dom_targets.get(target_id)
        if target is not None and dom_target is not None:
            return self.client.invoke_dom(target, dom_target)
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

    def insert_text(self, text: str) -> Any:
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
        }
    return elements, dom_targets


def _semantic_map_is_sparse(elements: dict[str, Element], root_ids: list[str]) -> bool:
    return len(elements) <= len(root_ids)


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
    return (el.getAttribute("aria-label") || el.innerText || el.value || el.textContent || el.title || "").trim().replace(/\s+/g, " ");
  }
  return Array.from(document.querySelectorAll("a[href], button, input, textarea, select, [role='button'], [role='link']"))
    .filter(el => {
      const rect = el.getBoundingClientRect();
      return rect.width > 0 && rect.height > 0 && !el.disabled && nameFor(el);
    })
    .slice(0, 500)
    .map(el => {
      const rect = el.getBoundingClientRect();
      const role = roleFor(el);
      return {
        selector: selectorFor(el),
        role,
        name: nameFor(el),
        value: el.href || el.value || null,
        bounds: [Math.round(rect.x), Math.round(rect.y), Math.round(rect.width), Math.round(rect.height)],
        enabled: !el.disabled,
        actions: role === "link" || role === "button" ? ["invoke"] : ["set_value"]
      };
    });
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
