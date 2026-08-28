from __future__ import annotations

import asyncio
import logging
import secrets
from datetime import UTC, datetime, timedelta
from typing import Annotated

from fastapi import (
    APIRouter,
    Cookie,
    Depends,
    HTTPException,
    Query,
    Response,
    WebSocket,
    WebSocketDisconnect,
    status,
)
from fastapi.responses import StreamingResponse
from sqlalchemy import delete, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from ..adapters.registry import create_adapter
from ..config import get_settings
from ..database import SessionLocal, get_db
from ..models import (
    AuditLog,
    CollectionSession,
    CommandJob,
    ControlLease,
    Episode,
    Event,
    LoginSession,
    Robot,
    RuntimeSetting,
    SyncJob,
    TelemetrySnapshot,
    User,
    as_utc,
    utcnow,
)
from ..schemas import (
    AuditResponse,
    AuthResponse,
    CameraPreviewResponse,
    CollectionDecisionRequest,
    CollectionResponse,
    CollectionStartRequest,
    CommandRequest,
    CommandResponse,
    EpisodeDeleteRequest,
    EpisodeDeleteResponse,
    EpisodeResponse,
    LeaseRequest,
    LeaseResponse,
    LoginRequest,
    ProbeResponse,
    RobotCreate,
    RobotPatch,
    RobotResponse,
    SetupRequest,
    SetupStatus,
    SyncJobResponse,
    TelemetryResponse,
    UserResponse,
)
from ..security import (
    BOOTSTRAP_HASH_KEY,
    SESSION_COOKIE,
    create_login_session,
    get_current_user,
    hash_password,
    hash_secret,
    require_csrf,
    revoke_login_session,
    verify_password,
)
from ..service import (
    audit,
    emit_event,
    episode_response,
    robot_response,
    scan_robot_episodes,
    validate_command_preflight,
)

logger = logging.getLogger(__name__)
router = APIRouter()
DB = Annotated[AsyncSession, Depends(get_db)]
Admin = Annotated[User, Depends(get_current_user)]
MutatingAdmin = Annotated[User, Depends(require_csrf)]


@router.get("/healthz")
async def healthz() -> dict[str, str]:
    return {"status": "ok", "service": "openroboops-api"}


@router.get("/auth/setup-status", response_model=SetupStatus)
async def setup_status(db: DB) -> SetupStatus:
    return SetupStatus(setup_required=(await db.scalar(select(User.id).limit(1))) is None)


@router.post("/auth/setup", response_model=AuthResponse, status_code=status.HTTP_201_CREATED)
async def setup_admin(payload: SetupRequest, response: Response, db: DB) -> AuthResponse:
    if (await db.scalar(select(User.id).limit(1))) is not None:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="setup already completed")
    bootstrap = await db.get(RuntimeSetting, BOOTSTRAP_HASH_KEY)
    if bootstrap is None or not secrets.compare_digest(bootstrap.value, hash_secret(payload.bootstrap_token)):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="invalid bootstrap token")
    user = User(username=payload.username, password_hash=hash_password(payload.password))
    db.add(user)
    await db.delete(bootstrap)
    await audit(db, action="auth.setup", user_id=user.id, target=user.username)
    await db.commit()
    csrf = await create_login_session(db, user, response, get_settings())
    return AuthResponse(user=UserResponse.model_validate(user), csrf_token=csrf)


@router.post("/auth/login", response_model=AuthResponse)
async def login(payload: LoginRequest, response: Response, db: DB) -> AuthResponse:
    user = await db.scalar(select(User).where(User.username == payload.username))
    if user is None or not verify_password(user.password_hash, payload.password):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="invalid credentials")
    csrf = await create_login_session(db, user, response, get_settings())
    await audit(db, action="auth.login", user_id=user.id, target=user.username)
    await db.commit()
    return AuthResponse(user=UserResponse.model_validate(user), csrf_token=csrf)


@router.post("/auth/logout", status_code=status.HTTP_204_NO_CONTENT)
async def logout(
    response: Response,
    db: DB,
    _: MutatingAdmin,
    session_token: str | None = Cookie(default=None, alias=SESSION_COOKIE),
) -> Response:
    await revoke_login_session(db, response, session_token)
    response.status_code = status.HTTP_204_NO_CONTENT
    return response


@router.get("/auth/me", response_model=UserResponse)
async def me(user: Admin) -> UserResponse:
    return UserResponse.model_validate(user)


@router.get("/robots", response_model=list[RobotResponse])
async def list_robots(db: DB, _: Admin) -> list[RobotResponse]:
    robots = (await db.scalars(select(Robot).order_by(Robot.name))).all()
    return [robot_response(robot) for robot in robots]


@router.post("/robots", response_model=RobotResponse, status_code=status.HTTP_201_CREATED)
async def create_robot(payload: RobotCreate, db: DB, user: MutatingAdmin) -> RobotResponse:
    robot = Robot(
        name=payload.name,
        model=payload.model,
        adapter_type=payload.adapter_type,
        connection=payload.connection,
        observe_only=payload.observe_only,
        enabled_commands=payload.enabled_commands,
    )
    db.add(robot)
    await audit(
        db,
        action="robot.create",
        user_id=user.id,
        robot_id=robot.id,
        target=payload.name,
        request_payload={"adapterType": payload.adapter_type, "observeOnly": payload.observe_only},
    )
    try:
        await db.commit()
    except IntegrityError as exc:
        await db.rollback()
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="robot name already exists") from exc
    await db.refresh(robot)
    return robot_response(robot)


@router.get("/robots/{robot_id}", response_model=RobotResponse)
async def get_robot(robot_id: str, db: DB, _: Admin) -> RobotResponse:
    robot = await db.get(Robot, robot_id)
    if robot is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="robot not found")
    return robot_response(robot)


@router.patch("/robots/{robot_id}", response_model=RobotResponse)
async def patch_robot(robot_id: str, payload: RobotPatch, db: DB, user: MutatingAdmin) -> RobotResponse:
    robot = await db.get(Robot, robot_id)
    if robot is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="robot not found")
    for key, value in payload.model_dump(exclude_unset=True).items():
        setattr(robot, key, value)
    await audit(db, action="robot.update", user_id=user.id, robot_id=robot.id, target=robot.name)
    await db.commit()
    await db.refresh(robot)
    return robot_response(robot)


@router.delete("/robots/{robot_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_robot(robot_id: str, db: DB, user: MutatingAdmin) -> Response:
    robot = await db.get(Robot, robot_id)
    if robot is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="robot not found")
    await audit(db, action="robot.unregister", user_id=user.id, robot_id=robot.id, target=robot.name)
    await db.delete(robot)
    await db.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.post("/robots/{robot_id}/probe", response_model=ProbeResponse)
async def probe_robot(robot_id: str, db: DB, user: MutatingAdmin) -> ProbeResponse:
    robot = await db.get(Robot, robot_id)
    if robot is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="robot not found")
    try:
        adapter_status = await create_adapter(robot.adapter_type, robot.connection).probe()
        robot.online = adapter_status.online
        robot.status = adapter_status.payload
        robot.capabilities = adapter_status.capabilities
        robot.last_seen = utcnow() if adapter_status.online else robot.last_seen
        robot.revision += 1
        await audit(db, action="robot.probe", user_id=user.id, robot_id=robot.id, target=robot.name)
        await db.commit()
        return ProbeResponse(
            online=adapter_status.online,
            capabilities=adapter_status.capabilities,
            status=adapter_status.payload,
        )
    except Exception as exc:
        robot.online = False
        robot.revision += 1
        await audit(
            db,
            action="robot.probe",
            user_id=user.id,
            robot_id=robot.id,
            target=robot.name,
            result_payload={"error": str(exc)},
            status_value="failed",
        )
        await db.commit()
        return ProbeResponse(online=False, capabilities=[], status={}, error=str(exc))


@router.get("/robots/{robot_id}/telemetry", response_model=list[TelemetryResponse])
async def telemetry(
    robot_id: str,
    db: DB,
    _: Admin,
    limit: int = Query(default=120, ge=1, le=1000),
) -> list[TelemetrySnapshot]:
    result = await db.scalars(
        select(TelemetrySnapshot)
        .where(TelemetrySnapshot.robot_id == robot_id)
        .order_by(TelemetrySnapshot.recorded_at.desc())
        .limit(limit)
    )
    return list(result.all())


@router.get("/robots/{robot_id}/episodes", response_model=list[EpisodeResponse])
async def list_episodes(
    robot_id: str,
    db: DB,
    _: Admin,
    aligned: bool | None = None,
    validation: str | None = None,
    sync_status: str | None = Query(default=None, alias="syncStatus"),
) -> list[EpisodeResponse]:
    query = select(Episode).where(Episode.robot_id == robot_id)
    if aligned is not None:
        query = query.where(Episode.aligned == aligned)
    if validation:
        query = query.where(Episode.validation_status == validation)
    if sync_status:
        query = query.where(Episode.sync_status == sync_status)
    episodes = (await db.scalars(query.order_by(Episode.created_at.desc()))).all()
    return [episode_response(item) for item in episodes]


@router.post("/robots/{robot_id}/episodes/scan", response_model=list[EpisodeResponse])
async def scan_episodes(robot_id: str, db: DB, user: MutatingAdmin) -> list[EpisodeResponse]:
    robot = await db.get(Robot, robot_id)
    if robot is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="robot not found")
    try:
        episodes = await scan_robot_episodes(db, robot)
        await audit(
            db,
            action="episode.scan",
            user_id=user.id,
            robot_id=robot.id,
            result_payload={"count": len(episodes)},
        )
        await db.commit()
        return [episode_response(item) for item in episodes]
    except Exception as exc:
        await db.rollback()
        raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail=str(exc)) from exc


@router.post("/episodes/{episode_id}/sync", response_model=SyncJobResponse, status_code=202)
async def queue_sync(episode_id: str, db: DB, user: MutatingAdmin) -> SyncJob:
    episode = await db.get(Episode, episode_id)
    if episode is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="episode not found")
    active = await db.scalar(
        select(SyncJob).where(
            SyncJob.episode_id == episode.id,
            SyncJob.status.in_(["queued", "running", "verifying"]),
        )
    )
    if active is not None:
        return active
    job = SyncJob(robot_id=episode.robot_id, episode_id=episode.id)
    episode.sync_status = "queued"
    db.add(job)
    await audit(
        db,
        action="episode.sync.queue",
        user_id=user.id,
        robot_id=episode.robot_id,
        target=episode.uid,
    )
    await db.commit()
    await db.refresh(job)
    return job


@router.get("/episodes/{episode_id}/preview/{channel}", response_class=Response)
async def read_episode_preview(episode_id: str, channel: str, db: DB, _: Admin) -> Response:
    episode = await db.get(Episode, episode_id)
    if episode is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="episode not found")
    robot = await db.get(Robot, episode.robot_id)
    if robot is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="robot not found")
    try:
        frame = await create_adapter(robot.adapter_type, robot.connection).read_episode_preview(episode.uid, channel)
    except (FileNotFoundError, ValueError) as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    except NotImplementedError as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc
    except Exception as exc:
        logger.warning("episode preview failed for %s channel %s: %s", episode.id, channel, exc)
        raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail="episode preview is unavailable") from exc
    return Response(
        content=frame.content,
        media_type=frame.media_type,
        headers={"Cache-Control": "private, max-age=30", "X-Content-Type-Options": "nosniff"},
    )


@router.post("/episodes/{episode_id}/delete", response_model=EpisodeDeleteResponse)
async def delete_episode(
    episode_id: str,
    payload: EpisodeDeleteRequest,
    db: DB,
    user: MutatingAdmin,
) -> EpisodeDeleteResponse:
    episode = await db.get(Episode, episode_id)
    if episode is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="episode not found")
    if payload.confirm_uid != episode.uid:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="confirmation UID does not match")
    if not verify_password(user.password_hash, payload.password):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="administrator password is invalid")
    active_collection = await db.scalar(
        select(CollectionSession.id).where(
            CollectionSession.robot_id == episode.robot_id,
            CollectionSession.record_uid == episode.uid,
            CollectionSession.status.in_({"starting", "recording", "stopping"}),
        )
    )
    if active_collection is not None:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="stop the collection before deleting it")
    active_sync = await db.scalar(
        select(SyncJob.id).where(
            SyncJob.episode_id == episode.id,
            SyncJob.status.in_({"queued", "running", "verifying"}),
        )
    )
    if active_sync is not None:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="cancel the active sync before deleting data")
    if episode.sync_status == "completed":
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="deleting synchronized central copies is not supported yet; robot source data was preserved",
        )
    robot = await db.get(Robot, episode.robot_id)
    if robot is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="robot not found")
    uid = episode.uid
    try:
        result = await create_adapter(robot.adapter_type, robot.connection).discard_episode(uid)
    except Exception as exc:
        await audit(
            db,
            action="episode.delete",
            user_id=user.id,
            robot_id=robot.id,
            target=uid,
            result_payload={"error": str(exc)},
            status_value="failed",
        )
        await db.commit()
        raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail=str(exc)) from exc

    matching_collections = (
        await db.scalars(
            select(CollectionSession).where(
                CollectionSession.robot_id == episode.robot_id,
                CollectionSession.record_uid == uid,
            )
        )
    ).all()
    for collection in matching_collections:
        collection.review_status = "deleted"
        collection.reviewed_at = utcnow()
    await db.delete(episode)
    await audit(
        db,
        action="episode.delete",
        user_id=user.id,
        robot_id=robot.id,
        target=uid,
        request_payload={"confirmed_uid": uid},
        result_payload=result,
    )
    await db.commit()
    return EpisodeDeleteResponse(deleted=True, uid=uid)


@router.get("/sync-jobs", response_model=list[SyncJobResponse])
async def list_sync_jobs(db: DB, _: Admin, robot_id: str | None = None) -> list[SyncJob]:
    query = select(SyncJob)
    if robot_id:
        query = query.where(SyncJob.robot_id == robot_id)
    return list((await db.scalars(query.order_by(SyncJob.created_at.desc()).limit(200))).all())


@router.post("/sync-jobs/{job_id}/cancel", response_model=SyncJobResponse)
async def cancel_sync(job_id: str, db: DB, user: MutatingAdmin) -> SyncJob:
    job = await db.get(SyncJob, job_id)
    if job is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="sync job not found")
    if job.status != "queued":
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="only queued sync jobs can be cancelled safely",
        )
    episode = await db.get(Episode, job.episode_id)
    job.status = "cancelled"
    job.finished_at = utcnow()
    if episode is not None:
        episode.sync_status = "not_synced"
    await audit(
        db,
        action="episode.sync.cancel",
        user_id=user.id,
        robot_id=job.robot_id,
        target=job.id,
    )
    await emit_event(
        db,
        "sync.progress",
        {"id": job.id, "progress": job.progress, "status": "cancelled"},
        job.robot_id,
    )
    await db.commit()
    await db.refresh(job)
    return job


@router.post(
    "/robots/{robot_id}/collections",
    response_model=CollectionResponse,
    status_code=status.HTTP_201_CREATED,
)
async def start_collection(
    robot_id: str, payload: CollectionStartRequest, db: DB, user: MutatingAdmin
) -> CollectionSession:
    robot = await db.get(Robot, robot_id)
    if robot is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="robot not found")
    if robot.observe_only:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="robot is observe-only")
    if "collection" not in robot.capabilities:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="collection unsupported")
    active = await db.scalar(
        select(CollectionSession).where(
            CollectionSession.robot_id == robot_id,
            CollectionSession.status.in_(["starting", "recording", "stopping"]),
        )
    )
    if active is not None:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="collection already active")
    now = datetime.now(UTC)
    task_id = int(now.timestamp())
    job_id = secrets.randbelow(900_000_000) + 100_000_000
    collection = CollectionSession(
        robot_id=robot.id,
        name=payload.name,
        task_id=task_id,
        job_id=job_id,
        planned_duration_seconds=payload.planned_duration_seconds,
        due_at=(now + timedelta(seconds=payload.planned_duration_seconds))
        if payload.planned_duration_seconds
        else None,
    )
    db.add(collection)
    await db.flush()
    try:
        uid = await create_adapter(robot.adapter_type, robot.connection).start_collection(
            name=payload.name, task_id=task_id, job_id=job_id
        )
        collection.record_uid = uid
        collection.status = "recording"
        await audit(
            db,
            action="collection.start",
            user_id=user.id,
            robot_id=robot.id,
            target=uid,
            request_payload=payload.model_dump(),
        )
        await emit_event(db, "collection.progress", {"id": collection.id, "status": "recording"}, robot.id)
        await db.commit()
        await db.refresh(collection)
        return collection
    except Exception as exc:
        collection.status = "failed"
        collection.error = str(exc)
        await db.commit()
        raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail=str(exc)) from exc


@router.get("/robots/{robot_id}/collections", response_model=list[CollectionResponse])
async def list_collections(robot_id: str, db: DB, _: Admin) -> list[CollectionSession]:
    return list(
        (
            await db.scalars(
                select(CollectionSession)
                .where(CollectionSession.robot_id == robot_id)
                .order_by(CollectionSession.started_at.desc())
                .limit(100)
            )
        ).all()
    )


@router.get("/robots/{robot_id}/camera-previews", response_model=list[CameraPreviewResponse])
async def list_camera_previews(robot_id: str, db: DB, _: Admin) -> list[CameraPreviewResponse]:
    robot = await db.get(Robot, robot_id)
    if robot is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="robot not found")
    if not robot.online:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="robot is offline")
    try:
        previews = await create_adapter(robot.adapter_type, robot.connection).list_camera_previews()
    except Exception as exc:
        logger.warning("camera preview metadata failed for robot %s: %s", robot.id, exc)
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail="camera preview metadata is unavailable",
        ) from exc
    return [
        CameraPreviewResponse(
            channel=preview.channel,
            label=preview.label,
            captured_at=datetime.fromtimestamp(preview.captured_at_ms / 1000, tz=UTC)
            if preview.captured_at_ms is not None
            else None,
            age_ms=preview.age_ms,
            size=preview.size,
            stale=preview.age_ms is None or preview.age_ms > 10_000,
            frame_url=f"/api/v1/robots/{robot.id}/camera-previews/{preview.channel}/frame?v={preview.version}",
            stream_url=f"/api/v1/robots/{robot.id}/camera-previews/{preview.channel}/stream"
            if preview.streamable
            else None,
        )
        for preview in previews
    ]


@router.get("/robots/{robot_id}/camera-previews/{channel}/frame", response_class=Response)
async def read_camera_preview(robot_id: str, channel: str, db: DB, _: Admin) -> Response:
    robot = await db.get(Robot, robot_id)
    if robot is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="robot not found")
    if not robot.online:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="robot is offline")
    try:
        frame = await create_adapter(robot.adapter_type, robot.connection).read_camera_preview(channel)
    except (FileNotFoundError, ValueError) as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    except NotImplementedError as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc
    except Exception as exc:
        logger.warning("camera frame failed for robot %s channel %s: %s", robot.id, channel, exc)
        raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail="camera frame is unavailable") from exc
    return Response(
        content=frame.content,
        media_type=frame.media_type,
        headers={
            "Cache-Control": "private, max-age=2",
            "X-Content-Type-Options": "nosniff",
        },
    )


@router.get("/robots/{robot_id}/camera-previews/{channel}/stream")
async def stream_camera_preview(robot_id: str, channel: str, db: DB, _: Admin) -> StreamingResponse:
    robot = await db.get(Robot, robot_id)
    if robot is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="robot not found")
    if not robot.online:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="robot is offline")
    adapter = create_adapter(robot.adapter_type, robot.connection)
    try:
        frames = adapter.camera_preview_stream(channel)
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    except NotImplementedError as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc

    async def multipart_frames():
        try:
            async for frame in frames:
                yield (
                    b"--frame\r\n"
                    + f"Content-Type: {frame.media_type}\r\nContent-Length: {len(frame.content)}\r\n\r\n".encode()
                    + frame.content
                    + b"\r\n"
                )
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            logger.warning("live camera stream failed for robot %s channel %s: %s", robot.id, channel, exc)

    return StreamingResponse(
        multipart_frames(),
        media_type="multipart/x-mixed-replace; boundary=frame",
        headers={
            "Cache-Control": "no-store, private",
            "X-Accel-Buffering": "no",
            "X-Content-Type-Options": "nosniff",
        },
    )


@router.post("/collections/{collection_id}/stop", response_model=CollectionResponse)
async def stop_collection(collection_id: str, db: DB, user: MutatingAdmin) -> CollectionSession:
    collection = await db.get(CollectionSession, collection_id)
    if collection is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="collection not found")
    if collection.status not in {"starting", "recording", "stopping"} or not collection.record_uid:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="collection is not active")
    robot = await db.get(Robot, collection.robot_id)
    if robot is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="robot not found")
    collection.status = "stopping"
    await db.commit()
    try:
        result = await create_adapter(robot.adapter_type, robot.connection).stop_collection(collection.record_uid)
        collection.status = "completed"
        collection.stopped_at = utcnow()
        await audit(
            db,
            action="collection.stop",
            user_id=user.id,
            robot_id=robot.id,
            target=collection.record_uid,
            result_payload=result,
        )
        await emit_event(db, "collection.progress", {"id": collection.id, "status": "completed"}, robot.id)
        await db.commit()
        await db.refresh(collection)
        return collection
    except Exception as exc:
        collection.status = "failed"
        collection.error = str(exc)
        await db.commit()
        raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail=str(exc)) from exc


@router.post("/collections/{collection_id}/force-stop", response_model=CollectionResponse)
async def force_stop_collection(collection_id: str, db: DB, user: MutatingAdmin) -> CollectionSession:
    collection = await db.get(CollectionSession, collection_id)
    if collection is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="collection not found")
    if not collection.record_uid:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="collection has no recorder UID")
    if collection.review_status == "deleted":
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="collection data was deleted")
    robot = await db.get(Robot, collection.robot_id)
    if robot is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="robot not found")
    try:
        result = await create_adapter(robot.adapter_type, robot.connection).force_stop_collection(collection.record_uid)
        collection.status = "stopped"
        collection.stopped_at = utcnow()
        await audit(
            db,
            action="collection.force_stop",
            user_id=user.id,
            robot_id=robot.id,
            target=collection.record_uid,
            result_payload=result,
        )
        await emit_event(db, "collection.progress", {"id": collection.id, "status": "stopped"}, robot.id)
        await db.commit()
        await db.refresh(collection)
        return collection
    except Exception as exc:
        collection.status = "failed"
        collection.error = str(exc)
        await audit(
            db,
            action="collection.force_stop",
            user_id=user.id,
            robot_id=robot.id,
            target=collection.record_uid,
            result_payload={"error": str(exc)},
            status_value="failed",
        )
        await db.commit()
        raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail=str(exc)) from exc


@router.get("/collections/{collection_id}/preview/{channel}", response_class=Response)
async def read_collection_preview(collection_id: str, channel: str, db: DB, _: Admin) -> Response:
    collection = await db.get(CollectionSession, collection_id)
    if collection is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="collection not found")
    if not collection.record_uid or collection.review_status == "deleted":
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="collection preview is unavailable")
    robot = await db.get(Robot, collection.robot_id)
    if robot is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="robot not found")
    try:
        frame = await create_adapter(robot.adapter_type, robot.connection).read_episode_preview(
            collection.record_uid, channel
        )
    except (FileNotFoundError, ValueError) as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    except NotImplementedError as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc
    except Exception as exc:
        logger.warning("collection preview failed for %s channel %s: %s", collection.id, channel, exc)
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail="collection preview is unavailable",
        ) from exc
    return Response(
        content=frame.content,
        media_type=frame.media_type,
        headers={"Cache-Control": "private, max-age=30", "X-Content-Type-Options": "nosniff"},
    )


@router.post("/collections/{collection_id}/decision", response_model=CollectionResponse)
async def decide_collection(
    collection_id: str,
    payload: CollectionDecisionRequest,
    db: DB,
    user: MutatingAdmin,
) -> CollectionSession:
    collection = await db.get(CollectionSession, collection_id)
    if collection is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="collection not found")
    if not collection.record_uid:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="collection has no recorder UID")
    if collection.status in {"starting", "recording", "stopping"}:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="stop the collection before reviewing it")
    robot = await db.get(Robot, collection.robot_id)
    if robot is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="robot not found")

    if payload.decision == "delete":
        if payload.confirm_uid != collection.record_uid:
            raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="confirmation UID does not match")
        if not payload.password or not verify_password(user.password_hash, payload.password):
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="administrator password is invalid")
        try:
            result = await create_adapter(robot.adapter_type, robot.connection).discard_episode(collection.record_uid)
        except Exception as exc:
            await audit(
                db,
                action="collection.delete",
                user_id=user.id,
                robot_id=robot.id,
                target=collection.record_uid,
                result_payload={"error": str(exc)},
                status_value="failed",
            )
            await db.commit()
            raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail=str(exc)) from exc
        episode = await db.scalar(
            select(Episode).where(Episode.robot_id == robot.id, Episode.uid == collection.record_uid)
        )
        if episode is not None:
            await db.delete(episode)
        collection.review_status = "deleted"
        action = "collection.delete"
    else:
        result = {"preserved": True}
        collection.review_status = "kept"
        action = "collection.keep"

    collection.reviewed_at = utcnow()
    await audit(
        db,
        action=action,
        user_id=user.id,
        robot_id=robot.id,
        target=collection.record_uid,
        request_payload={"decision": payload.decision},
        result_payload=result,
    )
    await db.commit()
    await db.refresh(collection)
    return collection


@router.post("/robots/{robot_id}/control-leases", response_model=LeaseResponse)
async def acquire_lease(robot_id: str, payload: LeaseRequest, db: DB, user: MutatingAdmin) -> ControlLease:
    robot = await db.get(Robot, robot_id)
    if robot is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="robot not found")
    if not verify_password(user.password_hash, payload.password):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="password verification failed")
    if not payload.physical_safety_confirmed:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="physical safety confirmation required")
    now = datetime.now(UTC)
    await db.execute(
        delete(ControlLease).where(
            ControlLease.robot_id == robot_id,
            ControlLease.expires_at < now,
        )
    )
    existing = await db.scalar(
        select(ControlLease).where(
            ControlLease.robot_id == robot_id,
            ControlLease.expires_at >= now,
            ControlLease.revoked_at.is_(None),
        )
    )
    if existing is not None:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="robot already has an active control lease")
    lease = ControlLease(
        robot_id=robot_id,
        user_id=user.id,
        physical_safety_confirmed=True,
        expires_at=now + timedelta(seconds=get_settings().control_lease_seconds),
    )
    db.add(lease)
    await audit(db, action="control.lease.acquire", user_id=user.id, robot_id=robot_id)
    await db.commit()
    await db.refresh(lease)
    return lease


@router.post("/commands", response_model=CommandResponse, status_code=202)
async def queue_command(payload: CommandRequest, db: DB, user: MutatingAdmin) -> CommandJob:
    robot = await db.get(Robot, payload.robot_id)
    if robot is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="robot not found")
    if payload.expected_revision != robot.revision:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="robot revision changed; refresh before commanding",
        )
    lease = await db.get(ControlLease, payload.control_lease_id)
    now = datetime.now(UTC)
    if (
        lease is None
        or lease.robot_id != robot.id
        or lease.user_id != user.id
        or as_utc(lease.expires_at) < now
        or lease.revoked_at is not None
        or not lease.physical_safety_confirmed
    ):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="invalid or expired control lease")
    validate_command_preflight(robot, payload.type, payload.params)
    existing = await db.scalar(
        select(CommandJob).where(
            CommandJob.robot_id == robot.id,
            CommandJob.idempotency_key == payload.idempotency_key,
        )
    )
    if existing is not None:
        return existing
    active = await db.scalar(
        select(CommandJob).where(
            CommandJob.robot_id == robot.id,
            CommandJob.status.in_(["queued", "running"]),
        )
    )
    if active is not None:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="another command is active")
    job = CommandJob(
        robot_id=robot.id,
        user_id=user.id,
        lease_id=lease.id,
        command_type=payload.type,
        params=payload.params,
        idempotency_key=payload.idempotency_key,
        expected_revision=payload.expected_revision,
    )
    db.add(job)
    await audit(
        db,
        action="command.queue",
        user_id=user.id,
        robot_id=robot.id,
        target=payload.type,
        request_payload=payload.model_dump(by_alias=True),
    )
    await emit_event(db, "command.status", {"id": job.id, "status": "queued"}, robot.id)
    await db.commit()
    await db.refresh(job)
    return job


@router.get("/commands", response_model=list[CommandResponse])
async def list_commands(db: DB, _: Admin, robot_id: str | None = None) -> list[CommandJob]:
    query = select(CommandJob)
    if robot_id:
        query = query.where(CommandJob.robot_id == robot_id)
    return list((await db.scalars(query.order_by(CommandJob.created_at.desc()).limit(200))).all())


@router.get("/audit", response_model=list[AuditResponse])
async def list_audit(db: DB, _: Admin, robot_id: str | None = None) -> list[AuditLog]:
    query = select(AuditLog)
    if robot_id:
        query = query.where(AuditLog.robot_id == robot_id)
    return list((await db.scalars(query.order_by(AuditLog.created_at.desc()).limit(300))).all())


@router.websocket("/ws")
async def websocket_status(websocket: WebSocket) -> None:
    session_token = websocket.cookies.get(SESSION_COOKIE)
    if not session_token:
        await websocket.close(code=4401)
        return
    async with SessionLocal() as db:
        login_session = await db.scalar(
            select(LoginSession).where(LoginSession.token_hash == hash_secret(session_token))
        )
        if login_session is None or as_utc(login_session.expires_at) < datetime.now(UTC):
            await websocket.close(code=4401)
            return
    await websocket.accept()
    last_event_id = 0
    try:
        while True:
            async with SessionLocal() as db:
                robots = (await db.scalars(select(Robot).order_by(Robot.name))).all()
                events = (
                    await db.scalars(select(Event).where(Event.id > last_event_id).order_by(Event.id).limit(100))
                ).all()
                if events:
                    last_event_id = events[-1].id
            await websocket.send_json(
                {
                    "type": "robot.snapshot",
                    "robots": [robot_response(robot).model_dump(mode="json") for robot in robots],
                    "events": [
                        {
                            "id": event.id,
                            "robotId": event.robot_id,
                            "type": event.event_type,
                            "payload": event.payload,
                            "createdAt": event.created_at.isoformat(),
                        }
                        for event in events
                    ],
                }
            )
            await asyncio.sleep(2)
    except WebSocketDisconnect:
        return
