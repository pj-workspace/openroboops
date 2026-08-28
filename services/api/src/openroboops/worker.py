from __future__ import annotations

import asyncio
import json
import logging
from datetime import UTC, datetime, timedelta

from sqlalchemy import delete, select

from .adapters.registry import create_adapter
from .config import get_settings
from .database import SessionLocal, create_schema, ensure_telemetry_partitions
from .models import (
    CollectionSession,
    CommandJob,
    ControlLease,
    Episode,
    Robot,
    SyncJob,
    TelemetrySnapshot,
    as_utc,
    utcnow,
)
from .service import audit, emit_event, scan_robot_episodes, validate_command_preflight

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s %(message)s",
)
logger = logging.getLogger("openroboops.worker")
settings = get_settings()


class Worker:
    def __init__(self) -> None:
        self.last_persisted: dict[str, datetime] = {}
        self.last_scanned: dict[str, datetime] = {}
        self.last_partition_check: datetime | None = None
        self.collection_misses: dict[str, int] = {}

    async def tick(self) -> None:
        await self.poll_robots()
        await self.auto_stop_collections()
        await self.process_command()
        await self.process_sync()
        await self.prune_telemetry()
        await self.maintain_partitions()

    async def maintain_partitions(self) -> None:
        now = datetime.now(UTC)
        if self.last_partition_check and now - self.last_partition_check < timedelta(hours=1):
            return
        await ensure_telemetry_partitions()
        self.last_partition_check = now

    async def poll_robots(self) -> None:
        async with SessionLocal() as db:
            robots = list((await db.scalars(select(Robot).order_by(Robot.name))).all())
        for robot_snapshot in robots:
            scan_robot_id: str | None = None
            async with SessionLocal() as db:
                robot = await db.get(Robot, robot_snapshot.id)
                if robot is None:
                    continue
                old_online = robot.online
                old_status = json.dumps(robot.status, sort_keys=True, default=str)
                try:
                    adapter_status = await create_adapter(robot.adapter_type, robot.connection).read_status()
                    active_collection = await db.scalar(
                        select(CollectionSession).where(
                            CollectionSession.robot_id == robot.id,
                            CollectionSession.status.in_(["starting", "recording", "stopping"]),
                        )
                    )
                    payload = dict(adapter_status.payload)
                    reported_recording = payload.get("recording") is True
                    if active_collection is not None and robot.adapter_type == "a2d":
                        if reported_recording:
                            self.collection_misses.pop(active_collection.id, None)
                        else:
                            misses = self.collection_misses.get(active_collection.id, 0) + 1
                            self.collection_misses[active_collection.id] = misses
                            if misses >= 2:
                                active_collection.status = "failed"
                                active_collection.error = (
                                    "collector stopped reporting the active recording after recovery"
                                )
                                active_collection.stopped_at = utcnow()
                                await emit_event(
                                    db,
                                    "collection.progress",
                                    {"id": active_collection.id, "status": "failed"},
                                    robot.id,
                                )
                                active_collection = None
                    if active_collection is not None:
                        payload["recording"] = True
                    robot.online = adapter_status.online
                    robot.status = payload
                    robot.capabilities = adapter_status.capabilities
                    if adapter_status.online:
                        robot.last_seen = utcnow()
                    robot.revision += 1
                    if old_online != robot.online:
                        await emit_event(
                            db,
                            "robot.status",
                            {"online": robot.online, "name": robot.name},
                            robot.id,
                        )
                    now = datetime.now(UTC)
                    should_persist = (
                        robot.id not in self.last_persisted
                        or now - self.last_persisted[robot.id] >= timedelta(seconds=settings.persist_interval_seconds)
                        or old_status != json.dumps(payload, sort_keys=True, default=str)
                    )
                    if should_persist:
                        db.add(TelemetrySnapshot(robot_id=robot.id, payload=payload))
                        self.last_persisted[robot.id] = now
                    await db.commit()
                    scan_robot_id = robot.id
                except Exception as exc:
                    robot.online = False
                    robot.revision += 1
                    robot.status = {
                        **(robot.status or {}),
                        "alerts": [f"adapter error: {exc}"],
                    }
                    if old_online:
                        await emit_event(
                            db,
                            "alert",
                            {"severity": "error", "message": str(exc)},
                            robot.id,
                        )
                    await db.commit()
                    logger.warning("Robot poll failed for %s: %s", robot.name, exc)
            if scan_robot_id is not None:
                await self.scan_if_due(scan_robot_id)

    async def scan_if_due(self, robot_id: str) -> None:
        now = datetime.now(UTC)
        last = self.last_scanned.get(robot_id)
        if last and now - last < timedelta(seconds=settings.episode_scan_interval_seconds):
            return
        async with SessionLocal() as db:
            robot = await db.get(Robot, robot_id)
            if robot is None or not robot.online:
                return
            robot_name = robot.name
            try:
                episodes = await scan_robot_episodes(db, robot)
                await db.commit()
                self.last_scanned[robot_id] = now
                logger.info("Indexed %s episodes for %s", len(episodes), robot_name)
            except Exception as exc:
                await db.rollback()
                logger.warning("Episode scan failed for %s: %s", robot_name, exc)

    async def process_sync(self) -> None:
        async with SessionLocal() as db:
            job = await db.scalar(
                select(SyncJob).where(SyncJob.status == "queued").order_by(SyncJob.created_at).limit(1)
            )
            if job is None:
                return
            episode = await db.get(Episode, job.episode_id)
            robot = await db.get(Robot, job.robot_id)
            if episode is None or robot is None:
                job.status = "failed"
                job.error = "robot or episode no longer exists"
                job.finished_at = utcnow()
                await db.commit()
                return
            job.status = "running"
            job.started_at = utcnow()
            episode.sync_status = "running"
            target = settings.data_root / robot.id / episode.uid
            job.target_path = str(target)
            await db.commit()
            job_id = job.id
            episode_id = episode.id
            adapter_type = robot.adapter_type
            connection = robot.connection
            uid = episode.uid

        async def update_progress(value: int) -> None:
            async with SessionLocal() as progress_db:
                progress_job = await progress_db.get(SyncJob, job_id)
                if progress_job:
                    progress_job.progress = value
                    progress_job.status = "verifying" if value >= 96 else "running"
                    await emit_event(
                        progress_db,
                        "sync.progress",
                        {"id": job_id, "progress": value, "status": progress_job.status},
                        progress_job.robot_id,
                    )
                    await progress_db.commit()

        try:
            manifest = await create_adapter(adapter_type, connection).sync_episode(
                uid=uid,
                target_path=str(target),
                progress=update_progress,
            )
            async with SessionLocal() as db:
                job = await db.get(SyncJob, job_id)
                episode = await db.get(Episode, episode_id)
                if job and episode:
                    job.status = "completed"
                    job.progress = 100
                    job.manifest = manifest
                    job.finished_at = utcnow()
                    episode.sync_status = "completed"
                    await emit_event(
                        db,
                        "sync.progress",
                        {"id": job.id, "progress": 100, "status": "completed"},
                        job.robot_id,
                    )
                    await db.commit()
        except Exception as exc:
            async with SessionLocal() as db:
                job = await db.get(SyncJob, job_id)
                episode = await db.get(Episode, episode_id)
                if job:
                    job.status = "failed"
                    job.error = str(exc)
                    job.finished_at = utcnow()
                if episode:
                    episode.sync_status = "failed"
                await db.commit()
            logger.exception("Sync job failed: %s", exc)

    async def process_command(self) -> None:
        async with SessionLocal() as db:
            job = await db.scalar(
                select(CommandJob).where(CommandJob.status == "queued").order_by(CommandJob.created_at).limit(1)
            )
            if job is None:
                return
            robot = await db.get(Robot, job.robot_id)
            lease = await db.get(ControlLease, job.lease_id)
            now = datetime.now(UTC)
            if robot is None or lease is None or as_utc(lease.expires_at) < now or lease.revoked_at:
                job.status = "failed"
                job.error = "control lease expired or robot unavailable"
                job.finished_at = utcnow()
                await db.commit()
                return
            try:
                validate_command_preflight(robot, job.command_type, job.params)
            except Exception as exc:
                job.status = "failed"
                job.error = getattr(exc, "detail", str(exc))
                job.finished_at = utcnow()
                await db.commit()
                return
            job.status = "running"
            job.started_at = utcnow()
            await emit_event(db, "command.status", {"id": job.id, "status": "running"}, robot.id)
            await db.commit()
            job_id = job.id
            robot_id = robot.id
            adapter_type = robot.adapter_type
            connection = robot.connection
            command_type = job.command_type
            params = job.params
        try:
            result = await create_adapter(adapter_type, connection).execute_command(command_type, params)
            async with SessionLocal() as db:
                job = await db.get(CommandJob, job_id)
                if job:
                    job.status = "completed"
                    job.result = result
                    job.finished_at = utcnow()
                    await audit(
                        db,
                        action="command.execute",
                        user_id=job.user_id,
                        robot_id=robot_id,
                        target=command_type,
                        request_payload=params,
                        result_payload=result,
                    )
                    await emit_event(db, "command.status", {"id": job.id, "status": "completed"}, robot_id)
                    await db.commit()
        except Exception as exc:
            async with SessionLocal() as db:
                job = await db.get(CommandJob, job_id)
                if job:
                    job.status = "failed"
                    job.error = str(exc)
                    job.finished_at = utcnow()
                    await audit(
                        db,
                        action="command.execute",
                        user_id=job.user_id,
                        robot_id=robot_id,
                        target=command_type,
                        request_payload=params,
                        result_payload={"error": str(exc)},
                        status_value="failed",
                    )
                    await emit_event(db, "command.status", {"id": job.id, "status": "failed"}, robot_id)
                    await db.commit()

    async def auto_stop_collections(self) -> None:
        now = datetime.now(UTC)
        async with SessionLocal() as db:
            collections = list(
                (
                    await db.scalars(
                        select(CollectionSession).where(
                            CollectionSession.status == "recording",
                            CollectionSession.due_at.is_not(None),
                            CollectionSession.due_at <= now,
                        )
                    )
                ).all()
            )
        for snapshot in collections:
            async with SessionLocal() as db:
                collection = await db.get(CollectionSession, snapshot.id)
                robot = await db.get(Robot, snapshot.robot_id)
                if not collection or not robot or not collection.record_uid:
                    continue
                collection.status = "stopping"
                await db.commit()
                try:
                    result = await create_adapter(robot.adapter_type, robot.connection).stop_collection(
                        collection.record_uid
                    )
                    collection.status = "completed"
                    collection.stopped_at = utcnow()
                    await audit(
                        db,
                        action="collection.auto_stop",
                        robot_id=robot.id,
                        target=collection.record_uid,
                        result_payload=result,
                    )
                except Exception as exc:
                    collection.status = "failed"
                    collection.error = str(exc)
                await db.commit()

    async def prune_telemetry(self) -> None:
        cutoff = datetime.now(UTC) - timedelta(days=settings.telemetry_retention_days)
        async with SessionLocal() as db:
            await db.execute(delete(TelemetrySnapshot).where(TelemetrySnapshot.recorded_at < cutoff))
            await db.commit()


async def worker_loop() -> None:
    await create_schema()
    await asyncio.to_thread(settings.data_root.mkdir, parents=True, exist_ok=True)
    worker = Worker()
    while True:
        started = asyncio.get_running_loop().time()
        try:
            await worker.tick()
        except Exception:
            logger.exception("Worker tick failed")
        elapsed = asyncio.get_running_loop().time() - started
        await asyncio.sleep(max(0.5, settings.poll_interval_seconds - elapsed))


def run() -> None:
    asyncio.run(worker_loop())


if __name__ == "__main__":
    run()
