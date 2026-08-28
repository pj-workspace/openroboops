from __future__ import annotations

from .a2d import A2DAdapter
from .base import RobotAdapter
from .simulator import SimulatorAdapter

ADAPTERS: dict[str, type[RobotAdapter]] = {
    "simulator": SimulatorAdapter,
    "a2d": A2DAdapter,
}


def create_adapter(adapter_type: str, connection: dict[str, object]) -> RobotAdapter:
    adapter_class = ADAPTERS.get(adapter_type)
    if adapter_class is None:
        raise ValueError(f"unsupported adapter: {adapter_type}")
    return adapter_class(connection)


def summarize_connection(adapter_type: str, connection: dict[str, object]) -> dict[str, object]:
    if adapter_type == "simulator":
        return {"mode": "simulator"}
    return {
        "host": connection.get("host", ""),
        "port": connection.get("port", 22),
        "username": connection.get("username", ""),
        "dataRoot": connection.get("data_root", "/data/record"),
        "hostKeyPinned": bool(connection.get("known_hosts_path")),
        "keyConfigured": bool(connection.get("private_key_path")),
    }
