import pytest

from openroboops.adapters.simulator import SimulatorAdapter


@pytest.mark.asyncio
async def test_simulator_exposes_safe_demo_capabilities() -> None:
    adapter = SimulatorAdapter({"seed": "test"})
    status = await adapter.read_status()

    assert status.online is True
    assert status.payload["collisionProtection"]["enabled"] is True
    assert status.payload["vrActive"] is False
    assert "collection" in status.capabilities


@pytest.mark.asyncio
async def test_simulator_lists_generic_episodes() -> None:
    episodes = await SimulatorAdapter({}).list_episodes()

    assert len(episodes) == 3
    assert all(episode.uid.startswith("demo-episode-") for episode in episodes)
    assert episodes[0].metadata["camera_list"] == ["head", "left_hand", "right_hand"]
