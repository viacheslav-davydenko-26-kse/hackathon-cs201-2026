import pytest
from fastapi.testclient import TestClient

from app.deps import get_repository


@pytest.fixture(scope="session")
def repo():
    return get_repository()


@pytest.fixture
def client():
    from app.main import app
    return TestClient(app)


def require_implemented(response):
    """Тест ендпоінту, реалізація якого ще не змерджена, стає xfail, а не red."""
    if response.status_code == 501:
        pytest.xfail(response.json()["error"]["message"])
    return response
