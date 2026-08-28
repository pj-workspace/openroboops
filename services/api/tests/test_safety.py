from collections.abc import Callable
from datetime import timedelta

import pytest
from fastapi import HTTPException

from openroboops.models import Robot, utcnow
from openroboops.service import validate_command_preflight


def robot_fixture() -> Robot:
    return Robot(
        name="Safety Fixture",
        adapter_type="simulator",
        observe_only=False,
        online=True,
        last_seen=utcnow(),
        capabilities=["reset_arm"],
        enabled_commands=["reset_arm"],
        status={
            "recording": False,
            "vrActive": False,
            "collisionProtection": {"enabled": True},
            "resetPoses": {
                "left": {"available": True},
                "right": {"available": False},
            },
        },
    )


@pytest.mark.parametrize(
    ("mutation", "detail"),
    [
        (lambda robot: setattr(robot, "online", False), "offline"),
        (lambda robot: setattr(robot, "last_seen", utcnow() - timedelta(seconds=20)), "stale"),
        (lambda robot: robot.status.update({"recording": True}), "collection is active"),
        (lambda robot: robot.status.update({"vrActive": None}), "VR activity"),
        (
            lambda robot: robot.status.update({"collisionProtection": {"enabled": False}}),
            "collision protection",
        ),
    ],
)
def test_motion_preflight_fails_closed(mutation: Callable[[Robot], None], detail: str) -> None:
    robot = robot_fixture()
    mutation(robot)
    with pytest.raises(HTTPException, match=detail):
        validate_command_preflight(robot, "reset_arm", {"side": "left"})


def test_arm_reset_requires_that_sides_saved_pose() -> None:
    with pytest.raises(HTTPException, match="right arm has no saved reset pose"):
        validate_command_preflight(robot_fixture(), "reset_arm", {"side": "right"})
