import socket

import pytest

from jevscan_chainmonitor import enrich


@pytest.fixture(autouse=True)
def forbid_network(monkeypatch):
    def fail(*args, **kwargs):
        raise AssertionError("Tests must not contact external services")
    monkeypatch.setattr(socket.socket, "connect", fail)
    monkeypatch.setattr(socket.socket, "connect_ex", fail)


@pytest.fixture(autouse=True)
def no_real_credentials(monkeypatch):
    for name in ("MAINNET_RPC_URL", "ETHERSCAN_API_KEY", "TYPESAFE_API_KEY"):
        monkeypatch.delenv(name, raising=False)


@pytest.fixture(autouse=True)
def isolated_mixer_snapshot():
    enrich.mixer_payouts.cache_clear()
    yield
    enrich.mixer_payouts.cache_clear()
