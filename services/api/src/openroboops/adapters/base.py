from __future__ import annotations

from abc import ABC, abstractmethod
from collections.abc import Awaitable, Callable
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

    @abstractmethod
    async def sync_episode(
        self,
        *,
        uid: str,
        target_path: str,
        progress: ProgressCallback,
    ) -> dict[str, Any]: ...
