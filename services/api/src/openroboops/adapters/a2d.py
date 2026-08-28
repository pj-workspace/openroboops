from __future__ import annotations

import asyncio
import hashlib
import json
import os
import re
import shlex
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any

import asyncssh
import httpx

from .base import AdapterEpisode, AdapterStatus, ProgressCallback, RobotAdapter

A2D_CAPABILITIES = [
    "telemetry",
    "episode_index",
    "collection",
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
