# OpenRoboOps Architecture

```text
Browser
  │ HTTPS / WebSocket
  ▼
Caddy ──► Next.js console
  │
  └─────► FastAPI control plane ──► PostgreSQL
                       │
                       ├── simulator adapter
                       └── A2D adapter ── SSH tunnel / SFTP / rsync ──► Robot
```

The browser only talks to the control plane. Robot network addresses and SSH
credentials never cross the server/client boundary. Adapters expose capabilities
instead of assuming every robot supports every operation.

The A2D adapter is non-invasive: it reads public runtime interfaces and files
available to the configured SSH user. It does not install or copy vendor code.

## Control plane boundaries

- Next.js only calls the same-origin `/api/v1` surface.
- Caddy terminates internal TLS and proxies HTTP and authenticated WebSocket traffic.
- FastAPI owns authentication, CSRF protection, robot registration, capability discovery,
  revision checks, and audit creation.
- The worker owns polling, telemetry persistence, background sync, automatic collection
  stop, and serialized command execution.
- Only server-side adapters can access robot addresses, SSH files, collector ports, or
  dataset roots.

## Persistence model

PostgreSQL stores `Robot`, `TelemetrySnapshot`, `Episode`, `CollectionSession`,
`SyncJob`, `ControlLease`, `CommandJob`, `AuditLog`, and `Event` records. Telemetry
uses a time-bearing composite primary key so PostgreSQL can partition it monthly.
The worker creates the current and next two monthly partitions, while a default
partition provides a fail-safe for extended outages.

Every robot status update increments that robot's revision. A command request carries
the selected robot ID, idempotency key, expected revision, and control lease ID. This
prevents stale browser state and cross-robot selection errors from silently issuing an
operation.

## Adapter contract

`RobotAdapter` defines `probe`, `read_status`, `list_episodes`,
`start_collection`, `stop_collection`, `execute_command`, and `sync_episode`.
Capabilities are discovered at runtime and intersected with a private deployment
allowlist before any command is accepted.

The simulator is deterministic enough for CI but exercises the same persistence and
queue paths as a physical robot. The A2D adapter pins SSH host keys, tunnels collector
HTTP over SSH, reads episode metadata with SFTP, and runs resumable `rsync` without
deleting its source.
