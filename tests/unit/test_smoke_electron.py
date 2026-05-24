from tests.smoke import smoke_electron


def test_element_names_retries_until_observe_succeeds(monkeypatch):
    calls = []

    class FakeElement:
        role = "button"
        name = "Friends"

    class FakeMap:
        elements = {"button": FakeElement()}

    class FakeBackend:
        def __init__(self, port, app):
            self.port = port
            self.app = app

        def observe(self):
            calls.append((self.port, self.app))
            if len(calls) == 1:
                raise RuntimeError("No matching active CDP page target found.")
            return FakeMap()

    monkeypatch.setattr(smoke_electron, "CDPBackend", FakeBackend)

    names = smoke_electron.element_names(
        "discord",
        attempts=2,
        interval=0,
        sleep=lambda _: None,
    )

    assert names == ["Friends"]
    assert calls == [(9224, "Discord"), (9224, "Discord")]


def test_run_smoke_restarts_app_before_launch(monkeypatch):
    calls = []

    monkeypatch.setattr(
        smoke_electron,
        "launch_app",
        lambda app_name, restart=False: calls.append(("launch", app_name, restart)),
    )
    monkeypatch.setattr(
        smoke_electron,
        "element_names",
        lambda app_name: ["Friends"],
    )
    monkeypatch.setattr(smoke_electron.time, "sleep", lambda _: None)

    result = smoke_electron.run_smoke(
        ["discord"],
        launch=True,
        restart=True,
        wait_seconds=0,
        contains=None,
        min_named_elements=1,
        scroll_check=False,
    )

    assert result == 0
    assert calls == [("launch", "discord", True)]


def test_scrolled_element_names_observes_after_each_scroll(monkeypatch):
    calls = []

    class FakeElement:
        def __init__(self, name):
            self.role = "button"
            self.name = name

    class FakeMap:
        def __init__(self, name):
            self.elements = {name: FakeElement(name)}

    class FakeBackend:
        def __init__(self, port, app):
            self.maps = [FakeMap("before"), FakeMap("after-down"), FakeMap("after-up")]

        def observe(self):
            calls.append(("observe",))
            return self.maps.pop(0)

        def scroll(self, delta_y):
            calls.append(("scroll", delta_y))

    monkeypatch.setattr(smoke_electron, "CDPBackend", FakeBackend)

    names = smoke_electron.scrolled_element_names(
        "discord",
        interval=0,
        sleep=lambda _: None,
    )

    assert names == ["after-down", "after-up", "before"]
    assert calls == [
        ("observe",),
        ("scroll", 800),
        ("observe",),
        ("scroll", -800),
        ("observe",),
    ]


def test_run_smoke_uses_scroll_check(monkeypatch):
    monkeypatch.setattr(
        smoke_electron,
        "scrolled_element_names",
        lambda app_name: ["message-1", "message-2"],
    )

    result = smoke_electron.run_smoke(
        ["discord"],
        launch=False,
        restart=False,
        wait_seconds=0,
        contains="message",
        min_named_elements=2,
        scroll_check=True,
    )

    assert result == 0
