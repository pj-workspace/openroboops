# OpenRoboOps

用于机器人遥测、数据采集、数据集管理和安全门控控制的开源机器人集群运维控制台。

[English](README.md) · [架构](docs/architecture.md) · [安全模型](docs/safety.md) · [部署](docs/deployment.md)

> [!IMPORTANT]
> OpenRoboOps 不是安全控制器，也不是真实急停系统。任何可能产生运动的现场操作，都必须保留机器人原有物理安全系统，并确保物理急停可用。

## v0.1 已实现能力

- 手动注册多台机器人并快速切换，所有状态按机器人 ID 严格隔离。
- 每 5 秒轮询一次实时状态；每 30 秒或状态发生变化时保存快照。
- 使用 PostgreSQL 持久化机器人、遥测、采集任务、同步任务、命令和审计事件。
- 直接扫描磁盘中的 `meta_info.json`，展示相机通道、大小、持续时间、时间对齐、校验结果和同步状态。
- 创建、停止本地采集任务，同时保存本地 task/job ID 和采集端返回的 UID。
- 用户显式触发 `rsync` 断点续传；完成后对比源端和目标端 SHA-256 manifest。
- 内置 simulator adapter，可用于公开演示、CI 和无实机开发。
- A2D/AGI G1 通过固定 SSH host key、服务端 SSH 隧道、SFTP 和 `rsync` 接入，不复制或修改厂商代码。
- 预设运维命令同时受 adapter capability、私有部署 allowlist、密码复验、60 秒独占 control lease、状态时效和安全前置条件保护。

直接设定 14 轴目标角度的能力明确放入 v0.2，不在 v0.1 开放。

## 默认安全策略

每台新注册机器人默认 `observe_only: true`，命令 allowlist 为空。浏览器不会获得 SSH 凭证，也不能直接访问机器人端口。

运动相关命令只有在以下条件全部被明确确认后才允许进入队列：

- 私有部署配置已经逐项启用该命令；
- adapter 已发现并声明该 capability；
- 机器人在线，且状态采样时间不超过 15 秒；
- 当前没有正在执行的采集任务；
- 碰撞保护明确处于开启状态；
- VR 输入明确处于空闲状态；
- 管理员重新输入密码；
- 已取得 60 秒独占 control lease；
- 操作者确认本人在现场、工作区域已清空、物理急停触手可及。

A2D adapter 当前将 VR 活跃状态建模为“未知”，因此真实运动命令会 fail closed。只有私有部署接入并验收可靠的 VR-idle 信号后，才具备进一步开放的前提。OpenRoboOps 永远不会关闭碰撞保护，也不暴露原始 WBC/MBC 发布接口。

## 系统架构

```text
浏览器 ── HTTPS / WebSocket ── Caddy
                                  ├── Next.js 管理端
                                  └── FastAPI 控制平面 ── PostgreSQL 18
                                               │
                                               ├── 后台 worker
                                               ├── simulator adapter
                                               └── A2D adapter ── SSH/SFTP/rsync ── 机器人
```

Monorepo 目录：

```text
apps/web/                 Next.js App Router 管理界面
services/api/             FastAPI、worker、adapter、测试与 Alembic
infra/                    Caddy 反向代理配置
docs/                     架构、安全、adapter 和部署文档
compose.yaml              Web、API、worker、PostgreSQL、Caddy
```

FastAPI OpenAPI 会生成 `apps/web/src/lib/api-types.ts`，核心接口类型不在前后端重复维护。

## 使用 simulator 快速启动

只需安装 Docker Engine 和 Docker Compose v2；宿主机不需要安装 Node.js 或 Python。

```bash
cp .env.example .env
# 将两个 change-me 替换为同一个高强度数据库密码。
mkdir -p data runtime-secrets
docker compose up --build -d
docker compose logs api | grep "First-run bootstrap token"
```

打开 `https://localhost:8443`。Caddy 使用内部 CA，因此本地客户端需要信任该 CA，或仅在开发环境接受证书提示。使用 API 容器输出的一次性 bootstrap token 创建管理员；设置成功后 token 会从数据库中删除，无法再次使用。

常用检查：

```bash
docker compose ps
docker compose logs -f api worker
curl -k https://localhost:8443/api/v1/healthz
```

默认 simulator 支持连接检测、数据索引、采集、同步和无实机运维命令验证。

生产主机可以增加 `-f compose.production.yaml`，直接从 GHCR 拉取应用镜像，
无需在主机上构建 Python 或 Node.js 项目。

## 本地开发

### API

```bash
cd services/api
uv sync --extra dev
uv run pytest
uv run ruff check src tests migrations
uv run ruff format --check src tests migrations
uv run openroboops-api
```

开发默认使用 SQLite；Docker Compose 部署使用 PostgreSQL。

### Web

```bash
pnpm install
pnpm --dir apps/web lint
pnpm --dir apps/web typecheck
pnpm --dir apps/web build
pnpm --dir apps/web dev
```

FastAPI schema 变化后重新生成前端类型：

```bash
cd services/api
uv run openroboops-export-openapi
cd ../..
pnpm --dir apps/web generate:api
```

## A2D adapter

A2D adapter 不安装、不修改、也不重新分发厂商软件。私有部署仅向服务端提供专用 SSH key 和固定 `known_hosts` 的文件路径：

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

不要提交真实 IP、host key、private key、机器人标识、内部域名、厂商源码或真实采集数据。完整配置说明见 [A2D adapter 文档](docs/a2d-adapter.md)。

## API 范围

鉴权 API 位于 `/api/v1`：

- `/robots`：机器人注册、状态、连接检测、遥测、数据扫描和采集任务；
- `/episodes/{id}/sync`：显式创建可续传同步任务；
- `/control-leases`：管理员密码复验与现场安全确认；
- `/commands`：带幂等键和 revision 检查的预设运维命令；
- `/audit`：长期操作审计；
- `/ws`：鉴权后的 `robot.status`、`collection.progress`、`sync.progress`、`command.status` 和 `alert` 推送。

在受信任开发环境中，可通过 API 服务的 `/docs` 查看 OpenAPI 交互文档。

## 数据保留

- 原始遥测默认保留 90 天。
- 遥测表使用 PostgreSQL declarative monthly partitioning，并提前创建分区。
- 事件和操作审计在 v0.1 长期保留。
- 机器人源端 episode 永不自动删除。
- 同步数据保存在 `OPENROBOOPS_DATA_ROOT`，每个成功任务都会持久化 SHA-256 manifest。

## 路线图

- **v0.2：** 安全门控的 14 轴目标控制；真实软限位、度/弧度转换、目标预览、默认单次不超过 5°、500ms 状态新鲜度、收敛判断及失败锁定。
- **v0.3：** A2D 数据质量报告、时间对齐、版本化清洗产物和 LeRobot 转换；原始数据始终只读保留。

v0.2 不做拖动即下发的实时滑杆，不开放底盘导航，也不开放原始 WBC topic。

## 参与贡献与安全报告

请阅读 [CONTRIBUTING.md](CONTRIBUTING.md)、[SECURITY.md](SECURITY.md) 和 [CODE_OF_CONDUCT.md](CODE_OF_CONDUCT.md)。公开 Issue 中不得包含真实机器人凭证或采集数据。

## 许可证

本项目使用 [Apache License 2.0](LICENSE)。
