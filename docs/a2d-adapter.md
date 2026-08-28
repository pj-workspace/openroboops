# A2D Adapter

The A2D adapter connects to a robot through SSH. It never exposes the robot's SSH
credentials or local service ports to the browser.

## Dedicated SSH identity

Create a dedicated deployment key, install only its public half for the least-privilege
robot user, and capture the robot's host key out of band. Mount the private key and
`known_hosts` file read-only below `/run/secrets` in the API and worker containers.

The adapter passes `known_hosts` to AsyncSSH and configures `rsync` with
`StrictHostKeyChecking=yes`. A changed host key therefore makes probes, reads, syncs,
and commands fail instead of silently trusting a new host.

## Connection profile

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

Use a DNS name or address that is private to your deployment. Never publish a real
profile. Inline passwords, tokens, or private-key bodies are rejected by the API.

## Read path

- Status calls create a short-lived SSH tunnel to the collector's loopback HTTP port.
- Service and disk health are read over the same pinned SSH identity.
- Episode discovery scans `<data_root>/*/meta_info.json` through SFTP; it does not depend
  on vendor history endpoints.
- Malformed endpoint fields and unreachable required services make the adapter fail
  closed.

## Collection and sync

OpenRoboOps allocates local task and job IDs, calls the configured collector start
interface, and persists the returned UID. Stop is explicit or driven by the planned
duration. The next worker scan indexes the resulting `meta_info.json`.

Sync uses `rsync -a --partial --append-verify`. After transfer, the adapter generates a
remote SHA-256 tree and a local SHA-256 tree and requires an exact path/hash match. A
failure leaves the source directory unchanged and keeps the partial target for resume.
No upload, discard, or cleanup endpoint is called.

## Current motion boundary

The public A2D adapter deliberately reports `vrActive` as unknown because there is no
portable, verified signal in this repository. Consequently, movement-capable commands
fail preflight. A private deployment must implement and field-accept a trustworthy
idle signal before changing this boundary.
