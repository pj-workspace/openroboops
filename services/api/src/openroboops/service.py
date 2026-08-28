from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any

from fastapi import HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from .adapters.base import AdapterEpisode
from .adapters.registry import create_adapter, summarize_connection
from .models import AuditLog, Episode, Event, Robot, as_utc, utcnow
from .schemas import EpisodeResponse, RobotResponse

MOTION_COMMANDS = {"reset_arm", "reset_robot", "pack_pose", "set_body_params"}


def robot_response(robot: Robot) -> RobotResponse:
    return RobotResponse(
        id=robot.id,
        name=robot.name,
        model=robot.model,
        adapter_type=robot.adapter_type,
        connection_summary=summarize_connection(robot.adapter_type, robot.connection),
        capabilities=robot.capabilities,
        status=robot.status,
        online=robot.online,
        last_seen=robot.last_seen,
        revision=robot.revision,
        observe_only=robot.observe_only,
        enabled_commands=robot.enabled_commands,
        created_at=robot.created_at,
        updated_at=robot.updated_at,
    )


def episode_response(episode: Episode) -> EpisodeResponse:
    return EpisodeResponse(
        id=episode.id,
        robot_id=episode.robot_id,
        uid=episode.uid,
        source_path=episode.source_path,
        metadata=episode.metadata_payload,
        channels=episode.channels,
        file_size=episode.file_size,
        duration_seconds=episode.duration_seconds,
        aligned=episode.aligned,
        validation_status=episode.validation_status,
        sync_status=episode.sync_status,
        last_scanned_at=episode.last_scanned_at,
    )


async def audit(
    db: AsyncSession,
    *,
    action: str,
    user_id: str | None = None,
    robot_id: str | None = None,
    target: str = "",
    request_payload: dict[str, Any] | None = None,
    result_payload: dict[str, Any] | None = None,
    status_value: str = "ok",
) -> None:
    db.add(
        AuditLog(
            user_id=user_id,
            robot_id=robot_id,
            action=action,
            target=target,
            request_payload=request_payload or {},
            result_payload=result_payload or {},
            status=status_value,
        )
    )


async def emit_event(db: AsyncSession, event_type: str, payload: dict[str, Any], robot_id: str | None = None) -> None:
    db.add(Event(robot_id=robot_id, event_type=event_type, payload=payload))


async def scan_robot_episodes(db: AsyncSession, robot: Robot) -> list[Episode]:
    adapter = create_adapter(robot.adapter_type, robot.connection)
    discovered = await adapter.list_episodes()
    existing = {
        episode.uid: episode
        for episode in (await db.scalars(select(Episode).where(Episode.robot_id == robot.id))).all()
    }
    for item in discovered:
        episode = existing.get(item.uid)
        if episode is None:
            episode = Episode(robot_id=robot.id, uid=item.uid, source_path=item.source_path)
            db.add(episode)
            existing[item.uid] = episode
        apply_episode(item, episode)
    await db.flush()
    return sorted(existing.values(), key=lambda episode: episode.created_at, reverse=True)


def apply_episode(source: AdapterEpisode, target: Episode) -> None:
    target.source_path = source.source_path
    target.metadata_payload = source.metadata
    target.channels = source.channels
    target.file_size = source.file_size
    target.duration_seconds = source.duration_seconds
    target.aligned = source.aligned
    target.validation_status = source.validation_status
    target.last_scanned_at = utcnow()


def validate_command_preflight(robot: Robot, command_type: str, params: dict[str, Any]) -> None:
    if robot.observe_only:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="robot is observe-only")
    if command_type not in robot.enabled_commands:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="command is not enabled")
    if command_type not in robot.capabilities:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="adapter lacks capability")
    if not robot.online or robot.last_seen is None:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="robot is offline")
    if as_utc(robot.last_seen) < datetime.now(UTC) - timedelta(seconds=15):
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="robot status is stale")
    status_payload = robot.status or {}
    if status_payload.get("recording"):
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="collection is active")
    collision = status_payload.get("collisionProtection") or {}
    if command_type in MOTION_COMMANDS:
        if not collision.get("enabled"):
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="collision protection must be enabled",
            )
        if status_payload.get("vrActive") is not False:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="VR activity must be positively confirmed idle",
            )
    if command_type == "reset_arm":
        side = str(params.get("side", "")).lower()
        reset_pose = (status_payload.get("resetPoses") or {}).get(side, {})
        if not reset_pose.get("available"):
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail=f"{side or 'selected'} arm has no saved reset pose",
            )
