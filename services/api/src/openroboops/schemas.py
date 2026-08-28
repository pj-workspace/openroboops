from __future__ import annotations

from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator


class ApiModel(BaseModel):
    model_config = ConfigDict(from_attributes=True, populate_by_name=True)


class SetupStatus(ApiModel):
    setup_required: bool


class SetupRequest(ApiModel):
    bootstrap_token: str
    username: str = Field(min_length=3, max_length=80, pattern=r"^[a-zA-Z0-9_.-]+$")
    password: str = Field(min_length=12, max_length=256)


class LoginRequest(ApiModel):
    username: str
    password: str


class UserResponse(ApiModel):
    id: str
    username: str


class AuthResponse(ApiModel):
    user: UserResponse
    csrf_token: str


class RobotCreate(ApiModel):
    name: str = Field(min_length=2, max_length=120)
    model: str = Field(default="Unknown", max_length=120)
    adapter_type: Literal["simulator", "a2d"]
    connection: dict[str, Any] = Field(default_factory=dict)
    observe_only: bool = True
    enabled_commands: list[str] = Field(default_factory=list)

    @field_validator("connection")
    @classmethod
    def validate_connection(cls, value: dict[str, Any]) -> dict[str, Any]:
        forbidden = {"password", "private_key", "privateKey", "token"}
        if forbidden.intersection(value):
            raise ValueError("store secret file paths, never inline credentials")
        return value


class RobotPatch(ApiModel):
    name: str | None = Field(default=None, min_length=2, max_length=120)
    model: str | None = Field(default=None, max_length=120)
    connection: dict[str, Any] | None = None
    observe_only: bool | None = None
    enabled_commands: list[str] | None = None


class RobotResponse(ApiModel):
    id: str
    name: str
    model: str
    adapter_type: str
    connection_summary: dict[str, Any] = Field(default_factory=dict)
    capabilities: list[str]
    status: dict[str, Any]
    online: bool
    last_seen: datetime | None
    revision: int
    observe_only: bool
    enabled_commands: list[str]
    created_at: datetime
    updated_at: datetime


class ProbeResponse(ApiModel):
    online: bool
    capabilities: list[str]
    status: dict[str, Any]
    error: str | None = None


class TelemetryResponse(ApiModel):
    id: str
    robot_id: str
    recorded_at: datetime
    payload: dict[str, Any]


class EpisodeResponse(ApiModel):
    id: str
    robot_id: str
    uid: str
    source_path: str
    metadata: dict[str, Any]
    channels: list[str]
    file_size: int
    duration_seconds: float
    aligned: bool
    validation_status: str
    sync_status: str
    last_scanned_at: datetime


class CollectionStartRequest(ApiModel):
    name: str = Field(min_length=2, max_length=180)
    planned_duration_seconds: int | None = Field(default=None, ge=10, le=3600)


class CollectionResponse(ApiModel):
    id: str
    robot_id: str
    name: str
    task_id: int
    job_id: int
    record_uid: str | None
    planned_duration_seconds: int | None
    status: str
    error: str | None
    review_status: str
    reviewed_at: datetime | None
    started_at: datetime
    due_at: datetime | None
    stopped_at: datetime | None


class CollectionDecisionRequest(ApiModel):
    decision: Literal["keep", "delete"]
    password: str | None = Field(default=None, max_length=256)
    confirm_uid: str | None = Field(default=None, max_length=160)


class CameraPreviewResponse(ApiModel):
    channel: str
    label: str
    captured_at: datetime | None
    age_ms: int | None
    size: int | None
    stale: bool
    frame_url: str
    stream_url: str | None


class SyncJobResponse(ApiModel):
    id: str
    robot_id: str
    episode_id: str
    status: str
    progress: int
    target_path: str | None
    manifest: dict[str, Any]
    error: str | None
    created_at: datetime
    started_at: datetime | None
    finished_at: datetime | None


class LeaseRequest(ApiModel):
    password: str
    physical_safety_confirmed: bool


class LeaseResponse(ApiModel):
    id: str
    robot_id: str
    expires_at: datetime


class CommandRequest(ApiModel):
    robot_id: str = Field(alias="robotId")
    type: str = Field(min_length=2, max_length=80)
    params: dict[str, Any] = Field(default_factory=dict)
    idempotency_key: str = Field(alias="idempotencyKey", min_length=8, max_length=120)
    expected_revision: int = Field(alias="expectedRevision", ge=0)
    control_lease_id: str = Field(alias="controlLeaseId")


class CommandResponse(ApiModel):
    id: str
    robot_id: str
    command_type: str
    params: dict[str, Any]
    idempotency_key: str
    expected_revision: int
    status: str
    result: dict[str, Any]
    error: str | None
    created_at: datetime
    started_at: datetime | None
    finished_at: datetime | None


class AuditResponse(ApiModel):
    id: str
    robot_id: str | None
    action: str
    target: str
    request_payload: dict[str, Any]
    result_payload: dict[str, Any]
    status: str
    created_at: datetime
