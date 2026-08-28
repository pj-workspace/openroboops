from contextlib import asynccontextmanager

import pytest

from openroboops.adapters.a2d import A2DAdapter


class FakeConnection:
    async def run(self, command: str, **_kwargs: object):
        if "pico_streamer" in command:
            return type("Result", (), {"stdout": "8 1\n", "exit_status": 0})()
        stdout = "100 50 50\n" if command.startswith("df ") else "active\nactive\nactive\n"
        return type("Result", (), {"stdout": stdout, "exit_status": 0})()


@pytest.mark.asyncio
async def test_a2d_detects_live_vr_process_activity(monkeypatch: pytest.MonkeyPatch) -> None:
    adapter = A2DAdapter({})

    @asynccontextmanager
    async def fake_ssh():
        yield FakeConnection()

    monkeypatch.setattr(adapter, "_ssh", fake_ssh)

    active, details = await adapter._read_vr_activity()

    assert active is True
    assert details["detector"] == "pico-process-activity"
    assert details["streamerRunning"] is True
    assert details["udpListener"] is True
    assert details["cpuTicksDelta"] == 8


@pytest.mark.asyncio
async def test_a2d_partial_telemetry_failure_keeps_reachable_robot_online(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    adapter = A2DAdapter({})

    @asynccontextmanager
    async def fake_ssh():
        yield FakeConnection()

    async def fake_collector(_connection, _method: str, path: str, _payload=None):
        if path == "/api/custom_battery":
            raise RuntimeError("collector rejected request")
        return {"data": {"job": None} if path == "/api/custom_progress" else {}}

    async def fake_vr_activity(_connection):
        return True, {"detector": "pico-process-activity", "cpuTicksDelta": 8}

    monkeypatch.setattr(adapter, "_ssh", fake_ssh)
    monkeypatch.setattr(adapter, "_collector_request_on_connection", fake_collector)
    monkeypatch.setattr(adapter, "_read_vr_activity_on_connection", fake_vr_activity)

    status = await adapter.read_status()

    assert status.online is True
    assert status.payload["vrActive"] is True
    assert status.payload["recording"] is False
    assert "battery status unavailable: collector rejected request" in status.payload["alerts"]
