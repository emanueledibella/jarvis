import pytest

from jarvis.config import ConfigStore
from jarvis.runtime import Runtime


@pytest.fixture(autouse=True)
def no_real_carrier_requests(monkeypatch):
    class UnconfiguredCarrier:
        def __init__(self, *args, **kwargs):
            raise AssertionError("Le prove automatiche non possono contattare un operatore reale.")

    monkeypatch.setattr("twilio.rest.Client", UnconfiguredCarrier)


@pytest.fixture
def config(tmp_path):
    return ConfigStore(env_file=tmp_path / "absent.env", data_dir=tmp_path / "data")


@pytest.fixture
async def runtime(config):
    runtime = Runtime(config)
    await runtime.start(scheduler=False, process_lock=False)
    try:
        yield runtime
    finally:
        await runtime.close()
