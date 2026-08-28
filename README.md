# OpenRoboOps

Open-source robot fleet operations console for telemetry, data collection, dataset management, and safety-gated control.

[简体中文](README.zh-CN.md) · [Architecture](docs/architecture.md) · [Safety model](docs/safety.md) · [Deployment](docs/deployment.md)

> [!IMPORTANT]
> OpenRoboOps is not a safety controller or emergency-stop system. Keep the robot's physical safety systems and physical emergency stop available whenever motion is possible.

## What v0.1 delivers

- Register and switch between multiple robots without mixing state.
- Poll live status every five seconds and persist snapshots every thirty seconds or on change.
- Keep robot registration, telemetry, collection sessions, sync jobs, commands, and audit events in PostgreSQL.
- Index datasets directly from `meta_info.json`, including channels, size, duration, alignment, validation, and sync state.
- Start and stop local collection jobs while preserving both local task/job IDs and the collector UID.
- Explicitly sync an episode with resumable `rsync`, then compare source and destination SHA-256 manifests.
- Run a public simulator for development, CI, and product demonstrations.
- Connect to A2D/AGI G1 systems through pinned-host-key SSH, server-side tunnels, SFTP, and `rsync` without copying vendor code.
- Gate preset maintenance commands behind capability discovery, deployment allowlists, password re-authentication, a 60-second exclusive lease, fresh status, and runtime safety checks.

Direct 14-axis target control is intentionally deferred to v0.2.

## Safety defaults

Every newly registered robot starts with `observe_only: true` and an empty command allowlist. The browser never receives SSH credentials or direct access to robot ports.

Motion-capable commands fail closed unless all of these are positively true:

- the command is enabled in the private deployment profile;
- the adapter advertises the capability;
- the robot is online and its status is no more than 15 seconds old;
- no collection job is active;
- collision protection is enabled;
- VR activity is positively confirmed idle;
- the administrator has re-entered their password;
- a 60-second exclusive control lease is active;
- the operator confirms physical presence and a clear work area.

The A2D adapter currently reports VR activity as unknown, so its motion commands remain fail-closed until a deployment supplies and validates a trustworthy VR-idle signal. OpenRoboOps never disables collision protection and does not expose raw WBC/MBC publishing endpoints.

## Architecture

```text
Browser ── HTTPS / WebSocket ── Caddy
                                  ├── Next.js console
                                  └── FastAPI control plane ── PostgreSQL 18
                                               │
                                               ├── background worker
                                               ├── simulator adapter
                                               └── A2D adapter ── SSH/SFTP/rsync ── robot
```

The monorepo contains:

```text
apps/web/                 Next.js App Router management console
services/api/             FastAPI API, worker, adapters, tests, and Alembic
infra/                    Caddy reverse-proxy configuration
docs/                     Architecture, safety, adapter, and deployment guides
compose.yaml              Web, API, worker, PostgreSQL, and Caddy stack
```

The FastAPI OpenAPI document generates `apps/web/src/lib/api-types.ts`; core API types are not manually duplicated in the frontend.

## Quick start with the simulator

Requirements: Docker Engine with Docker Compose v2. The host does not need Node.js or Python.

```bash
cp .env.example .env
# Replace both change-me values with one strong database password.
mkdir -p data runtime-secrets
docker compose up --build -d
docker compose logs api | grep "First-run bootstrap token"
```

Open `https://localhost:8443`. Caddy uses its internal CA, so local clients must explicitly trust that CA or accept the development certificate warning. Use the one-time bootstrap token to create the administrator account; the token is then deleted and cannot be reused.

Useful checks:

```bash
docker compose ps
docker compose logs -f api worker
curl -k https://localhost:8443/api/v1/healthz
```

The seeded simulator can be probed, indexed, collected, synced, and safely commanded without physical hardware.

## Local development

### API

```bash
cd services/api
uv sync --extra dev
uv run pytest
uv run ruff check src tests migrations
uv run ruff format --check src tests migrations
uv run openroboops-api
```

The default development database is SQLite. PostgreSQL is used by the Compose deployment.

### Web

```bash
pnpm install
pnpm --dir apps/web lint
pnpm --dir apps/web typecheck
pnpm --dir apps/web build
pnpm --dir apps/web dev
```

Regenerate frontend API types after changing FastAPI schemas:

```bash
cd services/api
uv run openroboops-export-openapi
cd ../..
pnpm --dir apps/web generate:api
```

## A2D adapter

The A2D adapter is non-invasive. It does not install, modify, or redistribute vendor software. A private deployment provides file paths to a dedicated SSH key and pinned `known_hosts` file:

```json
{
  "host": "robot.example.lan",
  "port": 22,
  "username": "robot-ops",
  "known_hosts_path": "/run/secrets/robot_known_hosts",
  "private_key_path": "/run/secrets/robot_key",
  "data_root": "/data/record",
  "collector_host": "127.0.0.1",
  "collector_port": 8888
}
```

Do not commit real addresses, host keys, private keys, robot identifiers, internal domains, vendor source, or collected data. See [A2D adapter setup](docs/a2d-adapter.md).

## API surface

The authenticated API is under `/api/v1` and includes:

- `/robots` registration, status, connection probes, telemetry, episode scans, and collection sessions;
- `/episodes/{id}/sync` explicit resumable sync jobs;
- `/control-leases` password re-authentication and physical-safety confirmation;
- `/commands` idempotent, revision-checked preset operations;
- `/audit` long-lived operations history;
- `/ws` authenticated `robot.status`, `collection.progress`, `sync.progress`, `command.status`, and `alert` updates.

Interactive OpenAPI documentation is available at `/docs` on the API service in trusted development environments.

## Data retention

- Raw telemetry: 90 days by default.
- Telemetry table: PostgreSQL declarative monthly partitions, created ahead of time.
- Events and operation audits: retained indefinitely by v0.1.
- Source episodes: never automatically deleted.
- Synced episodes: stored below `OPENROBOOPS_DATA_ROOT`; each completed job persists a SHA-256 manifest.

## Roadmap

- **v0.2:** safety-gated 14-axis arm target execution with per-robot soft limits, degree/radian conversion, target review, ≤5° default deltas, 500 ms feedback freshness, convergence checks, and post-failure lockout.
- **v0.3:** A2D data-quality reports, time alignment, versioned cleaning artifacts, and LeRobot conversion while preserving raw datasets as read-only sources.

No real-time drag-to-command sliders, base navigation, or raw WBC topics are planned for v0.2.

## Contributing and security

See [CONTRIBUTING.md](CONTRIBUTING.md), [SECURITY.md](SECURITY.md), and [CODE_OF_CONDUCT.md](CODE_OF_CONDUCT.md). Security reports should not include live robot credentials or collected data in public issues.

## License

Licensed under the [Apache License 2.0](LICENSE).
