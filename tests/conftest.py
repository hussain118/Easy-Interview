import os
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent


def pytest_collection_modifyitems(config, items):
    if os.environ.get("RUN_LIVE_TESTS") == "1":
        return
    skip_live = pytest.mark.skip(reason="live test skipped (set RUN_LIVE_TESTS=1 to run)")
    for item in items:
        if "live" in item.keywords:
            item.add_marker(skip_live)


@pytest.fixture(scope="session")
def root_dir() -> Path:
    return ROOT
