from fastapi import FastAPI
from fastapi.testclient import TestClient
import pytest

from app.routers.apple_links import router


def client():
    app = FastAPI()
    app.include_router(router)
    return TestClient(app)


def test_unconfigured_identity_does_not_publish_a_fake_association(monkeypatch):
    monkeypatch.delenv('APPLE_TEAM_ID', raising=False)
    monkeypatch.delenv('APPLE_APP_ID_PREFIX', raising=False)
    response = client().get('/.well-known/apple-app-site-association')
    assert response.status_code == 503
    assert response.headers['cache-control'] == 'no-store'
    assert response.json() == {'applinks': {'details': []}}


def test_association_is_json_with_one_exact_invitation_path_and_no_auth_paths(monkeypatch):
    monkeypatch.setenv('APPLE_TEAM_ID', 'ABCDEFGHIJ')
    monkeypatch.delenv('APPLE_APP_ID_PREFIX', raising=False)
    monkeypatch.setenv('APPLE_BUNDLE_ID', 'com.trotter.mobilev2')
    monkeypatch.setenv('BACKEND_URL', 'https://api.example.test')
    response = client().get('/.well-known/apple-app-site-association')
    assert response.status_code == 200
    assert response.headers['content-type'] == 'application/json'
    details = response.json()['applinks']['details']
    assert details[0]['appIDs'] == ['ABCDEFGHIJ.com.trotter.mobilev2']
    assert [component['/'] for component in details[0]['components']] == ['/planner/open']
    assert '?' not in details[0]['components'][0]


def test_legacy_app_id_prefix_and_api_base_path_are_supported(monkeypatch):
    monkeypatch.setenv('APPLE_APP_ID_PREFIX', 'PREFIX1234')
    monkeypatch.setenv('APPLE_TEAM_ID', 'TEAMID1234')
    monkeypatch.setenv('APPLE_BUNDLE_ID', 'com.trotter.mobilev2')
    monkeypatch.setenv('BACKEND_URL', 'https://api.example.test/v1')
    entry = client().get('/.well-known/apple-app-site-association').json()['applinks']['details'][0]
    assert entry['appIDs'] == ['PREFIX1234.com.trotter.mobilev2']
    assert entry['components'][0]['/'] == '/v1/planner/open'


@pytest.mark.parametrize('key,value', [
    ('APPLE_TEAM_ID', 'placeholder'), ('APPLE_BUNDLE_ID', 'com.trotter.*'),
    ('BACKEND_URL', 'https://api.example.test/*'), ('BACKEND_URL', 'https://api.example.test?token=private'),
    ('BACKEND_URL', 'https://[invalid'),
])
def test_bad_configuration_cannot_associate_broad_paths(monkeypatch, key, value):
    monkeypatch.setenv('APPLE_TEAM_ID', 'ABCDEFGHIJ')
    monkeypatch.delenv('APPLE_APP_ID_PREFIX', raising=False)
    monkeypatch.setenv('APPLE_BUNDLE_ID', 'com.trotter.mobilev2')
    monkeypatch.setenv('BACKEND_URL', 'https://api.example.test')
    monkeypatch.setenv(key, value)
    assert client().get('/.well-known/apple-app-site-association').status_code == 503
