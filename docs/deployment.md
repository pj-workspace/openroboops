# Deployment

The reference deployment runs entirely in containers and does not use a host GPU.
Official base images are referenced through AWS Public ECR's Docker Library mirror,
which avoids a hard dependency on Docker Hub while preserving upstream images.

## Host preparation

Install Docker Engine and Docker Compose v2, then create persistent directories:

```bash
mkdir -p /srv/openroboops/runtime-secrets
mkdir -p /srv/openroboops-data
```

Copy `.env.example` to `.env`, generate a strong database password, and set:

```dotenv
POSTGRES_PASSWORD=replace-with-a-strong-random-value
OPENROBOOPS_DATA_ROOT_HOST=/srv/openroboops-data
OPENROBOOPS_SECRETS_HOST=/srv/openroboops/runtime-secrets
OPENROBOOPS_SITE_ADDRESS=https://openroboops.example.lan
OPENROBOOPS_SITE_HOST=openroboops.example.lan
OPENROBOOPS_HTTP_PORT=8080
OPENROBOOPS_HTTPS_PORT=8443
```

Do not commit `.env` or `runtime-secrets`.

## Start and initialize

```bash
docker compose -f compose.yaml -f compose.production.yaml pull
docker compose -f compose.yaml -f compose.production.yaml up -d
docker compose ps
docker compose logs api | grep "First-run bootstrap token"
```

The production override pulls published API and web images from GitHub Container
Registry, so the deployment host does not compile Python or Node.js applications.
Use `docker compose up --build -d` without the override when building locally.

Use the token once in the web setup page. After the administrator is created, the
token hash is deleted. Do not paste the token into an issue, chat transcript, or
shell history shared with others.

## Internal TLS

Caddy issues an internal certificate. Export and install Caddy's root certificate on
trusted operator devices, or replace `tls internal` with your organization's internal
PKI configuration. Do not expose the reference deployment directly to the public
Internet without an explicit network and identity security review.

## Upgrade and backup

```bash
git pull --ff-only
docker compose -f compose.yaml -f compose.production.yaml pull
docker compose -f compose.yaml -f compose.production.yaml up -d
docker compose exec postgres pg_dump -U openroboops -Fc openroboops > openroboops.dump
```

Alembic upgrades run before the API starts. Back up both PostgreSQL and the configured
episode target directory. Source data on the robot is outside OpenRoboOps backup scope
and is never automatically deleted.

PostgreSQL 18 stores versioned cluster directories below `/var/lib/postgresql`; the
Compose volume intentionally mounts that parent path for safe future `pg_upgrade`
workflows.

## Health and logs

```bash
curl -k https://openroboops.example.lan:8443/api/v1/healthz
docker compose logs -f --tail=200 api worker
docker compose stats
```

The reference services request no GPU and do not mount a Docker socket.
