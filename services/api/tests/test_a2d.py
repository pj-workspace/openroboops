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

    websocket = FakeWebSocket(
        '{"op":"publish","topic":"/remote/vr_data","msg":{"status":0,"err_code":0}}'
    )
    monkeypatch.setattr(adapter, "_ssh", fake_ssh)
    monkeypatch.setattr(a2d_module, "connect", lambda *_args, **_kwargs: websocket)

    active, details = await adapter._read_vr_activity()

    assert active is True
    assert details == {"topic": "/remote/vr_data", "status": 0, "errCode": 0}
    assert '"op": "subscribe"' in websocket.sent[0]
