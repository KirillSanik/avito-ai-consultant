from app.tasks import deadline_reminder


def test_deadline_reminder_dry_run_does_not_call_network(monkeypatch) -> None:
    monkeypatch.setenv("TG_NOTIFY_URL", "http://tg-notify:8080/notify")
    monkeypatch.setenv("TG_NOTIFY_API_KEY", "test-key")

    result = deadline_reminder.run("Python", "Homework 1", "2026-09-07T12:00:00", "12345", True)

    assert result["status"] == "dry_run"


def test_deadline_reminder_uses_tg_notify_api_key(monkeypatch) -> None:
    monkeypatch.setenv("TG_NOTIFY_URL", "http://tg-notify:8080/notify")
    monkeypatch.setenv("TG_NOTIFY_API_KEY", "test-key")
    captured = {}

    class Response:
        def raise_for_status(self) -> None:
            return None

    def post(url, *, json, headers, timeout):
        captured.update(url=url, json=json, headers=headers, timeout=timeout)
        return Response()

    monkeypatch.setattr("app.tasks.httpx.post", post)
    result = deadline_reminder.run("Python", "Homework 1", "2026-09-07T12:00:00", "12345")

    assert result["status"] == "sent"
    assert captured["headers"] == {"X-API-Key": "test-key"}
    assert captured["json"]["chat_id"] == "12345"
