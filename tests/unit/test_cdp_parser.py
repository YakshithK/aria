import pytest

from cua.backends.cdp import (
    CDPBackend,
    CDPNotAvailableError,
    HttpWebSocketCDPClient,
    PortRegistry,
    PortConflictError,
    filter_elements,
    parse_ax_tree,
    select_active_target,
)


def ax_node(
    node_id,
    role,
    name="",
    *,
    value=None,
    ignored=False,
    child_ids=None,
    properties=None,
    bounds=None,
    backend_dom_node_id=None,
):
    node = {
        "nodeId": node_id,
        "role": {"value": role},
        "name": {"value": name},
        "value": {"value": value} if value is not None else None,
        "ignored": ignored,
        "childIds": child_ids or [],
        "properties": properties or [],
        "bounds": bounds or {"x": 1, "y": 2, "width": 30, "height": 40},
    }
    if backend_dom_node_id is not None:
        node["backendDOMNodeId"] = backend_dom_node_id
    return node


def test_parse_ax_tree_basic_nodes_to_elements():
    nodes = [
        ax_node(
            1,
            "RootWebArea",
            "Example",
            child_ids=[2],
            properties=[{"name": "focused", "value": {"value": True}}],
        ),
        ax_node(
            2,
            "button",
            "Submit",
            properties=[
                {"name": "disabled", "value": {"value": False}},
                {"name": "focused", "value": {"value": False}},
            ],
        ),
    ]

    elements = parse_ax_tree(nodes, target_id="page-1")

    assert elements["cdp:page-1:nodeId_1"].role == "RootWebArea"
    assert elements["cdp:page-1:nodeId_1"].name == "Example"
    assert elements["cdp:page-1:nodeId_1"].focused is True
    assert elements["cdp:page-1:nodeId_1"].children == ["cdp:page-1:nodeId_2"]
    assert elements["cdp:page-1:nodeId_2"].role == "button"
    assert elements["cdp:page-1:nodeId_2"].actions == ["invoke"]
    assert elements["cdp:page-1:nodeId_2"].enabled is True
    assert elements["cdp:page-1:nodeId_2"].bounds == (1, 2, 30, 40)


def test_parse_ax_tree_skips_ignored_nodes():
    elements = parse_ax_tree(
        [ax_node(1, "button", "Hidden", ignored=True)],
        target_id="page-1",
    )

    assert elements == {}


def test_parse_ax_tree_does_not_link_to_ignored_children():
    elements = parse_ax_tree(
        [
            ax_node(1, "RootWebArea", "Root", child_ids=[2]),
            ax_node(2, "generic", "Ignored", ignored=True),
        ],
        target_id="page-1",
    )

    assert elements["cdp:page-1:nodeId_1"].children == []
    assert filter_elements(elements, root_ids=["cdp:page-1:nodeId_1"])


def test_filter_elements_excludes_nodes_deeper_than_limit():
    nodes = [ax_node(1, "RootWebArea", "Root", child_ids=[2])]
    for node_id in range(2, 11):
        nodes.append(ax_node(node_id, "generic", f"Node {node_id}", child_ids=[node_id + 1]))
    nodes.append(ax_node(11, "button", "Too deep"))
    elements = parse_ax_tree(nodes, target_id="page-1")

    filtered = filter_elements(elements, root_ids=["cdp:page-1:nodeId_1"], max_depth=8)

    assert "cdp:page-1:nodeId_9" in filtered
    assert "cdp:page-1:nodeId_10" not in filtered
    assert "cdp:page-1:nodeId_11" not in filtered


def test_filter_elements_caps_result_count():
    nodes = [
        ax_node(1, "RootWebArea", "Root", child_ids=list(range(2, 20))),
        *[ax_node(node_id, "button", f"Button {node_id}") for node_id in range(2, 20)],
    ]
    elements = parse_ax_tree(nodes, target_id="page-1")

    filtered = filter_elements(elements, root_ids=["cdp:page-1:nodeId_1"], max_count=5)

    assert len(filtered) == 5


def test_filter_elements_skips_nameless_actionless_nodes():
    nodes = [
        ax_node(1, "RootWebArea", "Root", child_ids=[2, 3]),
        ax_node(2, "generic", ""),
        ax_node(3, "button", ""),
    ]
    elements = parse_ax_tree(nodes, target_id="page-1")

    filtered = filter_elements(elements, root_ids=["cdp:page-1:nodeId_1"])

    assert "cdp:page-1:nodeId_2" not in filtered
    assert "cdp:page-1:nodeId_3" in filtered


def test_active_tab_by_window_id():
    targets = [
        {"id": "a", "type": "page", "title": "Wrong", "windowId": 1},
        {"id": "b", "type": "page", "title": "Right", "windowId": 2},
    ]

    assert select_active_target(targets, window_id=2, title=None)["id"] == "b"


def test_active_tab_fallback_title():
    targets = [
        {"id": "a", "type": "page", "title": "Docs - Chrome"},
        {"id": "b", "type": "page", "title": "Mail - Chrome"},
    ]

    assert select_active_target(targets, window_id=None, title="mail")["id"] == "b"


def test_active_tab_no_match_returns_none():
    targets = [{"id": "a", "type": "page", "title": "Only tab", "windowId": 1}]

    assert select_active_target(targets, window_id=2, title="missing") is None


def test_active_target_without_hints_prefers_first_usable_page():
    targets = [
        {"id": "browser", "type": "browser", "title": "Browser"},
        {"id": "blank", "type": "page", "title": "", "webSocketDebuggerUrl": "ws://blank"},
        {
            "id": "notion",
            "type": "page",
            "title": "Notion",
            "webSocketDebuggerUrl": "ws://notion",
        },
    ]

    assert select_active_target(targets, window_id=None, title=None)["id"] == "notion"


def test_port_collision_guard():
    registry = PortRegistry()
    registry.register("chrome", 9222)

    with pytest.raises(PortConflictError):
        registry.register("edge", 9222)


def test_http_client_uses_ipv4_loopback_for_json_list(monkeypatch):
    requested = {}

    def fake_get(url, timeout):
        requested["url"] = url
        requested["timeout"] = timeout
        raise RuntimeError("stop")

    monkeypatch.setattr("cua.backends.cdp.httpx.get", fake_get)

    with pytest.raises(RuntimeError, match="stop"):
        HttpWebSocketCDPClient(9222).list_targets()

    assert requested == {
        "url": "http://127.0.0.1:9222/json/list",
        "timeout": 5.0,
    }


def test_http_client_error_mentions_debug_port(monkeypatch):
    def fake_get(url, timeout):
        raise __import__("httpx").ConnectError("no listener")

    monkeypatch.setattr("cua.backends.cdp.httpx.get", fake_get)

    with pytest.raises(CDPNotAvailableError, match="--remote-debugging-port=9222"):
        HttpWebSocketCDPClient(9222).list_targets()


def test_http_client_retries_until_ax_tree_has_useful_nodes(monkeypatch):
    sent = []

    class FakeWebSocket:
        def __init__(self):
            self.responses = [
                {"id": 1, "result": {}},
                {
                    "id": 2,
                    "result": {"nodes": [ax_node(1, "RootWebArea", "Google")]},
                },
                {
                    "id": 3,
                    "result": {
                        "nodes": [
                            ax_node(1, "RootWebArea", "Google", child_ids=[2]),
                            ax_node(2, "link", "OpenAI", backend_dom_node_id=42),
                        ]
                    },
                },
            ]

        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc, tb):
            return False

        async def send(self, payload):
            sent.append(__import__("json").loads(payload))

        async def recv(self):
            return __import__("json").dumps(self.responses.pop(0))

    async def fake_sleep(delay):
        return None

    monkeypatch.setattr(
        "cua.backends.cdp.websockets.connect",
        lambda websocket_url, open_timeout: FakeWebSocket(),
    )
    monkeypatch.setattr("cua.backends.cdp.asyncio.sleep", fake_sleep)

    nodes = HttpWebSocketCDPClient(9222).get_full_ax_tree(
        {"webSocketDebuggerUrl": "ws://example"}
    )

    assert [message["method"] for message in sent] == [
        "Accessibility.enable",
        "Accessibility.getFullAXTree",
        "Accessibility.getFullAXTree",
    ]
    assert nodes[1]["name"]["value"] == "OpenAI"


def test_backend_observe_builds_semantic_map_from_client():
    class FakeClient:
        def list_targets(self):
            return [
                {
                    "id": "page-1",
                    "type": "page",
                    "title": "Example",
                    "webSocketDebuggerUrl": "ws://example",
                }
            ]

        def get_full_ax_tree(self, target):
            return [
                ax_node(1, "RootWebArea", "Example", child_ids=[2]),
                ax_node(2, "button", "Submit"),
            ]

    semantic_map = CDPBackend(port=9222, app="Chrome", client=FakeClient()).observe()

    assert semantic_map.focused_window == "cdp:chrome:page-1"
    assert semantic_map.windows[0].backend == "cdp"
    assert semantic_map.windows[0].root_elements == ["cdp:page-1:nodeId_1"]
    assert "cdp:page-1:nodeId_2" in semantic_map.elements


def test_backend_observe_falls_back_to_dom_interactives_when_ax_tree_is_sparse():
    class FakeClient:
        def list_targets(self):
            return [
                {
                    "id": "page-1",
                    "type": "page",
                    "title": "openai - Google Search",
                    "webSocketDebuggerUrl": "ws://example",
                }
            ]

        def get_full_ax_tree(self, target):
            return [ax_node(1, "RootWebArea", "openai - Google Search")]

        def get_dom_interactives(self, target):
            return [
                {
                    "selector": "#result",
                    "role": "link",
                    "name": "OpenAI",
                    "value": "https://openai.com/",
                    "bounds": [10, 20, 300, 40],
                    "actions": ["invoke"],
                }
            ]

        def invoke_dom(self, target, dom_target):
            self.invoke_dom_call = (target["id"], dom_target)
            return {"ok": True}

    client = FakeClient()
    backend = CDPBackend(port=9222, app="Chrome", client=client)

    semantic_map = backend.observe()

    assert semantic_map.windows[0].root_elements == ["cdp:page-1:nodeId_1"]
    assert semantic_map.elements["cdp:page-1:nodeId_1"].children == ["cdp:page-1:dom_0"]
    assert semantic_map.elements["cdp:page-1:dom_0"].role == "link"
    assert semantic_map.elements["cdp:page-1:dom_0"].name == "OpenAI"
    assert backend.invoke("cdp:page-1:dom_0") == {"ok": True}
    assert client.invoke_dom_call == (
        "page-1",
        {
            "selector": "#result",
            "role": "link",
            "name": "OpenAI",
            "value": "https://openai.com/",
        },
    )


def test_backend_set_value_supports_dom_fallback_inputs():
    class FakeClient:
        def list_targets(self):
            return [
                {
                    "id": "page-1",
                    "type": "page",
                    "title": "Search",
                    "webSocketDebuggerUrl": "ws://example",
                }
            ]

        def get_full_ax_tree(self, target):
            return [ax_node(1, "RootWebArea", "Search")]

        def get_dom_interactives(self, target):
            return [
                {
                    "selector": "textarea[name='q']",
                    "role": "searchbox",
                    "name": "Search",
                    "value": "",
                    "bounds": [10, 20, 300, 40],
                    "actions": ["set_value"],
                }
            ]

        def set_value_dom(self, target, dom_target, text):
            self.set_value_dom_call = (target["id"], dom_target, text)
            return {"ok": True}

    client = FakeClient()
    backend = CDPBackend(port=9222, app="Chrome", client=client)
    backend.observe()

    assert backend.set_value("cdp:page-1:dom_0", "openai") == {"ok": True}
    assert client.set_value_dom_call == (
        "page-1",
        {
            "selector": "textarea[name='q']",
            "role": "searchbox",
            "name": "Search",
            "value": "",
        },
        "openai",
    )


def test_backend_observe_caches_backend_dom_ids_for_actions():
    class FakeClient:
        def list_targets(self):
            return [
                {
                    "id": "page-1",
                    "type": "page",
                    "title": "Example",
                    "webSocketDebuggerUrl": "ws://example",
                }
            ]

        def get_full_ax_tree(self, target):
            return [
                ax_node(1, "RootWebArea", "Example", child_ids=[2]),
                ax_node(2, "textbox", "Search", backend_dom_node_id=42),
            ]

        def set_value(self, target, backend_node_id, text):
            self.set_value_call = (target["id"], backend_node_id, text)
            return {"ok": True}

        def invoke(self, target, backend_node_id):
            self.invoke_call = (target["id"], backend_node_id)
            return {"ok": True}

    client = FakeClient()
    backend = CDPBackend(port=9222, app="Chrome", client=client)
    backend.observe()

    result = backend.set_value("cdp:page-1:nodeId_2", "hello")

    assert result == {"ok": True}
    assert client.set_value_call == ("page-1", 42, "hello")

    assert backend.invoke("cdp:page-1:nodeId_2") == {"ok": True}
    assert client.invoke_call == ("page-1", 42)


def test_backend_set_value_requires_prior_observe_cache():
    backend = CDPBackend(port=9222, app="Chrome", client=object())

    with pytest.raises(Exception, match="not cached"):
        backend.set_value("cdp:page-1:nodeId_2", "hello")


def test_http_client_set_value_sends_resolve_and_runtime_commands(monkeypatch):
    sent = []

    class FakeWebSocket:
        def __init__(self):
            self.responses = [
                {
                    "id": 1,
                    "result": {"object": {"objectId": "object-1"}},
                },
                {"id": 2, "result": {"result": {"value": True}}},
            ]

        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc, tb):
            return False

        async def send(self, payload):
            sent.append(__import__("json").loads(payload))

        async def recv(self):
            return __import__("json").dumps(self.responses.pop(0))

    monkeypatch.setattr(
        "cua.backends.cdp.websockets.connect",
        lambda websocket_url, open_timeout: FakeWebSocket(),
    )

    result = HttpWebSocketCDPClient(9222).set_value(
        {"webSocketDebuggerUrl": "ws://example"},
        backend_node_id=42,
        text="hello",
    )

    assert result == {"ok": True}
    assert sent[0] == {
        "id": 1,
        "method": "DOM.resolveNode",
        "params": {"backendNodeId": 42},
    }
    assert sent[1]["id"] == 2
    assert sent[1]["method"] == "Runtime.callFunctionOn"
    assert sent[1]["params"]["objectId"] == "object-1"
    assert sent[1]["params"]["arguments"] == [{"value": "hello"}]


def test_http_client_invoke_sends_click_function(monkeypatch):
    sent = []

    class FakeWebSocket:
        def __init__(self):
            self.responses = [
                {"id": 1, "result": {"object": {"objectId": "object-1"}}},
                {"id": 2, "result": {"result": {"value": True}}},
            ]

        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc, tb):
            return False

        async def send(self, payload):
            sent.append(__import__("json").loads(payload))

        async def recv(self):
            return __import__("json").dumps(self.responses.pop(0))

    monkeypatch.setattr(
        "cua.backends.cdp.websockets.connect",
        lambda websocket_url, open_timeout: FakeWebSocket(),
    )

    assert HttpWebSocketCDPClient(9222).invoke(
        {"webSocketDebuggerUrl": "ws://example"},
        backend_node_id=42,
    ) == {"ok": True}
    assert sent[0]["method"] == "DOM.resolveNode"
    assert sent[1]["method"] == "Runtime.callFunctionOn"
    assert ".click()" in sent[1]["params"]["functionDeclaration"]


def test_http_client_scroll_sends_mouse_wheel_event(monkeypatch):
    sent = []

    class FakeWebSocket:
        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc, tb):
            return False

        async def send(self, payload):
            sent.append(__import__("json").loads(payload))

        async def recv(self):
            return __import__("json").dumps({"id": 1, "result": {}})

    monkeypatch.setattr(
        "cua.backends.cdp.websockets.connect",
        lambda websocket_url, open_timeout: FakeWebSocket(),
    )

    assert HttpWebSocketCDPClient(9222).scroll(
        {"webSocketDebuggerUrl": "ws://example"},
        x=10,
        y=20,
        delta_x=0,
        delta_y=400,
    ) == {"ok": True}
    assert sent == [
        {
            "id": 1,
            "method": "Input.dispatchMouseEvent",
            "params": {
                "type": "mouseWheel",
                "x": 10,
                "y": 20,
                "deltaX": 0,
                "deltaY": 400,
            },
        }
    ]


def test_http_client_key_combo_sends_key_events(monkeypatch):
    sent = []

    class FakeWebSocket:
        def __init__(self):
            self.responses = [
                {"id": 1, "result": {}},
                {"id": 2, "result": {}},
                {"id": 3, "result": {}},
                {"id": 4, "result": {}},
            ]

        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc, tb):
            return False

        async def send(self, payload):
            sent.append(__import__("json").loads(payload))

        async def recv(self):
            return __import__("json").dumps(self.responses.pop(0))

    monkeypatch.setattr(
        "cua.backends.cdp.websockets.connect",
        lambda websocket_url, open_timeout: FakeWebSocket(),
    )

    assert HttpWebSocketCDPClient(9222).key_combo(
        {"webSocketDebuggerUrl": "ws://example"},
        ["Control", "L"],
    ) == {"ok": True}
    assert [event["params"]["type"] for event in sent] == [
        "keyDown",
        "keyDown",
        "keyUp",
        "keyUp",
    ]
    assert sent[0]["params"]["modifiers"] == 2
    assert sent[1]["params"]["key"] == "L"


def test_http_client_insert_text_sends_input_insert_text(monkeypatch):
    sent = []

    class FakeWebSocket:
        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc, tb):
            return False

        async def send(self, payload):
            sent.append(__import__("json").loads(payload))

        async def recv(self):
            return __import__("json").dumps({"id": 1, "result": {}})

    monkeypatch.setattr(
        "cua.backends.cdp.websockets.connect",
        lambda websocket_url, open_timeout: FakeWebSocket(),
    )

    assert HttpWebSocketCDPClient(9222).insert_text(
        {"webSocketDebuggerUrl": "ws://example"},
        "hello",
    ) == {"ok": True}
    assert sent == [
        {
            "id": 1,
            "method": "Input.insertText",
            "params": {"text": "hello"},
        }
    ]


def test_http_client_navigate_sends_page_navigate(monkeypatch):
    sent = []

    class FakeWebSocket:
        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc, tb):
            return False

        async def send(self, payload):
            sent.append(__import__("json").loads(payload))

        async def recv(self):
            return __import__("json").dumps({"id": 1, "result": {"frameId": "frame-1"}})

    monkeypatch.setattr(
        "cua.backends.cdp.websockets.connect",
        lambda websocket_url, open_timeout: FakeWebSocket(),
    )

    assert HttpWebSocketCDPClient(9222).navigate(
        {"webSocketDebuggerUrl": "ws://example"},
        "https://www.google.com/search?q=openai",
    ) == {"ok": True}
    assert sent == [
        {
            "id": 1,
            "method": "Page.navigate",
            "params": {"url": "https://www.google.com/search?q=openai"},
        }
    ]
