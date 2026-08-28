from __future__ import annotations

import asyncio
import hashlib
import json
import os
import re
import shlex
import time
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any, cast
from urllib.parse import urlsplit

import asyncssh
import httpx

from .base import (
    AdapterCameraFrame,
    AdapterCameraPreview,
    AdapterEpisode,
    AdapterStatus,
    ProgressCallback,
    RobotAdapter,
)

A2D_CAPABILITIES = [
    "telemetry",
    "episode_index",
    "collection",
    "camera_preview",
    "sync",
    "save_reset_pose",
    "reset_arm",
    "clear_fault",
    "restart_stack",
    "set_body_params",
    "set_collision_protect",
    "reset_robot",
    "pack_pose",
]

CAMERA_PREVIEW_CHANNELS = {
    "head_color": "Head camera",
    "hand_left_color": "Left hand camera",
    "hand_right_color": "Right hand camera",
}

CAMERA_DDS_TOPICS = {
    "head_color": "/camera/head_color",
    "hand_left_color": "/camera/hand_left_color",
    "hand_right_color": "/camera/hand_right_color",
}

LIVE_HEAD_PREVIEW_DIRECTORIES = (
    "/dev/shm/hmi/head_center_fisheye",
    "/dev/shm/hmi/head",
)

LIVE_CAMERA_STREAM_READER = r"""import os, sys, time
import cv2
from a2d_sdk.core.camera.camera_receiver_cosine import CameraReceiverCosine

topic = sys.argv[1]
camera = CameraReceiverCosine([topic])
output = os.fdopen(3, "wb", buffering=0)
last_timestamp = None
next_frame_at = 0.0
frame_interval = 1.0 / 10.0
target_width = 720 if topic == "/camera/head_color" else 560
try:
    while True:
        packet = camera.get_latest_packet(topic)
        if packet is None:
            time.sleep(0.01)
            continue
        timestamp = int(packet.send_timestamp)
        now = time.monotonic()
        if timestamp == last_timestamp or now < next_frame_at:
            time.sleep(0.005)
            continue
        image_data = packet.get_image_data()
        if image_data is None:
            time.sleep(0.01)
            continue
        image = cv2.imdecode(image_data, cv2.IMREAD_COLOR)
        if image is None:
            time.sleep(0.01)
            continue
        height, width = image.shape[:2]
        target_height = max(1, int(height * target_width / width))
        image = cv2.resize(
            image,
            (target_width, target_height),
            interpolation=cv2.INTER_AREA,
        )
        encoded_ok, encoded = cv2.imencode(
            ".jpg",
            image,
            [int(cv2.IMWRITE_JPEG_QUALITY), 55],
        )
        if not encoded_ok:
            time.sleep(0.01)
            continue
        payload = encoded.tobytes()
        output.write(len(payload).to_bytes(4, "big"))
        output.write(payload)
        last_timestamp = timestamp
        next_frame_at = now + frame_interval
finally:
    camera.close()
"""

COMMAND_ENDPOINTS: dict[str, tuple[str, str]] = {
    "save_reset_pose": ("POST", "/api/custom_arm_reset_pose"),
    "reset_arm": ("POST", "/api/custom_arm_reset"),
    "clear_fault": ("POST", "/api/custom_clear_fault"),
    "restart_stack": ("POST", "/api/custom_restart_stack"),
    "set_body_params": ("POST", "/api/custom_body_params"),
    "set_collision_protect": ("POST", "/api/custom_collision_protect"),
    "reset_robot": ("POST", "/api/custom_reset_robot"),
    "pack_pose": ("POST", "/api/custom_pack_pose"),
}


class A2DAdapter(RobotAdapter):
    def _required(self, key: str) -> str:
        value = self.connection.get(key)
        if not isinstance(value, str) or not value.strip():
            raise ValueError(f"A2D connection requires {key}")
        return value

    @property
    def data_root(self) -> str:
        return str(self.connection.get("data_root", "/data/record"))

    @asynccontextmanager
    async def _ssh(self) -> AsyncIterator[asyncssh.SSHClientConnection]:
        host = self._required("host")
        username = self._required("username")
        known_hosts = self._required("known_hosts_path")
        private_key = self._required("private_key_path")
        port = int(self.connection.get("port", 22))
        connection = await asyncssh.connect(
            host,
            port=port,
            username=username,
            client_keys=[private_key],
            known_hosts=known_hosts,
            login_timeout=8,
            keepalive_interval=15,
        )
        try:
            yield connection
        finally:
            connection.close()
            await connection.wait_closed()

    async def _collector_request_on_connection(
        self,
        connection: asyncssh.SSHClientConnection,
        method: str,
        path: str,
        payload: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        collector_port = int(self.connection.get("collector_port", 8888))
        listener = await connection.forward_local_port("127.0.0.1", 0, "127.0.0.1", collector_port)
        try:
            local_port = listener.get_port()
            async with httpx.AsyncClient(timeout=90.0) as client:
                response = await client.request(
                    method,
                    f"http://127.0.0.1:{local_port}{path}",
                    json=payload,
                )
                response.raise_for_status()
                data = response.json()
        finally:
            listener.close()
            await listener.wait_closed()
        if not isinstance(data, dict):
            raise RuntimeError("collector returned a non-object response")
        if int(data.get("code", 0)) != 0:
            raise RuntimeError(str(data.get("msg") or "collector rejected request"))
        return data

    async def _collector_request(self, method: str, path: str, payload: dict[str, Any] | None = None) -> dict[str, Any]:
        async with self._ssh() as connection:
            return await self._collector_request_on_connection(connection, method, path, payload)

    async def _read_vr_activity_on_connection(
        self,
        connection: asyncssh.SSHClientConnection,
    ) -> tuple[bool | None, dict[str, Any]]:
        command = r"""
pid=$(pgrep -f '/pico_streamer( |$)' | head -1)
if [ -z "$pid" ]; then
    printf 'unavailable\n'
    exit 0
fi
before=$(awk '{print $14+$15}' "/proc/$pid/stat" 2>/dev/null)
sleep 0.5
after=$(awk '{print $14+$15}' "/proc/$pid/stat" 2>/dev/null)
listener=0
ss -H -lun 2>/dev/null | grep -q ':8080 ' && listener=1
if [ -z "$before" ] || [ -z "$after" ]; then
    printf 'unavailable\n'
else
    printf '%s %s\n' "$((after-before))" "$listener"
fi
"""
        result = await connection.run(command, check=False, timeout=4)
        stdout = result.stdout if isinstance(result.stdout, str) else ""
        values = stdout.strip().split()
        if result.exit_status != 0 or len(values) != 2 or not all(value.isdigit() for value in values):
            return None, {"detector": "pico-process-activity"}
        cpu_ticks, listener = (int(value) for value in values)
        details = {
            "detector": "pico-process-activity",
            "streamerRunning": True,
            "udpListener": listener == 1,
            "cpuTicksDelta": cpu_ticks,
        }
        if listener == 1 and cpu_ticks > 0:
            return True, details
        return None, details

    async def _read_vr_activity(self) -> tuple[bool | None, dict[str, Any]]:
        """Positively detect PICO activity without opening a rosbridge connection."""
        async with self._ssh() as connection:
            return await self._read_vr_activity_on_connection(connection)

    async def probe(self) -> AdapterStatus:
        return await self.read_status()

    async def read_status(self) -> AdapterStatus:
        endpoints = {
            "battery": "/api/custom_battery",
            "stack": "/api/custom_stack_ready",
            "bodyParams": "/api/custom_body_params",
            "collisionProtection": "/api/custom_collision_protect",
            "resetPoses": "/api/custom_arm_reset_pose",
            "progress": "/api/custom_progress",
        }

        async with self._ssh() as connection:

            async def read_one(name: str, path: str) -> tuple[str, dict[str, Any]]:
                try:
                    response = await self._collector_request_on_connection(connection, "GET", path)
                except Exception as exc:
                    raise RuntimeError(f"{name} status unavailable: {exc}") from exc
                value = response.get("data", {})
                if not isinstance(value, dict):
                    raise RuntimeError(f"collector returned invalid {name} data")
                return name, value

            vr_task = asyncio.create_task(self._read_vr_activity_on_connection(connection))
            values = await asyncio.gather(
                *(read_one(name, path) for name, path in endpoints.items()),
                return_exceptions=True,
            )
            disk_result = await connection.run(
                f"df -B1 --output=size,used,avail {shlex.quote(self.data_root)} | tail -1",
                check=False,
                timeout=6,
            )
            services_result = await connection.run(
                "systemctl is-active custom_collector.service a2d_mode_switch_server.service nginx.service",
                check=False,
                timeout=6,
            )
            try:
                vr_active, vr_status = await vr_task
            except Exception:
                vr_active = None
                vr_status = None

        payload: dict[str, Any] = {}
        warnings: list[str] = []
        for item in values:
            if isinstance(item, BaseException):
                warnings.append(str(item))
            else:
                name, value = item
                payload[name] = value
        if vr_status is None:
            payload["vrActive"] = None
            warnings.append("PICO/VR activity is unknown; motion commands fail closed")
        else:
            payload["vrActive"] = vr_active
            payload["vrStatus"] = vr_status
            if vr_active is True:
                warnings.append("PICO/VR input is active; motion commands are blocked")
            else:
                warnings.append("PICO/VR activity is unknown; motion commands fail closed")

        disk_stdout = disk_result.stdout if isinstance(disk_result.stdout, str) else ""
        disk_values = [int(item) for item in disk_stdout.split() if item.isdigit()]
        if len(disk_values) >= 3:
            payload["disk"] = {
                "total": disk_values[0],
                "used": disk_values[1],
                "free": disk_values[2],
            }
        else:
            warnings.append("robot data disk status is unavailable")
        services_stdout = services_result.stdout if isinstance(services_result.stdout, str) else ""
        service_values = services_stdout.splitlines()
        payload["services"] = {
            "collector": service_values[0] if len(service_values) > 0 else "unknown",
            "modeSwitch": service_values[1] if len(service_values) > 1 else "unknown",
            "web": service_values[2] if len(service_values) > 2 else "unknown",
        }
        payload["recording"] = bool((payload.get("progress") or {}).get("job"))
        payload["alerts"] = warnings
        return AdapterStatus(online=True, payload=payload, capabilities=A2D_CAPABILITIES)

    async def list_episodes(self) -> list[AdapterEpisode]:
        root = self.data_root.rstrip("/")
        episodes: list[AdapterEpisode] = []
        async with self._ssh() as connection:
            tree_result = await connection.run(
                f"find {shlex.quote(root)} -mindepth 2 -maxdepth 3 -type f -printf '%P\\0%s\\0'",
                check=False,
                timeout=30,
            )
            if tree_result.exit_status != 0:
                raise RuntimeError("could not inspect episode file trees")
            tree_stdout = tree_result.stdout if isinstance(tree_result.stdout, str) else ""
            tree_fields = tree_stdout.split("\0")
            files_by_episode: dict[str, list[dict[str, Any]]] = {}
            for index in range(0, len(tree_fields) - 1, 2):
                relative, size_text = tree_fields[index : index + 2]
                if "/" not in relative or not size_text.isdigit():
                    continue
                uid, file_path = relative.split("/", 1)
                if re.fullmatch(r"[A-Za-z0-9_.-]+", uid):
                    files_by_episode.setdefault(uid, []).append({"path": file_path, "size": int(size_text)})
            sftp = await connection.start_sftp_client()
            paths = await sftp.glob(f"{root}/*/meta_info.json")
            for path in paths:
                try:
                    async with sftp.open(path, "r") as file_handle:
                        raw = await file_handle.read()
                    metadata = json.loads(raw)
                    if not isinstance(metadata, dict):
                        continue
                    uid = Path(str(path)).parent.name
                    if not re.fullmatch(r"[A-Za-z0-9_.-]+", uid):
                        continue
                    channels = [str(value) for value in metadata.get("camera_list", [])]
                    validation = metadata.get("data_validate", {})
                    valid = validation.get("validate") if isinstance(validation, dict) else validation
                    validation_status = "valid" if valid is True else "warning" if valid is False else "unknown"
                    files = sorted(files_by_episode.get(uid, []), key=lambda item: item["path"])
                    missing_items = [
                        key for key in ("camera_list", "data_validate", "is_aligned") if key not in metadata
                    ]
                    metadata["_openroboops"] = {
                        "file_tree": files,
                        "file_tree_max_depth": 3,
                        "missing_items": missing_items,
                    }
                    duration = next(
                        (
                            metadata[key]
                            for key in ("duration", "duration_seconds", "record_duration")
                            if isinstance(metadata.get(key), int | float)
                        ),
                        0,
                    )
                    episodes.append(
                        AdapterEpisode(
                            uid=uid,
                            source_path=f"{root}/{uid}",
                            metadata=metadata,
                            channels=channels,
                            file_size=int(metadata.get("file_size", 0))
                            if isinstance(metadata.get("file_size"), int | float)
                            else sum(int(item["size"]) for item in files),
                            duration_seconds=float(duration),
                            aligned=bool(metadata.get("is_aligned", False)),
                            validation_status=validation_status,
                        )
                    )
                except (OSError, ValueError, json.JSONDecodeError):
                    continue
        return sorted(episodes, key=lambda episode: episode.uid)

    async def start_collection(self, *, name: str, task_id: int, job_id: int) -> str:
        response = await self._collector_request(
            "POST",
            "/api/custom_start",
            {
                "userId": "openroboops",
                "user_taskId": task_id,
                "user_jobId": job_id,
                "taskName": name,
            },
        )
        uid = response.get("record_uid") or (response.get("data") or {}).get("record_uid")
        if not isinstance(uid, str) or not uid:
            raise RuntimeError("collector did not return record_uid")
        return uid

    async def stop_collection(self, record_uid: str) -> dict[str, Any]:
        if not re.fullmatch(r"[A-Za-z0-9_.-]+", record_uid):
            raise ValueError("invalid record UID")
        response = await self._collector_request("PUT", f"/api/custom_stop?uuid={record_uid}")
        return response.get("data", {})

    async def list_camera_previews(self) -> list[AdapterCameraPreview]:
        response = await self._collector_request("GET", "/api/custom_preview_images")
        data = response.get("data", {})
        metadata = response.get("meta", {})
        if not isinstance(data, dict) or not isinstance(metadata, dict):
            raise RuntimeError("collector returned invalid camera preview metadata")
        previews: dict[str, AdapterCameraPreview] = {}
        for channel, label in CAMERA_PREVIEW_CHANNELS.items():
            source_url = data.get(channel)
            details = metadata.get(channel, {})
            if not isinstance(source_url, str) or not source_url or not isinstance(details, dict):
                continue
            captured_at_ms = details.get("mtimeMs")
            age_ms = details.get("ageMs")
            size = details.get("size")
            previews[channel] = AdapterCameraPreview(
                channel=channel,
                label=label,
                captured_at_ms=int(captured_at_ms) if isinstance(captured_at_ms, int | float) else None,
                age_ms=max(0, int(age_ms)) if isinstance(age_ms, int | float) else None,
                size=int(size) if isinstance(size, int | float) else None,
                version=str(int(captured_at_ms)) if isinstance(captured_at_ms, int | float) else "unknown",
            )
        try:
            live_head = await self._live_head_preview_metadata()
        except Exception:
            live_head = None
        if live_head is not None:
            previews[live_head.channel] = live_head
        for channel, label in CAMERA_PREVIEW_CHANNELS.items():
            preview = previews.get(channel)
            if preview is None:
                previews[channel] = AdapterCameraPreview(
                    channel=channel,
                    label=label,
                    captured_at_ms=None,
                    age_ms=None,
                    size=None,
                    version="cosine-live",
                    streamable=True,
                )
            else:
                preview.streamable = True
        return [previews[channel] for channel in CAMERA_PREVIEW_CHANNELS]

    async def _live_head_preview_metadata(self) -> AdapterCameraPreview | None:
        async with self._ssh() as connection:
            sftp = await connection.start_sftp_client()
            path = await self._latest_live_head_path(sftp)
            if path is None:
                return None
            attributes = await sftp.stat(path)
        captured_at_ms = int(attributes.mtime * 1000) if attributes.mtime is not None else None
        return AdapterCameraPreview(
            channel="head_color",
            label="Head camera",
            captured_at_ms=captured_at_ms,
            age_ms=max(0, int(time.time() * 1000) - captured_at_ms) if captured_at_ms is not None else None,
            size=int(attributes.size) if attributes.size is not None else None,
            version=str(captured_at_ms or "live"),
            streamable=True,
        )

    @staticmethod
    async def _latest_live_head_path(sftp: asyncssh.SFTPClient) -> str | None:
        for directory in LIVE_HEAD_PREVIEW_DIRECTORIES:
            paths = await sftp.glob(f"{directory}/*.jpg")
            if paths:
                return max((str(path) for path in paths), key=lambda path: Path(path).name)
        return None

    async def read_camera_preview(self, channel: str) -> AdapterCameraFrame:
        if channel not in CAMERA_PREVIEW_CHANNELS:
            raise ValueError("unknown camera preview channel")
        if channel == "head_color":
            async with self._ssh() as connection:
                sftp = await connection.start_sftp_client()
                path = await self._latest_live_head_path(sftp)
                if path is not None:
                    async with sftp.open(path, "rb") as file_handle:
                        content = cast(bytes, await file_handle.read())
                    if not content.startswith(b"\xff\xd8"):
                        raise RuntimeError("live camera source returned a non-JPEG frame")
                    return AdapterCameraFrame(content=content, media_type="image/jpeg")
        async with self._ssh() as connection:
            manifest = await self._collector_request_on_connection(connection, "GET", "/api/custom_preview_images")
            data = manifest.get("data", {})
            source_url = data.get(channel) if isinstance(data, dict) else None
            if not isinstance(source_url, str) or not source_url:
                raise FileNotFoundError("camera preview is unavailable")
            parsed = urlsplit(source_url)
            if parsed.scheme not in {"http", "https"} or parsed.path != "/api/proxy_image":
                raise RuntimeError("collector returned an unsafe camera preview URL")
            collector_port = int(self.connection.get("collector_port", 8888))
            listener = await connection.forward_local_port("127.0.0.1", 0, "127.0.0.1", collector_port)
            try:
                target = f"http://127.0.0.1:{listener.get_port()}{parsed.path}"
                if parsed.query:
                    target = f"{target}?{parsed.query}"
                async with httpx.AsyncClient(timeout=20.0) as client:
                    response = await client.get(target)
                    response.raise_for_status()
            finally:
                listener.close()
                await listener.wait_closed()
        media_type = response.headers.get("content-type", "").split(";", 1)[0].lower()
        if media_type not in {"image/jpeg", "image/png", "image/webp"}:
            raise RuntimeError("collector returned a non-image camera preview")
        if not response.content or len(response.content) > 10 * 1024 * 1024:
            raise RuntimeError("collector returned an invalid camera preview size")
        return AdapterCameraFrame(content=response.content, media_type=media_type)

    def camera_preview_stream(self, channel: str) -> AsyncIterator[AdapterCameraFrame]:
        topic = CAMERA_DDS_TOPICS.get(channel)
        if topic is None:
            raise ValueError("unknown camera preview channel")

        async def frames() -> AsyncIterator[AdapterCameraFrame]:
            locator_ip = self._required("camera_bus_locator_ip")
            discovery_uri = self._required("camera_bus_discovery_uri")
            parsed_discovery = urlsplit(discovery_uri)
            if parsed_discovery.scheme not in {"http", "https"} or not parsed_discovery.hostname:
                raise ValueError("A2D camera bus discovery URI is invalid")
            async with self._ssh() as connection:
                command = (
                    f"env LOCATOR_IP={shlex.quote(locator_ip)} "
                    f"AORTA_DISCOVERY_URI={shlex.quote(discovery_uri)} "
                    "PROTOCOL_BUFFERS_PYTHON_IMPLEMENTATION=python "
                    f"python3 -u -c {shlex.quote(LIVE_CAMERA_STREAM_READER)} {shlex.quote(topic)} "
                    "3>&1 1>/dev/null 2>/dev/null"
                )
                process = await connection.create_process(
                    command,
                    encoding=None,
                )
                try:
                    while True:
                        header = cast(bytes, await process.stdout.readexactly(4))
                        size = int.from_bytes(header, "big")
                        if size <= 0 or size > 2 * 1024 * 1024:
                            raise RuntimeError("live camera reader returned an invalid frame size")
                        content = cast(bytes, await process.stdout.readexactly(size))
                        if not content.startswith(b"\xff\xd8"):
                            raise RuntimeError("live camera reader returned a non-JPEG frame")
                        yield AdapterCameraFrame(content=content, media_type="image/jpeg")
                finally:
                    process.terminate()
                    await process.wait()

        return frames()

    async def execute_command(self, command_type: str, params: dict[str, Any]) -> dict[str, Any]:
        if command_type not in COMMAND_ENDPOINTS:
            raise ValueError(f"unsupported A2D command: {command_type}")
        if command_type in {"save_reset_pose", "reset_arm"}:
            side = str(params.get("side", "")).lower()
            if side not in {"left", "right"}:
                raise ValueError("side must be left or right")
            params = {"side": side}
        elif command_type == "set_collision_protect":
            if params.get("enabled") is False:
                raise ValueError("OpenRoboOps never disables collision protection")
            level = str(params.get("level", "mid")).lower()
            if level not in {"high", "mid", "low"}:
                raise ValueError("collision level must be high, mid, or low")
            params = {"enabled": True, "level": level}
        method, path = COMMAND_ENDPOINTS[command_type]
        response = await self._collector_request(method, path, params)
        return response.get("data", {})

    async def sync_episode(self, *, uid: str, target_path: str, progress: ProgressCallback) -> dict[str, Any]:
        if not re.fullmatch(r"[A-Za-z0-9_.-]+", uid):
            raise ValueError("invalid episode UID")
        source = f"{self.data_root.rstrip('/')}/{uid}/"
        target = Path(target_path)
        await asyncio.to_thread(target.mkdir, parents=True, exist_ok=True)
        host = self._required("host")
        username = self._required("username")
        known_hosts = self._required("known_hosts_path")
        private_key = self._required("private_key_path")
        port = str(int(self.connection.get("port", 22)))
        ssh_command = (
            f"ssh -p {port} -i {shlex.quote(private_key)} "
            f"-o UserKnownHostsFile={shlex.quote(known_hosts)} -o StrictHostKeyChecking=yes"
        )
        process = await asyncio.create_subprocess_exec(
            "rsync",
            "-a",
            "--partial",
            "--append-verify",
            "--info=progress2",
            "-e",
            ssh_command,
            f"{username}@{host}:{source}",
            f"{target}/",
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.STDOUT,
        )
        assert process.stdout is not None
        async for line in process.stdout:
            text = line.decode("utf-8", "replace")
            match = re.search(r"(\d{1,3})%", text)
            if match:
                await progress(min(int(match.group(1)), 95))
        if await process.wait() != 0:
            raise RuntimeError("rsync failed; source data was left untouched")
        await progress(96)
        local_manifest = await asyncio.to_thread(self._hash_tree, target)
        remote_manifest = await self._remote_hash_tree(source)
        local_hashes = {item["path"]: item["sha256"] for item in local_manifest}
        if remote_manifest != local_hashes:
            raise RuntimeError("SHA-256 verification failed; source data was left untouched")
        await progress(100)
        return {
            "algorithm": "sha256",
            "verified": True,
            "files": local_manifest,
            "source": source,
            "target": str(target),
        }

    async def _remote_hash_tree(self, source: str) -> dict[str, str]:
        command = f"cd {shlex.quote(source)} && find . -type f -print0 | sort -z | xargs -0 -r sha256sum -b"
        async with self._ssh() as connection:
            result = await connection.run(command, check=False, timeout=None)
        if result.exit_status != 0:
            raise RuntimeError("could not create source SHA-256 manifest")
        manifest: dict[str, str] = {}
        stdout = result.stdout if isinstance(result.stdout, str) else ""
        for line in stdout.splitlines():
            match = re.fullmatch(r"([0-9a-f]{64}) [ *](.+)", line)
            if not match:
                raise RuntimeError("source SHA-256 manifest contained an invalid entry")
            path = match.group(2).removeprefix("./")
            manifest[path] = match.group(1)
        return manifest

    @staticmethod
    def _hash_tree(root: Path) -> list[dict[str, Any]]:
        result: list[dict[str, Any]] = []
        for path in sorted(item for item in root.rglob("*") if item.is_file()):
            digest = hashlib.sha256()
            with path.open("rb") as file_handle:
                for chunk in iter(lambda: file_handle.read(1024 * 1024), b""):
                    digest.update(chunk)
            result.append(
                {
                    "path": str(path.relative_to(root)),
                    "sha256": digest.hexdigest(),
                    "size": os.path.getsize(path),
                }
            )
        return result
