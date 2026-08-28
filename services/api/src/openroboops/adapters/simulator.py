from __future__ import annotations

import asyncio
import hashlib
import math
import time
import uuid
from datetime import UTC, datetime, timedelta
from typing import Any

from .base import AdapterEpisode, AdapterStatus, ProgressCallback, RobotAdapter

SIMULATOR_CAPABILITIES = [
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


class SimulatorAdapter(RobotAdapter):
    async def probe(self) -> AdapterStatus:
        return await self.read_status()

    async def read_status(self) -> AdapterStatus:
        now = time.time()
        battery = round(74 + 5 * math.sin(now / 180), 1)
        payload = {
            "battery": {"available": True, "percent": battery, "charging": False, "statusText": "Discharging"},
            "stack": {"ready": True},
            "collisionProtection": {"enabled": True, "level": "mid", "value": 6},
            "bodyParams": {
                "headYaw": 0,
                "headPitch": 18,
                "lumbarPitch": 8,
                "height": 42,
                "maxLinearSpeed": 0.2,
                "maxAngularSpeed": 0.2,
            },
            "resetPoses": {
                "left": {"available": True, "source": "simulator"},
                "right": {"available": False, "source": "default"},
            },
            "recording": False,
            "vrActive": False,
            "disk": {"total": 2_000_000_000_000, "used": 244_000_000_000, "free": 1_756_000_000_000},
            "services": {"collector": "active", "modeSwitch": "active", "web": "active"},
            "alerts": [],
            "sampledAt": datetime.now(UTC).isoformat(),
        }
        return AdapterStatus(online=True, payload=payload, capabilities=SIMULATOR_CAPABILITIES)

    async def list_episodes(self) -> list[AdapterEpisode]:
        episodes: list[AdapterEpisode] = []
        for index in range(3):
            created_at = datetime.now(UTC) - timedelta(days=index + 1)
            metadata = {
                "create_time": created_at.isoformat(),
                "task_id": 1000 + index,
                "task_mode": "DEMO",
                "text": f"Simulator episode {index + 1}",
                "camera_list": ["head", "left_hand", "right_hand"],
                "data_validate": {"validate": index != 2, "reason": "" if index != 2 else "demo warning"},
                "is_aligned": index == 0,
            }
            episodes.append(
                AdapterEpisode(
                    uid=f"demo-episode-{index + 1}",
                    source_path=f"/simulator/record/demo-episode-{index + 1}",
                    metadata=metadata,
                    channels=["head", "left_hand", "right_hand"],
                    file_size=(index + 1) * 512_000_000,
                    duration_seconds=60.0 * (index + 1),
                    aligned=index == 0,
                    validation_status="valid" if index != 2 else "warning",
                )
            )
        return episodes

    async def start_collection(self, *, name: str, task_id: int, job_id: int) -> str:
        await asyncio.sleep(0.1)
        return f"sim-{uuid.uuid4()}"

    async def stop_collection(self, record_uid: str) -> dict[str, Any]:
        await asyncio.sleep(0.1)
        return {"released": True, "record_uid": record_uid}

    async def execute_command(self, command_type: str, params: dict[str, Any]) -> dict[str, Any]:
        if command_type not in SIMULATOR_CAPABILITIES:
            raise ValueError(f"unsupported simulator command: {command_type}")
        await asyncio.sleep(0.2)
        return {"simulated": True, "command": command_type, "params": params}

    async def sync_episode(self, *, uid: str, target_path: str, progress: ProgressCallback) -> dict[str, Any]:
        for value in (10, 35, 65, 90, 100):
            await asyncio.sleep(0.05)
            await progress(value)
        digest = hashlib.sha256(uid.encode()).hexdigest()
        return {
            "algorithm": "sha256",
            "files": [{"path": "meta_info.json", "sha256": digest, "size": 1024}],
            "target": target_path,
            "simulated": True,
        }
