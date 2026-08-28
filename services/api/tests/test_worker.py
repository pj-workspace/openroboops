from sqlalchemy import select

import openroboops.worker as worker_module
from openroboops.adapters.base import AdapterStatus
from openroboops.database import SessionLocal, create_schema
from openroboops.models import CollectionSession, Robot
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


async def test_unknown_recorder_status_does_not_fail_active_a2d_collection(monkeypatch) -> None:
    await create_schema()
    async with SessionLocal() as db:
        robot = Robot(
            name="Worker Unknown Recorder Fixture",
            model="Fixture",
            adapter_type="a2d",
            connection={},
        )
        db.add(robot)
        await db.flush()
        collection = CollectionSession(
            robot_id=robot.id,
            name="active fixture",
            task_id=1,
            job_id=1,
            record_uid="fixture-record-uid",
            status="recording",
        )
        db.add(collection)
        await db.commit()
        collection_id = collection.id

    class UnknownRecorderAdapter:
        async def read_status(self) -> AdapterStatus:
            return AdapterStatus(
                online=True,
                payload={"recording": None, "collisionProtection": {"enabled": True}},
                capabilities=["collection"],
            )

    monkeypatch.setattr(worker_module, "create_adapter", lambda *_args: UnknownRecorderAdapter())
    monkeypatch.setattr(worker_module, "scan_robot_episodes", fail_episode_scan)

    worker = Worker()
    await worker.poll_robots()
    await worker.poll_robots()

    async with SessionLocal() as db:
        persisted = await db.get(CollectionSession, collection_id)
        assert persisted is not None
        assert persisted.status == "recording"
        assert persisted.error is None


async def test_camera_file_activity_overrides_unreliable_recorder_status(monkeypatch) -> None:
    await create_schema()
    async with SessionLocal() as db:
        robot = Robot(
            name="Worker Active Camera Fixture",
            model="Fixture",
            adapter_type="a2d",
            connection={},
        )
        db.add(robot)
        await db.flush()
        collection = CollectionSession(
            robot_id=robot.id,
            name="active camera fixture",
            task_id=2,
            job_id=2,
            record_uid="active-camera-uid",
            status="recording",
        )
        db.add(collection)
        await db.commit()
        collection_id = collection.id

    class ActiveCameraAdapter:
        async def read_status(self) -> AdapterStatus:
            return AdapterStatus(
                online=True,
                payload={"recording": False, "collisionProtection": {"enabled": True}},
                capabilities=["collection"],
            )

        async def read_collection_activity(self, _record_uid: str) -> bool:
            return True

    monkeypatch.setattr(worker_module, "create_adapter", lambda *_args: ActiveCameraAdapter())
    monkeypatch.setattr(worker_module, "scan_robot_episodes", fail_episode_scan)

    worker = Worker()
    await worker.poll_robots()
    await worker.poll_robots()

    async with SessionLocal() as db:
        persisted = await db.get(CollectionSession, collection_id)
        assert persisted is not None
        assert persisted.status == "recording"
        assert persisted.error is None
