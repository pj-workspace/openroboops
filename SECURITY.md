# Security Policy

OpenRoboOps can issue commands to physical robots. Treat every deployment as
safety-critical infrastructure.

## Reporting a vulnerability

Do not open a public issue for credential exposure, command authorization bugs,
host-key bypasses, or control-path vulnerabilities. Use GitHub private security
advisories for this repository.

## Deployment baseline

- Keep the console on a trusted LAN or VPN; do not expose it directly to the internet.
- Pin SSH host keys and use dedicated key files mounted as secrets.
- Keep `observeOnly` enabled until each mutating capability is physically accepted.
- Keep a verified physical emergency stop available during every motion test.
- Never store robot addresses, credentials, serial numbers, or real episode data in git.
