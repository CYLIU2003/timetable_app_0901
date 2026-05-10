from __future__ import annotations

from datetime import timedelta

import timetable_app


def test_api_schedule_returns_current_time_and_routes(monkeypatch):
    monkeypatch.setattr(
        timetable_app,
        "ROUTES",
        [
            {
                "label": "テスト路線",
                "type": "train",
                "line_code": "TY",
                "max": 1,
                "walk": 7,
                "run": 5,
                "directions": [{"column": "大井町方面", "dest_tag": "Shibuya"}],
            }
        ],
        raising=False,
    )
    monkeypatch.setattr(
        timetable_app,
        "fetch_train_schedule",
        lambda line_code, dest_tag: [{"time": "12:34", "type": "各停", "dest": "大井町"}],
    )
    monkeypatch.setattr(timetable_app, "fetch_bus_schedule_csv", lambda *args, **kwargs: [])
    monkeypatch.setattr(timetable_app, "fetch_bus_schedule", lambda *args, **kwargs: [])
    monkeypatch.setattr(timetable_app, "remaining", lambda dep_time: timedelta(minutes=10))

    with timetable_app.app.test_client() as client:
        response = client.get("/api/schedule")

    assert response.status_code == 200
    payload = response.get_json()
    assert "current_time" in payload
    assert isinstance(payload["routes"], list)
    assert payload["routes"]
    assert payload["routes"][0]["label"] == "テスト路線"


def test_api_status_returns_expected_contract(monkeypatch):
    monkeypatch.setattr(
        timetable_app,
        "load_status_snapshot",
        lambda: {
            "updated_at": "2026-01-01T00:00:00",
            "source": "cache",
            "rows": [
                {"logo_path": "/static/img/test.png", "display_text": "テスト運行情報"},
                {"logo_path": None, "display_text": "平常運転"},
            ],
        },
    )

    with timetable_app.app.test_client() as client:
        response = client.get("/api/status?page=0&page_size=1")

    assert response.status_code == 200
    payload = response.get_json()
    assert "status" in payload
    assert "updated_at" in payload
    assert "source" in payload
    assert payload["updated_at"] == "2026-01-01T00:00:00"
    assert payload["source"] == "cache"
    assert len(payload["status"]) == 1


def test_api_status_all_returns_full_snapshot(monkeypatch):
    monkeypatch.setattr(
        timetable_app,
        "load_status_snapshot",
        lambda: {
            "updated_at": "2026-01-01T00:00:00",
            "source": "cache",
            "rows": [
                {"logo_path": "/static/img/test.png", "display_text": "テスト運行情報"},
                {"logo_path": None, "display_text": "平常運転"},
            ],
        },
    )

    with timetable_app.app.test_client() as client:
        response = client.get("/api/status?all=1")

    assert response.status_code == 200
    payload = response.get_json()
    assert len(payload["status"]) == 2
    assert payload["total_pages"] == 1


def test_api_weather_failure_does_not_return_500(monkeypatch):
    def raise_error(*args, **kwargs):
        raise RuntimeError("weather unavailable")

    from app_core import weather_service

    monkeypatch.setattr(weather_service.requests, "get", raise_error)

    with timetable_app.app.test_client() as client:
        response = client.get("/api/weather")

    assert response.status_code == 200
    assert response.get_json() == {}


def test_api_news_failure_does_not_return_500(monkeypatch):
    def raise_error(*args, **kwargs):
        raise RuntimeError("news unavailable")

    from app_core import news_service

    monkeypatch.setattr(news_service.feedparser, "parse", raise_error)

    with timetable_app.app.test_client() as client:
        response = client.get("/api/news")

    assert response.status_code == 200
    assert response.get_json() == {"news": []}


def test_weather_service_returns_stale_value_on_refresh_failure(monkeypatch):
    from app_core import weather_service

    payload = {"forecasts": [{"dateLabel": "今日", "telop": "晴れ"}]}
    call_count = {"value": 0}

    def fake_get(_url, timeout):
        call_count["value"] += 1

        class Response:
            def raise_for_status(self):
                return None

            def json(self):
                return payload

        if call_count["value"] == 1:
            return Response()
        raise RuntimeError("weather unavailable")

    monkeypatch.setattr(weather_service, "WEATHER_CACHE_TTL_SECONDS", 0)
    monkeypatch.setattr(weather_service.requests, "get", fake_get)

    assert weather_service.get_weather() == payload
    assert weather_service.get_weather() == payload


def test_news_service_returns_stale_value_on_refresh_failure(monkeypatch):
    from app_core import news_service

    call_count = {"value": 0}

    class FakeFeed:
        def __init__(self, title: str):
            self.entries = [{"title": title}]

    def fake_parse(_url):
        call_count["value"] += 1
        if call_count["value"] <= 2:
            return FakeFeed(f"title-{call_count['value']}")
        raise RuntimeError("news unavailable")

    monkeypatch.setattr(news_service, "NEWS_CACHE_TTL_SECONDS", 0)
    monkeypatch.setattr(news_service.feedparser, "parse", fake_parse)

    assert news_service.get_news() == {"news": ["title-1", "title-2"]}
    assert news_service.get_news() == {"news": ["title-1", "title-2"]}