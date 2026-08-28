import asyncio
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
        if path == "/api/custom_progress":
            return {"data": {"job": {"uid": "upload-only"}}}
        if path == "/api/custom_stack_ready":
            return {"data": {"ready": True, "recordTaskStatus": 400}}
        return {"data": {}}

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


@pytest.mark.asyncio
async def test_a2d_uses_recorder_status_instead_of_upload_progress(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    adapter = A2DAdapter({})

    @asynccontextmanager
    async def fake_ssh():
        yield FakeConnection()

    async def fake_collector(_connection, _method: str, path: str, _payload=None):
        if path == "/api/custom_stack_ready":
            return {"data": {"ready": True, "recordTaskStatus": 200}}
        if path == "/api/custom_progress":
            return {"data": {"job": {}}}
        return {"data": {}}

    async def fake_vr_activity(_connection):
        return False, {"detector": "pico-process-activity", "cpuTicksDelta": 0}

    monkeypatch.setattr(adapter, "_ssh", fake_ssh)
    monkeypatch.setattr(adapter, "_collector_request_on_connection", fake_collector)
    monkeypatch.setattr(adapter, "_read_vr_activity_on_connection", fake_vr_activity)

    status = await adapter.read_status()

    assert status.payload["recording"] is True


@pytest.mark.asyncio
async def test_a2d_camera_preview_metadata_is_sanitized(monkeypatch: pytest.MonkeyPatch) -> None:
    adapter = A2DAdapter({})

    async def fake_collector(_method: str, _path: str, _payload=None):
        return {
            "data": {
                "head_color": "http://robot.internal/api/proxy_image?path=/private/frame.jpg",
                "unexpected": "http://robot.internal/secret",
            },
            "meta": {"head_color": {"mtimeMs": 1_700_000_000_000, "ageMs": 250, "size": 42_000}},
        }

    monkeypatch.setattr(adapter, "_collector_request", fake_collector)

    previews = await adapter.list_camera_previews()

    assert len(previews) == 3
    assert previews[0].channel == "head_color"
    assert previews[0].label == "Head camera"
    assert previews[0].version == "1700000000000"
    assert all(preview.streamable for preview in previews)
    assert {preview.channel for preview in previews} == {
        "head_color",
        "hand_left_color",
        "hand_right_color",
    }
    assert not hasattr(previews[0], "source_url")


@pytest.mark.asyncio
async def test_a2d_camera_frame_rejects_collector_ssrf_url(monkeypatch: pytest.MonkeyPatch) -> None:
    adapter = A2DAdapter({})

    @asynccontextmanager
    async def fake_ssh():
        yield FakeConnection()

    async def fake_collector(_connection, _method: str, _path: str, _payload=None):
        return {"data": {"hand_left_color": "http://metadata.internal/latest"}}

    monkeypatch.setattr(adapter, "_ssh", fake_ssh)
    monkeypatch.setattr(adapter, "_collector_request_on_connection", fake_collector)

    with pytest.raises(RuntimeError, match="unsafe camera preview URL"):
        await adapter.read_camera_preview("hand_left_color")


@pytest.mark.asyncio
async def test_a2d_streams_hand_camera_from_cosine_bus(monkeypatch: pytest.MonkeyPatch) -> None:
    adapter = A2DAdapter(
        {
            "camera_bus_locator_ip": "robot-control.local",
            "camera_bus_discovery_uri": "http://robot-control.local:2379",
        }
    )
    payload = b"\xff\xd8live-jpeg"
    reader = asyncio.StreamReader()
    reader.feed_data(len(payload).to_bytes(4, "big") + payload)

    class FakeProcess:
        stdout = reader

        def terminate(self) -> None:
            pass

        async def wait(self) -> None:
            pass

    class StreamConnection:
        command = ""

        async def create_process(self, command: str, **_kwargs: object) -> FakeProcess:
            self.command = command
            return FakeProcess()

    connection = StreamConnection()

    @asynccontextmanager
    async def fake_ssh():
        yield connection

    monkeypatch.setattr(adapter, "_ssh", fake_ssh)

    frames = adapter.camera_preview_stream("hand_left_color")
    frame = await anext(frames)
    await frames.aclose()

    assert frame.content == payload
    assert frame.media_type == "image/jpeg"
    assert "/camera/hand_left_color" in connection.command


def test_a2d_rejects_unknown_live_camera_channel() -> None:
    adapter = A2DAdapter({})

    with pytest.raises(ValueError, match="unknown camera preview channel"):
        adapter.camera_preview_stream("unknown")


@pytest.mark.asyncio
async def test_a2d_force_stop_restarts_stack_without_discarding(monkeypatch: pytest.MonkeyPatch) -> None:
    adapter = A2DAdapter({})
    calls: list[tuple[str, str]] = []

    async def fake_request(method: str, path: str, _payload=None):
        calls.append((method, path))
        if path.startswith("/api/custom_stop"):
            raise RuntimeError("recorder slot was not released")
        return {"data": {"restarted": True}}

    monkeypatch.setattr(adapter, "_collector_request", fake_request)

    result = await adapter.force_stop_collection("record-uid")

    assert result["method"] == "restart-stack-fallback"
    assert calls == [
        ("PUT", "/api/custom_stop?uuid=record-uid"),
        ("POST", "/api/custom_restart_stack"),
    ]


@pytest.mark.asyncio
async def test_a2d_discard_is_explicit(monkeypatch: pytest.MonkeyPatch) -> None:
    adapter = A2DAdapter({})
    calls: list[tuple[str, str]] = []

    async def fake_request(method: str, path: str, _payload=None):
        calls.append((method, path))
        return {"data": {"discarded": True}}

    monkeypatch.setattr(adapter, "_collector_request", fake_request)

    result = await adapter.discard_episode("record-uid")

    assert result == {"discarded": True}
    assert calls == [("POST", "/api/custom_discard?uuid=record-uid")]


@pytest.mark.asyncio
async def test_a2d_detects_active_collection_from_camera_directory_mtime(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    adapter = A2DAdapter({})

    class ActivityConnection:
        async def run(self, _command: str, **_kwargs: object):
            return type("Result", (), {"stdout": "200 190\n", "exit_status": 0})()

    @asynccontextmanager
    async def fake_ssh():
        yield ActivityConnection()

    monkeypatch.setattr(adapter, "_ssh", fake_ssh)

    assert await adapter.read_collection_activity("record-uid") is True
