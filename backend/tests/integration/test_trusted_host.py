"""Anti DNS rebinding (issue #36): a API só responde a quem a chama por um nome de loopback ou por ALLOWED_HOSTS."""
import pytest
from httpx import ASGITransport, AsyncClient

from src.presentation.main import allowed_hosts, app


async def _get(host: str):
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        return await client.get("/api/v1/health", headers={"Host": host})


@pytest.mark.asyncio
@pytest.mark.parametrize("host", ["127.0.0.1:8000", "localhost:8000", "LOCALHOST", "[::1]:8000", "127.0.0.1"])
async def test_loopback_hosts_are_served(host):
    assert (await _get(host)).status_code == 200


@pytest.mark.asyncio
@pytest.mark.parametrize("host", ["rebind.attacker.example", "rebind.attacker.example:8000", "192.168.0.10:8000", "127.0.0.1.attacker.example"])
async def test_foreign_host_is_rejected(host):
    response = await _get(host)
    assert response.status_code == 400
    assert response.json() == {"detail": "Invalid host header"}


@pytest.mark.asyncio
async def test_malformed_host_is_rejected():
    assert (await _get("127.0.0.1:8000@attacker.example")).status_code == 400


def test_default_hosts_are_loopback_only():
    assert allowed_hosts("") == {"127.0.0.1", "localhost", "[::1]"}


def test_extra_hosts_come_from_the_environment():
    assert allowed_hosts(" Auto-Send.Acme.example , ,10.0.0.5") == {
        "127.0.0.1", "localhost", "[::1]", "auto-send.acme.example", "10.0.0.5",
    }
