from fastapi import FastAPI
from fastapi.testclient import TestClient
import pytest

from app.routers.planner_landing import router


def client():
    app = FastAPI()
    app.include_router(router)
    return TestClient(app)


def test_invitation_page_keeps_bearer_token_out_of_server_urls(monkeypatch):
    monkeypatch.setenv('WEB_APP_URL', 'https://trotter.example')
    response = client().get('/planner/open')
    assert response.status_code == 200
    assert response.headers['cache-control'] == 'no-store'
    assert response.headers['referrer-policy'] == 'no-referrer'
    assert "frame-ancestors 'none'" in response.headers['content-security-policy']
    assert "location.hash" in response.text
    assert "fetch('/planner/invites/resolve',{method:'POST'" in response.text
    assert "body:JSON.stringify({token})" in response.text
    assert "webOrigin+'/#planner-invitation='" in response.text
    assert "innerHTML" not in response.text


def test_each_landing_has_a_new_nonce_and_rejects_unsafe_web_destination(monkeypatch):
    monkeypatch.setenv('WEB_APP_URL', 'javascript:alert(1)')
    first, second = client().get('/planner/open'), client().get('/planner/open')
    assert 'const webOrigin="";' in first.text
    assert first.headers['content-security-policy'] != second.headers['content-security-policy']
    assert '__NONCE__' not in first.text


def test_credentials_and_markup_cannot_escape_configured_link(monkeypatch):
    monkeypatch.setenv('WEB_APP_URL', 'https://secret:password@example.com')
    assert 'const webOrigin="";' in client().get('/planner/open').text
    monkeypatch.setenv('WEB_APP_URL', 'https://example.com/</script>')
    assert 'const webOrigin="https://example.com/\\u003c/script>";' in client().get('/planner/open').text


@pytest.mark.parametrize('url', [
    'https://testflight.apple.com/join/AbCdEfGh',
    'https://apps.apple.com/us/app/trotter/id123456789',
    'https://apps.apple.com/app/id123456789',
])
def test_iphone_install_destination_is_a_real_apple_host(monkeypatch, url):
    monkeypatch.setenv('IOS_APP_DOWNLOAD_URL', url)
    assert f'const iosDownload="{url}";' in client().get('/planner/open').text


@pytest.mark.parametrize('url', [
    '', 'https://example.com/install', 'javascript:alert(1)',
    'https://testflight.apple.com.evil.test/join/AbCdEfGh',
    'https://user:pass@testflight.apple.com/join/AbCdEfGh',
    'https://testflight.apple.com:8443/join/AbCdEfGh',
    'https://testflight.apple.com:invalid/join/AbCdEfGh',
    'https://testflight.apple.com/join/AbCdEfGh?redirect=https://evil.test',
    'https://testflight.apple.com/join/AbCdEfGh#token=private',
    'https://apps.apple.com/</script>',
])
def test_missing_or_unsafe_iphone_install_url_never_produces_a_button(monkeypatch, url):
    monkeypatch.setenv('IOS_APP_DOWNLOAD_URL', url)
    response = client().get('/planner/open')
    assert response.status_code == 200
    assert 'const iosDownload="";' in response.text
