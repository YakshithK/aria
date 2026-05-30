from aria.conductor.groq_client import GroqClient


class FakeCompletions:
    def __init__(self):
        self.kwargs = None

    def create(self, **kwargs):
        self.kwargs = kwargs
        return object()


class FakeChat:
    def __init__(self):
        self.completions = FakeCompletions()


class FakeOpenAIClient:
    def __init__(self):
        self.chat = FakeChat()


def test_groq_client_strips_ollama_extra_body():
    client = GroqClient(api_key="test-key")
    fake_client = FakeOpenAIClient()
    client._client = fake_client

    client.create_completion(messages=[], extra_body={"think": False})

    assert fake_client.chat.completions.kwargs == {
        "model": "meta-llama/llama-4-scout-17b-16e-instruct",
        "messages": [],
    }
