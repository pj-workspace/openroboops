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
  "collector_port": 8888,
  "camera_bus_locator_ip": "192.0.2.10",
  "camera_bus_discovery_uri": "http://192.0.2.10:2379"
}
```

Use a DNS name or address that is private to your deployment. Never publish a real
profile. Inline passwords, tokens, or private-key bodies are rejected by the API.
The camera bus fields are deployment-specific Aorta/Cosine discovery settings. The
example uses an RFC 5737 documentation-only address and will not connect to a robot.

## Read path

- Status calls create a short-lived SSH tunnel to the collector's loopback HTTP port.
- Live head and hand previews subscribe to the vendor camera bus read-only, then proxy
  its existing JPEG packets at up to 15 FPS. The browser never connects to that bus.
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

## PICO/VR activity boundary

The A2D adapter performs a bounded, read-only SSH check of `pico_streamer`, its UDP
listener, and a short CPU-tick delta. Positive process activity sets `vrActive=true`.
Every absent, unreadable, or inconclusive result sets `vrActive=null`, so this detector
can block movement but can never authorize it. The adapter deliberately avoids polling
rosbridge because some vendor builds do not reclaim short-lived WebSocket connections.
The browser never receives robot ports or SSH material.
