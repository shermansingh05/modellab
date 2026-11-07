import os
import tempfile

import pytest

_tmp = tempfile.mkdtemp(prefix="modellab-test-")
os.environ["DATABASE_URL"] = f"sqlite:///{_tmp}/test.db"
os.environ["MODELLAB_ADMIN_TOKEN"] = "test-token"
os.environ.pop("REDIS_URL", None)
AUTH = {"Authorization": "Bearer test-token"}


@pytest.fixture
def factory():
    from modellab_api.db import get_factory

    return get_factory()


@pytest.fixture
def client():
    from fastapi.testclient import TestClient

    from modellab_api.main import app

    with TestClient(app) as c:
        yield c


@pytest.fixture
def auth():
    return AUTH


@pytest.fixture
def scenarios():
    from modellab_experiments.scenarios import load_scenarios

    return load_scenarios()


@pytest.fixture
def mocks():
    from modellab_adapters import get_adapter
    from modellab_experiments.scenarios import load_model_configs

    m = {x.id: x for x in load_model_configs()}
    return get_adapter(m["mock-obedient"]), get_adapter(m["mock-cautious"])
