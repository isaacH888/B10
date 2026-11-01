"""Flood controls before persistence, tested without Cognito or a live database."""

from concurrent.futures import ThreadPoolExecutor

from app.traffic import RequestBudget
from test_admin_native import native_app, URL
from test_auth import auth_app, ORIGIN


def test_missing_origin_flood_has_bounded_denial_audits_and_no_persistent_limits(native_app):
    client = native_app.test_client()
    results = [client.post(URL, json={}) for _ in range(80)]
    assert [result.status_code for result in results] == [403] * 60 + [429] * 20
    events = [event for event in native_app.test_store.events if event[0] == 'admin_native_login_denied']
    assert len(events) == 4
    assert not native_app.test_store.buckets
    assert not native_app.test_store.native
    assert results[-1].headers['Retry-After'] == '60'
    assert results[-1].json['error']['code'] == 'rate_limited'


def test_rotating_addresses_cannot_bypass_global_denial_audit_budget(native_app):
    client = native_app.test_client()
    for address in range(320):
        result = client.post(URL, json={}, environ_overrides={'REMOTE_ADDR': f'192.0.2.{address}'})
        assert result.status_code == (403 if address < 300 else 429)
    assert len(native_app.test_store.events) == 40
    assert not native_app.test_store.buckets


def test_callback_denials_share_bounded_audit_budget(native_app):
    client = native_app.test_client()
    for _ in range(40):
        assert client.get('/api/v1/customer/callback?error=denied').status_code == 303
    assert len(native_app.test_store.events) == 4
    assert all(event[0] == 'login_denied' for event in native_app.test_store.events)


def test_rejected_ingress_never_calls_store_or_service_and_preserves_flow_cookie(native_app, monkeypatch):
    client = native_app.test_client()
    native_app.extensions['auth_ingress'] = RequestBudget(per_address=1, total=1)
    assert client.post(URL, json={}).status_code == 403

    def forbidden(*args, **kwargs):
        raise AssertionError('Throttled traffic reached the authentication service or audit store')

    monkeypatch.setattr(native_app.extensions['auth_service'], 'native_transaction', forbidden)
    monkeypatch.setattr(native_app.test_store, 'audit', forbidden)
    for method in ('get', 'post', 'delete'):
        result = getattr(client, method)(URL, headers={'Origin': ORIGIN})
        assert result.status_code == 429
        assert 'Set-Cookie' not in result.headers


def test_admission_recovers_after_window_and_one_address_does_not_use_anothers_budget():
    clock = [0]
    budget = RequestBudget(per_address=2, total=4, seconds=60, clock=lambda: clock[0])
    assert budget.allow('one') and budget.allow('one')
    assert not budget.allow('one')
    assert budget.allow('two') and budget.allow('two')
    assert not budget.allow('three')
    clock[0] = 60
    assert budget.allow('one') and budget.allow('three')


def test_admission_capacity_is_bounded_and_cannot_be_bypassed_by_eviction():
    budget = RequestBudget(per_address=1, total=10000, max_addresses=8)
    results = [budget.allow(str(index)) for index in range(1000)]
    assert sum(results) == 8
    assert len(budget._counts) == 8
    assert all(len(key) == 32 for key in budget._counts)
    assert not budget.allow('0')


def test_concurrent_admission_cannot_exceed_the_budget():
    budget = RequestBudget(per_address=7, total=100)
    with ThreadPoolExecutor(max_workers=12) as threads:
        results = list(threads.map(budget.allow, ['same-address'] * 100))
    assert sum(results) == 7
