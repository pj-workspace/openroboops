from __future__ import annotations

import asyncio
import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

import uvicorn
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy import select

from .api import router
from .config import get_settings
from .database import SessionLocal, create_schema
from .models import Robot
from .security import ensure_bootstrap_token

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s %(message)s",
)
logger = logging.getLogger("openroboops")
settings = get_settings()


@asynccontextmanager
async def lifespan(_: FastAPI) -> AsyncIterator[None]:
    await create_schema()
    await asyncio.to_thread(settings.data_root.mkdir, parents=True, exist_ok=True)
    async with SessionLocal() as db:
        bootstrap_token = await ensure_bootstrap_token(db)
        if bootstrap_token:
            logger.warning("First-run bootstrap token: %s", bootstrap_token)
        if settings.seed_simulator and not await db.scalar(select(Robot.id).limit(1)):
            db.add(
                Robot(
                    name="Demo Manipulator",
                    model="OpenRoboOps Simulator",
                    adapter_type="simulator",
                    connection={"seed": "public-demo"},
                    observe_only=False,
                    enabled_commands=[
                        "save_reset_pose",
                        "reset_arm",
                        "clear_fault",
                        "restart_stack",
                        "set_body_params",
                        "set_collision_protect",
                        "reset_robot",
                        "pack_pose",
                    ],
                )
            )
            await db.commit()
    yield


app = FastAPI(
    title="OpenRoboOps API",
    version="0.1.0",
    description="Robot fleet telemetry, collection, data, and safety-gated operations.",
    lifespan=lifespan,
)
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.allowed_origins,
    allow_credentials=True,
    allow_methods=["GET", "POST", "PATCH", "DELETE", "PUT"],
    allow_headers=["Content-Type", "X-CSRF-Token"],
)
app.include_router(router, prefix=settings.api_prefix)


def run() -> None:
    uvicorn.run("openroboops.main:app", host="0.0.0.0", port=8000, reload=False)


if __name__ == "__main__":
    run()
