import asyncio

from fastapi.testclient import TestClient
from sqlalchemy import select

from openroboops.database import SessionLocal
from openroboops.main import app
from openroboops.models import User
from openroboops.security import hash_password


async def seed_admin() -> None:
    async with SessionLocal() as db:
        if await db.scalar(select(User.id).limit(1)) is None:
            db.add(User(username="admin", password_hash=hash_password("correct-horse-battery")))
            await db.commit()


def login(client: TestClient) -> str:
    response = client.post(
        "/api/v1/auth/login",
        json={"username": "admin", "password": "correct-horse-battery"},
    )
    assert response.status_code == 200
    return response.json()["csrf_token"]


def test_simulator_end_to_end() -> None:
    with TestClient(app) as client:
        asyncio.run(seed_admin())
        csrf = login(client)
        headers = {"X-CSRF-Token": csrf}

        robots_response = client.get("/api/v1/robots")
        assert robots_response.status_code == 200
        robot = robots_response.json()[0]
        robot_id = robot["id"]

        probe = client.post(f"/api/v1/robots/{robot_id}/probe", headers=headers)
        assert probe.status_code == 200
        assert probe.json()["online"] is True

        scan = client.post(f"/api/v1/robots/{robot_id}/episodes/scan", headers=headers)
        assert scan.status_code == 200
        assert len(scan.json()) == 3

        collection = client.post(
            f"/api/v1/robots/{robot_id}/collections",
            headers=headers,
            json={"name": "Pick demo cube", "planned_duration_seconds": 30},
        )
        assert collection.status_code == 201
        assert collection.json()["status"] == "recording"

        stopped = client.post(
            f"/api/v1/collections/{collection.json()['id']}/stop",
            headers=headers,
        )
        assert stopped.status_code == 200
        assert stopped.json()["status"] == "completed"

        episode_id = scan.json()[0]["id"]
        sync = client.post(f"/api/v1/episodes/{episode_id}/sync", headers=headers)
        assert sync.status_code == 202
        assert sync.json()["status"] == "queued"

        cancelled = client.post(
            f"/api/v1/sync-jobs/{sync.json()['id']}/cancel",
            headers=headers,
        )
        assert cancelled.status_code == 200
        assert cancelled.json()["status"] == "cancelled"

        lease = client.post(
            f"/api/v1/robots/{robot_id}/control-leases",
            headers=headers,
            json={
                "password": "correct-horse-battery",
                "physical_safety_confirmed": True,
            },
        )
        assert lease.status_code == 200

        refreshed_robot = client.get(f"/api/v1/robots/{robot_id}").json()
        command = client.post(
            "/api/v1/commands",
            headers=headers,
            json={
                "robotId": robot_id,
                "type": "reset_arm",
                "params": {"side": "left"},
                "idempotencyKey": "test-reset-left-0001",
                "expectedRevision": refreshed_robot["revision"],
                "controlLeaseId": lease.json()["id"],
            },
        )
        assert command.status_code == 202
        assert command.json()["status"] == "queued"

        second = client.post(
            "/api/v1/robots",
            headers=headers,
            json={
                "name": "Second Simulator",
                "model": "Simulation Fixture",
                "adapter_type": "simulator",
                "connection": {"seed": "second"},
                "observe_only": True,
                "enabled_commands": [],
            },
        )
        assert second.status_code == 201
        second_id = second.json()["id"]
        assert second_id != robot_id
        assert client.post(f"/api/v1/robots/{second_id}/probe", headers=headers).status_code == 200
        first_again = client.get(f"/api/v1/robots/{robot_id}").json()
        second_again = client.get(f"/api/v1/robots/{second_id}").json()
        assert first_again["id"] == robot_id
        assert second_again["id"] == second_id
        assert first_again["name"] != second_again["name"]

    with TestClient(app) as restarted_client:
        login(restarted_client)
        persisted = restarted_client.get("/api/v1/robots")
        assert persisted.status_code == 200
        assert {item["name"] for item in persisted.json()} >= {
            "Demo Manipulator",
            "Second Simulator",
        }
