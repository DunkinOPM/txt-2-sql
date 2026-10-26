import pytest
from app.core.config import settings
from app.core.rate_limiter import limiter


@pytest.fixture(autouse=True)
def reset_test_environment():
    """
    Autouse fixture to reset rate limiter and configure test defaults.
    Enables mock auth by default for legacy tests, while allowing individual auth tests
    to set enable_mock_auth=False to test production enforcement.
    """
    limiter.reset()
    original_mock_auth = settings.enable_mock_auth
    settings.enable_mock_auth = True
    yield
    settings.enable_mock_auth = original_mock_auth
    limiter.reset()
