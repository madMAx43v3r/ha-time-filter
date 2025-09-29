# Note: pytest-homeassistant-custom-component supplies the `hass` fixture.
# Install dev deps: pip install -U pytest pytest-asyncio pytest-homeassistant-custom-component

import os
import shutil
import sys
from pathlib import Path
import pytest

pytest_plugins = ["pytest_homeassistant_custom_component"]

# This fixture enables loading custom integrations in all tests.
# Remove to enable selective use of this fixture
@pytest.fixture(autouse=True)
def _auto_enable_custom_integrations(enable_custom_integrations) -> None:
    """Automatically enable loading custom integrations in all tests."""
    return

# Make the repo root importable before tests are collected
REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

DOMAIN = "time_filter"

@pytest.fixture(autouse=True)
def _inject_time_filter(hass, enable_custom_integrations):
    """
    Ensure the custom component exists under the test config dir so HA's loader finds it.
    Runs automatically for every test.
    """
    src = REPO_ROOT / "custom_components" / DOMAIN
    assert src.exists(), f"Custom component not found at {src}"

    dst = Path(hass.config.path(f"custom_components/{DOMAIN}"))
    dst.parent.mkdir(parents=True, exist_ok=True)
    if not dst.exists():
        try:
            os.symlink(src, dst)  # Unix fast path
        except Exception:
            shutil.copytree(src, dst)  # Fallback (e.g., Windows)

    yield
