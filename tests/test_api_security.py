import os

import pytest
from fastapi.testclient import TestClient

from backend import api

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
ENV_PATH = os.path.join(ROOT, ".env")
INDEX = os.path.join(api.DIST, "index.html")

needs_dist = pytest.mark.skipif(not os.path.isfile(INDEX), reason="web/dist not built (run npm run build in web/)")


def _env_secrets() -> list[str]:
    """Non-empty values from .env, so a leak is detected without printing them."""
    if not os.path.isfile(ENV_PATH):
        return []
    values = []
    for line in open(ENV_PATH, encoding="utf-8"):
        if "=" in line and not line.lstrip().startswith("#"):
            value = line.split("=", 1)[1].strip()
            if len(value) >= 8:
                values.append(value)
    return values


@pytest.fixture(scope="module")
def client():
    # No context manager: the lifespan (stream engine) is not needed for static files.
    return TestClient(api.app)


@needs_dist
@pytest.mark.parametrize("url", ["/%2e%2e/.env", "/../.env", "/%2e%2e%2f.env", "/..%5c.env", "/assets/../../.env"])
def test_traversal_never_serves_env(client, url):
    r = client.get(url)
    body = r.text
    assert "GEMINI_API_KEY" not in body and "LLM_API_KEY" not in body
    for secret in _env_secrets():
        assert secret not in body
    if r.status_code == 200:
        assert body == open(INDEX, encoding="utf-8").read()


@needs_dist
@pytest.mark.parametrize("path", ["../.env", "..\\.env", "../../.env", "assets/../../.env", ENV_PATH, "/etc/passwd", "C:\\Windows\\win.ini"])
def test_resolve_static_stays_inside_dist(path):
    assert api.resolve_static(path) == INDEX


@needs_dist
def test_resolve_static_serves_real_dist_files():
    assert api.resolve_static("breaker.svg") == os.path.join(api.DIST, "breaker.svg")
    assert api.resolve_static("") == INDEX


def test_scan_rejects_oversized_content_length(client):
    r = client.post(api.SCAN_PATH, content=b"x", headers={"content-type": "multipart/form-data; boundary=x",
                                                             "content-length": str(api.MAX_SCAN_BODY + 1)})
    assert r.status_code == 413
