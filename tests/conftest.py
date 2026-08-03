"""Fixtures shared by the test suite."""
from __future__ import annotations

import pytest


@pytest.fixture(autouse=True)
def auto_enable_custom_integrations(enable_custom_integrations):
    """Without this, Home Assistant refuses to load a custom integration."""
    yield
