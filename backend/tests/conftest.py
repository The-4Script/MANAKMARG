import pytest

from manakmarg.core import clock


@pytest.fixture(autouse=True)
def _unfrozen_clock():
    """Every test starts and ends with the real clock."""
    clock.freeze(None)
    yield
    clock.freeze(None)
