from __future__ import annotations

from abc import ABC, abstractmethod
from collections.abc import AsyncIterator, Awaitable, Callable
from dataclasses import dataclass, field
from typing import Any

ProgressCallback = Callable[[int], Awaitable[None]]


@dataclass(slots=True)
class AdapterStatus:
    online: bool
    payload: dict[str, Any]
    capabilities: list[str] = field(default_factory=list)


@dataclass(slots=True)
class AdapterEpisode:
    uid: str
    source_path: str
    metadata: dict[str, Any]
    channels: list[str]
    file_size: int
    duration_seconds: float
    aligned: bool
    validation_status: str


@dataclass(slots=True)
class AdapterCameraPreview:
    channel: str
    label: str
    captured_at_ms: int | None
    age_ms: int | None
    size: int | None
    version: str
    streamable: bool = False


@dataclass(slots=True)
class AdapterCameraFrame:
    content: bytes
    media_type: str


class RobotAdapter(ABC):
    def __init__(self, connection: dict[str, Any]) -> None:
        self.connection = connection

    @abstractmethod
    async def probe(self) -> AdapterStatus: ...

    @abstractmethod
    async def read_status(self) -> AdapterStatus: ...

    @abstractmethod
    async def list_episodes(self) -> list[AdapterEpisode]: ...

    @abstractmethod
    async def start_collection(self, *, name: str, task_id: int, job_id: int) -> str: ...

    @abstractmethod
    async def stop_collection(self, record_uid: str) -> dict[str, Any]: ...

    @abstractmethod
    async def execute_command(self, command_type: str, params: dict[str, Any]) -> dict[str, Any]: ...

    async def list_camera_previews(self) -> list[AdapterCameraPreview]:
        return []

    async def read_camera_preview(self, channel: str) -> AdapterCameraFrame:
        raise NotImplementedError("camera preview unsupported")

    async def read_episode_preview(self, uid: str, channel: str) -> AdapterCameraFrame:
        raise NotImplementedError("episode preview unsupported")

    async def force_stop_collection(self, record_uid: str) -> dict[str, Any]:
        return await self.stop_collection(record_uid)

    async def read_collection_activity(self, record_uid: str) -> bool | None:
        return None

    async def discard_episode(self, uid: str) -> dict[str, Any]:
        raise NotImplementedError("episode discard unsupported")

    def camera_preview_stream(self, channel: str) -> AsyncIterator[AdapterCameraFrame]:
        raise NotImplementedError("live camera preview unsupported")

    @abstractmethod
    async def sync_episode(
        self,
        *,
        uid: str,
        target_path: str,
        progress: ProgressCallback,
    ) -> dict[str, Any]: ...
