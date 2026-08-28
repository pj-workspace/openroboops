from contextlib import asynccontextmanager

import pytest

import openroboops.adapters.a2d as a2d_module
from openroboops.adapters.a2d import A2DAdapter


class FakeListener:
    def get_port(self) -> int:
        return 19090

    def close(self) -> None:
        pass

    async def wait_closed(self) -> None:
        pass


class FakeConnection:
    async def forward_local_port(self, *_args: object) -> FakeListener:
        return FakeListener()

    async def run(self, command: str, **_kwargs: object):
        stdout = "100 50 50\n" if command.startswith("df ") else "active\nactive\nactive\n"
        return type("Result", (), {"stdout": stdout})()


class FakeWebSocket:
    def __init__(self, message: str) -> None:
        self.message = message
        self.sent: list[str] = []

    async def __aenter__(self) -> "FakeWebSocket":
        return self

    async def __aexit__(self, *_args: object) -> None:
        pass

    async def send(self, message: str) -> None:
        self.sent.append(message)

    async def recv(self) -> str:
        return self.message


@pytest.mark.asyncio
async def test_a2d_detects_live_vr_messages(monkeypatch: pytest.MonkeyPatch) -> None:
    adapter = A2DAdapter({})

    @asynccontextmanager
    async def fake_ssh():
        yield FakeConnection()

    websocket = FakeWebSocket('{"op":"publish","topic":"/remote/vr_data","msg":{"status":0,"err_code":0}}')
    monkeypatch.setattr(adapter, "_ssh", fake_ssh)
    monkeypatch.setattr(a2d_module, "connect", lambda *_args, **_kwargs: websocket)

    active, details = await adapter._read_vr_activity()

    assert active is True
    assert details == {"topic": "/remote/vr_data", "status": 0, "errCode": 0}
    assert '"op": "subscribe"' in websocket.sent[0]


@pytest.mark.asyncio
async def test_a2d_partial_telemetry_failure_keeps_reachable_robot_online(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    adapter = A2DAdapter({})

    @asynccontextmanager
    async def fake_ssh():
        yield FakeConnection()

    async def fake_collector(_method: str, path: str, _payload=None):
        if path == "/api/custom_battery":
            raise RuntimeError("collector rejected request")
        return {"data": {"job": None} if path == "/api/custom_progress" else {}}

    async def fake_vr_activity():
        return True, {"topic": "/remote/vr_data", "status": 0, "errCode": 0}

    monkeypatch.setattr(adapter, "_ssh", fake_ssh)
    monkeypatch.setattr(adapter, "_collector_request", fake_collector)
    monkeypatch.setattr(adapter, "_read_vr_activity", fake_vr_activity)

    status = await adapter.read_status()

    assert status.online is True
    assert status.payload["vrActive"] is True
    assert status.payload["recording"] is False
    assert "battery status unavailable: collector rejected request" in status.payload["alerts"]
