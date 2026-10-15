"""Readiness caching bounds SQL and fails closed while an expired probe runs."""

from concurrent.futures import ThreadPoolExecutor
from importlib import import_module
from threading import Event

from app.health import ReadinessCache
from test_auth import auth_app
from test_foundation import app


def test_readiness_flood_reuses_probe_facts_but_never_request_ids(auth_app, monkeypatch):
    calls = {'database': 0, 'schema': 0}

    def database():
        calls['database'] += 1
        return True

    def schema():
        calls['schema'] += 1
        return True

    monkeypatch.setattr(import_module('app.health'), 'database_available', database)
    monkeypatch.setattr(auth_app.test_store, 'ready', schema, raising=False)
    client = auth_app.test_client()
    responses = [client.get('/api/v1/health') for _ in range(80)]
    assert all(response.status_code == 200 for response in responses)
    assert calls == {'database': 1, 'schema': 1}
    assert len({response.json['meta']['request_id'] for response in responses}) == 80
    assert all(response.json['meta']['request_id'] == response.headers['X-Request-ID']
               and response.headers['Cache-Control'] == 'no-store' for response in responses)


def test_healthy_cache_expires_and_failed_probe_is_cached(app, monkeypatch):
    clock = [0]
    app.extensions['readiness_cache'] = ReadinessCache(clock=lambda: clock[0])
    calls = []

    def database():
        calls.append(clock[0])
        return len(calls) == 1

    monkeypatch.setattr(import_module('app.health'), 'database_available', database)
    client = app.test_client()
    assert client.get('/api/v1/health').status_code == 200
    clock[0] = 4.99
    assert client.get('/api/v1/health').status_code == 200
    clock[0] = 5
    assert client.get('/api/v1/health').status_code == 503
    assert client.get('/api/v1/health').status_code == 503
    assert calls == [0, 5]


def test_concurrent_readiness_never_queues_or_serves_expired_success(app, monkeypatch):
    clock = [0]
    app.extensions['readiness_cache'] = ReadinessCache(clock=lambda: clock[0])
    entered, release = Event(), Event()
    calls = []

    def database():
        calls.append(clock[0])
        if len(calls) > 1:
            entered.set()
            assert release.wait(timeout=5)
        return True

    monkeypatch.setattr(import_module('app.health'), 'database_available', database)
    assert app.test_client().get('/api/v1/health').status_code == 200
    clock[0] = 5
    with ThreadPoolExecutor(max_workers=1) as pool:
        pending = pool.submit(lambda: app.test_client().get('/api/v1/health'))
        assert entered.wait(timeout=5)
        try:
            responses = [app.test_client().get('/api/v1/health') for _ in range(40)]
            assert all(response.status_code == 503 for response in responses)
            assert calls == [0, 5]
            assert app.test_client().get('/api/v1/live').status_code == 200
        finally:
            release.set()
        assert pending.result(timeout=5).status_code == 200


def test_unexpected_probe_failure_does_not_leave_cache_locked():
    cache = ReadinessCache()

    def broken():
        raise RuntimeError('synthetic failure')

    import pytest
    with pytest.raises(RuntimeError):
        cache.read(broken)
    assert cache.read(lambda: (True, True)) == (True, True)
