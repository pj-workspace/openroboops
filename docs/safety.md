# Command Safety Model

Mutating commands are disabled by default. Enabling a command in a private
deployment does not bypass runtime preflight checks.

Motion-capable commands require an unexpired 60-second control lease, password
re-authentication, physical-safety acknowledgement, a fresh online status,
collision protection, no active collection, and no active VR input. Commands are
serialized per robot and recorded in the audit log.

OpenRoboOps never labels a software action as an emergency stop. Physical safety
systems remain authoritative.

## Fail-closed conditions

The API rejects a motion-capable command when any required signal is missing,
malformed, stale, or negative. This includes an offline robot, changed SSH host key,
collector timeout, unknown VR activity, active recording, disabled collision
protection, missing saved arm pose, stale revision, expired lease, or an unsupported
capability.

The worker repeats the preflight check immediately before adapter execution. This is
deliberate: queuing a command does not preserve a safety decision if the robot state
changes before the worker receives it.

## Deployment command profile

New robots are observe-only. Commands require both adapter capability discovery and an
explicit `enabled_commands` entry in the private database. Recommended initial A2D
allowlist after read-only acceptance:

```text
clear_fault
restart_stack
save_reset_pose
reset_arm       # only for an arm that already has a saved pose
```

`reset_robot`, `pack_pose`, body-motion parameters, and collision-protection level
changes should remain disabled until separately accepted on site. Disabling collision
protection is prohibited in every profile.

## Field acceptance

Never perform a real movement test alone. The operator should inspect the current
pose, clear the workspace, confirm the physical emergency stop, choose one arm, and
run one small preset operation. Stop acceptance immediately after any unexpected
sound, movement, latency, status loss, or command timeout.
