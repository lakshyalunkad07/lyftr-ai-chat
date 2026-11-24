import os

os.environ["LLM_API_KEYS"] = "test-key-one,test-key-two"
os.environ["DATABASE_URL"] = "sqlite:///./lyftr-test.db"
os.environ["ENABLE_FAILURE_SIMULATION"] = "true"

from fastapi.testclient import TestClient
from app import main


def setup_function():
    main.init_db()
    with main.connect() as db:
        db.execute("DELETE FROM messages")
        db.execute("DELETE FROM sessions")


def test_health_contract():
    with TestClient(main.app) as client:
        response = client.get("/health")
    assert response.status_code == 200
    assert response.json() == {"status": "ok", "keys_configured": 2, "cache_enabled": True}


def test_validation_and_unknown_session():
    with TestClient(main.app) as client:
        assert client.post("/chat", json={"session_id": "a", "message": "  "}).status_code == 422
        response = client.get("/sessions/missing/messages")
    assert response.status_code == 404
    assert response.json() == {"detail": "session not found"}


def test_failover_simulation_and_all_failed(monkeypatch):
    class Usage:
        prompt_tokens = 10
        completion_tokens = 3
    class Message:
        content = "Hello from mocked model"
    class Choice:
        message = Message()
    class Response:
        usage = Usage()
        model = "gemini/gemini-3.8-flash"
        choices = [Choice()]
        _hidden_params = {}
    async def fake_completion(**kwargs):
        assert kwargs["caching"] is False
        return Response()
    monkeypatch.setattr(main.litellm, "acompletion", fake_completion)
    with TestClient(main.app) as client:
        response = client.post("/chat", json={"session_id": "fallback", "message": "hello"}, headers={"X-Simulate-Failure": "key_1=429"})
        assert response.status_code == 200
        assert response.json()["metadata"]["key_id"] == "key_2"
        assert response.json()["metadata"]["fallback_attempts"] == 1
        failed = client.post("/chat", json={"session_id": "no-write", "message": "hello"}, headers={"X-Simulate-Failure": "*=429"})
        assert failed.status_code == 503
        assert failed.json() == {"detail": "all providers unavailable"}
        history = client.get("/sessions/no-write/messages")
    assert history.status_code == 404


def test_cache_and_history(monkeypatch):
    cached_requests = set()
    class Usage:
        prompt_tokens = 12
        completion_tokens = 4
    class Message:
        content = "Paris"
    class Choice:
        message = Message()
    class Response:
        usage = Usage()
        model = "gemini/gemini-3.8-flash"
        choices = [Choice()]
        def __init__(self, cache_hit):
            self._hidden_params = {"cache_hit": cache_hit}
    async def fake_completion(**kwargs):
        key = str(kwargs["messages"])
        hit = kwargs["caching"] and key in cached_requests
        if kwargs["caching"]:
            cached_requests.add(key)
        return Response(hit)
    monkeypatch.setattr(main.litellm, "acompletion", fake_completion)
    with TestClient(main.app) as client:
        live = client.post("/chat", json={"session_id": "one", "message": "Capital of France?"}).json()
        hit = client.post("/chat", json={"session_id": "two", "message": "Capital of France?"}).json()
        assert live["reply"] == hit["reply"]
        assert hit["metadata"]["resolution_source"] == "LLM_CACHE"
        assert hit["metadata"]["key_id"] is None
        history = client.get("/sessions/one/messages").json()["messages"]
    assert len(history) == 2
    assert history[1]["metadata"]["input_tokens"] == 12


def test_multiturn_sends_prior_messages_to_model(monkeypatch):
    calls = []
    class Usage:
        prompt_tokens = 20
        completion_tokens = 2
    class Message:
        content = "I will remember that."
    class Choice:
        message = Message()
    class Response:
        usage = Usage()
        model = "gemini/gemini-3.8-flash"
        choices = [Choice()]
    async def fake_completion(**kwargs):
        calls.append(kwargs["messages"])
        return Response()
    monkeypatch.setattr(main.litellm, "acompletion", fake_completion)
    with TestClient(main.app) as client:
        client.post("/chat", json={"session_id": "turns", "message": "My name is Sam."})
        client.post("/chat", json={"session_id": "turns", "message": "What is my name?"})
    assert [message["role"] for message in calls[1]] == ["system", "user", "assistant", "user"]
    assert calls[1][-3]["content"] == "My name is Sam."


def test_trimmed_limits_and_simulation_disabled(monkeypatch):
    main.FAILURE_SIMULATION = False
    assert main._failure_map("key_1=429") == {}
    with TestClient(main.app) as client:
        assert client.post("/chat", json={"session_id": "ok", "message": " " + "x" * 4001 + " "}).status_code == 422
        assert client.post("/chat", json={"session_id": "x" * 129, "message": "hello"}).status_code == 422
