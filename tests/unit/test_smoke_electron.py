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
