from sqlalchemy import select

import openroboops.worker as worker_module
from openroboops.adapters.base import AdapterStatus
from openroboops.database import SessionLocal, create_schema
from openroboops.models import Robot
from openroboops.worker import Worker


class OnlineAdapter:
    async def read_status(self) -> AdapterStatus:
        return AdapterStatus(
            online=True,
            payload={
                "collisionProtection": {"enabled": True},
                "recording": False,
                "vrActive": False,
            },
            capabilities=["telemetry"],
        )


async def fail_episode_scan(*_args: object) -> list[object]:
    raise TimeoutError("episode index timeout")


async def test_episode_scan_failure_does_not_mark_robot_offline(monkeypatch) -> None:
    await create_schema()
    async with SessionLocal() as db:
        robot = Robot(
            name="Worker Scan Failure Fixture",
            model="Fixture",
            adapter_type="simulator",
            connection={"seed": "worker-scan-failure"},
        )
        db.add(robot)
        await db.commit()
        robot_id = robot.id

    monkeypatch.setattr(worker_module, "create_adapter", lambda *_args: OnlineAdapter())
    monkeypatch.setattr(worker_module, "scan_robot_episodes", fail_episode_scan)

    await Worker().poll_robots()

    async with SessionLocal() as db:
        persisted = await db.scalar(select(Robot).where(Robot.id == robot_id))
        assert persisted is not None
        assert persisted.online is True
        assert persisted.status.get("alerts") is None
