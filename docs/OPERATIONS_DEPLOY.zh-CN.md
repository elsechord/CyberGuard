# 控制台部署、升级与恢复

[English](OPERATIONS_DEPLOY.md) · [中文文档导航](README.zh-CN.md)

新主机需要完整调查能力时，请按[原生安装指南](NATIVE_INSTALL.md)部署模型与 AgentTeams。单独启动 Console 不会自动创建 Worker。之后每次 Compose 升级都要保留生成的私有 `console.override.json`，否则后端连接参数可能丢失。

多用户控制台位于 `services/operations-console`，主 Compose 将其映射到本机 `127.0.0.1:18120`，健康检查为 `/healthz`。数据库位于持久卷内的 `/data/console.db`。账户、权限与页面操作见[控制台使用说明](OPERATIONS_CONSOLE.zh-CN.md)。

## 主机准备

- 基准环境：Ubuntu 22.04/24.04 x86_64、8 核 CPU、16 GB 内存、100 GB SSD、Docker Engine 与 Compose 插件。Python 哈希锁文件面向 Linux x86_64。
- 根据材料、报告和任务事件的保留量规划磁盘。Console 经内部网络连接网关、执行器及已配置的 AgentTeams；模型处理另有资源与数据流向要求。
- 18120 仅监听 loopback。远程访问使用受控 HTTPS 入口、SSH 隧道或私有 VPN，不要直接开放原始端口。

## 首次启动

1. 运行 `python3 deploy/init_secrets.py`，生成权限为 0600 的 `.env`，已有文件不会被覆盖。Console 引用网关与审批凭据，自己维护用户、会话和 API Key 数据库。仅在网关单独签发 Console token 时填写 `CYBERGUARD_GATEWAY_TOKEN`；未启用预算服务时留空 `CYBERGUARD_GUARD_*`。
2. 运行 `docker compose up -d --build`。镜像使用固定基础镜像、uid 10003、只读根文件系统。用 `docker compose ps operations-console` 和 `curl -fsS http://127.0.0.1:18120/healthz` 检查健康。
3. 运行 `docker compose logs operations-console` 获取一次性 setup token，打开 `/setup` 创建首个管理员。完成后再分配成员账户。HTTPS 使用默认 `CYBERGUARD_COOKIE_SECURE=true`；隔离本机 HTTP 测试需设置 false 并重建容器。原生配置器会为 loopback HTTP 自动生成这一设置。

## 连接外部 Agent

登录后打开「连接 Agent」(`/connect`)。远程部署在 `.env` 或私有覆盖文件设置 `CYBERGUARD_CONSOLE_ORIGIN=https://your-console.example` 并重建 Console。该值应是 Agent 可访问的完整 origin，不含路径、查询参数或凭据；它也参与 CSRF 检查，必须与浏览器公开入口一致。设置它本身不会把服务发布到公网。

本机可以推导 loopback 地址。远程连接提示词不会信任任意 Host / forwarded-host 请求头。注意 `localhost` 指向 Agent 所在机器，不一定是操作者浏览器所在机器。

页面生成 Skill v0.2.0 的无密钥提示词。默认调查用途可由管理员签发有效期 30 天的 `investigations:read` + `investigations:write` 凭据；旧事件只读用途仅签发 `incidents:read`。成员通过组织认可渠道取得所需权限。把秘密保存到 Agent 主机私有文件：Unix 目录 0700、文件 0600，Windows 限制 ACL。客户端请求时读取该文件，它不是隔离宿主 Agent 的安全边界。

调查连接检查为 `check --investigations`，安装与检查不会自动上传材料。只读路径使用 `check`、`fetch`；空列表表示暂无事件，不是认证失败。浏览器不能自动检测 Agent 本机安装是否完成。

调查任务按创建用户／API Key 隔离，同一部署的管理员会话可以查看全部任务。旧事件只读权限仍覆盖部署内所有事件；当前部署不等于多租户托管平台。

按照[原生任务服务](AGENTTEAMS_TASK_SERVICE.md)配置 Controller、Leader 与 Matrix。`/investigations` 可提交单份文本或多源 JSON；材料格式与权限见[调查任务](INVESTIGATION_TASKS.md)。SQLite 队列与阶段状态在调用方断线后保留。取消原生任务会暂停 Project，不保证立即终止已经开始的远程推理。Leader 规划、委派、验收 Task，Console 读取状态和最终文件；调查本身不会自动创建处置动作。

## 升级

```bash
git pull --rebase
python3 deploy/validate_config.py --cyberguard-env .env
docker compose build operations-console
docker compose up -d operations-console
curl -fsS http://127.0.0.1:18120/healthz
```

原生安装使用私有覆盖文件时，上述 Compose 命令应始终带上 `-f compose.yaml -f "$CG_PRIVATE/console.override.json"`。数据库迁移在启动时执行且幂等。升级前备份；回退时使用旧镜像和保留的数据卷，先核对版本与数据库兼容性。

## 备份

完整 Console 恢复需要数据库卷、`.env` 和私有覆盖配置。数据库包括调查材料、阶段状态及报告。AgentTeams Controller / Worker 状态、模型与 Matrix 凭据应独立保护，不能只从 Console 数据库还原。

Compose 会给卷名加项目名前缀，因此先从当前容器读取真实卷名，不要猜测：

```bash
CG_CONSOLE_CONTAINER=$(docker compose ps -q operations-console)
CG_CONSOLE_VOLUME=$(docker inspect "$CG_CONSOLE_CONTAINER" --format '{{range .Mounts}}{{if eq .Destination "/data"}}{{.Name}}{{end}}{{end}}')
test -n "$CG_CONSOLE_VOLUME"
docker run --rm -v "$CG_CONSOLE_VOLUME":/data:ro -v "$PWD":/out \
  python:3.12-slim \
  python /out/scripts/console-export.py --db /data/console.db \
  --out /out/console-export.tar.gz --env /out/.env --organization cyberguard
```

导出脚本使用 SQLite `VACUUM INTO` 创建一致性快照，不直接复制运行中的数据库。脚本只依赖标准库，可使用带 sqlite3 的 CPython 3.12 镜像。归档只记录环境变量名称，不包含秘密值。

## 恢复演练

1. 在目标主机获取相同或兼容的新版本，恢复私有配置与 `.env`；也可重新生成基础秘密，再补部署者配置。
2. 停止写入：`docker compose stop operations-console`。
3. 验证归档：`python scripts/console-export.py --verify console-export.tar.gz`，检查 manifest 中每个 SHA256。
4. 新主机先用 `docker compose create operations-console` 创建服务与卷，再用下面方式获取实际目标卷，恢复数据库并设置权限：

```bash
CG_CONSOLE_CONTAINER=$(docker compose ps -aq operations-console)
CG_CONSOLE_VOLUME=$(docker inspect "$CG_CONSOLE_CONTAINER" --format '{{range .Mounts}}{{if eq .Destination "/data"}}{{.Name}}{{end}}{{end}}')
test -n "$CG_CONSOLE_VOLUME"
docker run --rm -i -v "$CG_CONSOLE_VOLUME":/data -v "$PWD":/out \
  python:3.12-slim python - <<'PY'
import sqlite3, tarfile
with tarfile.open("/out/console-export.tar.gz") as tar:
    member = tar.getmember("console.db")
    tar.extract(member, "/tmp")
src = sqlite3.connect("/tmp/console.db")
src.backup(sqlite3.connect("/data/console.db"))
PY
docker run --rm -v "$CG_CONSOLE_VOLUME":/data alpine chown 10003:10003 /data/console.db
```

5. 启动 `docker compose up -d operations-console`，等待 healthy 且 `/healthz` 返回 200。
6. 登录核对用户、审计与保留的调查材料／任务归属，再做一次只读探测确认网关和执行器连接。恢复调度前单独核对 Worker 房间与回执关联。

## 迁移到另一台机器

在源主机导出归档，经组织认可渠道传输，目标主机验证后执行上述恢复流程。`env.keys.txt` 只包含变量名称，秘密值应从秘密管理系统重新配置。Console 会引用目标主机的网关与审批凭据。迁移原生调查能力时还要迁移相应平台数据、工作区和模型账本。

## 可选模型预算服务

在 `.env` 配置 `CYBERGUARD_GUARD_URL=http://model-guard.agentteams.local:8080` 与匹配的 `CYBERGUARD_GUARD_ADMIN_TOKEN`；该地址是 `compose.model-guard.yaml` 的别名。原生安装使用它自己的 `native-model-guard` 别名，应沿用生成配置。两项留空即不启用。预算操作见[原生安装指南](NATIVE_INSTALL.md)，机制见[模型预算说明](MODEL_GUARD.md)。

## Compose 运行约束

当前服务使用只读根文件系统、`cap_drop: ALL`、`no-new-privileges`、64 MB 的 `noexec,nosuid` `/tmp`、`init: true`、非 root uid 10003、loopback 端口和 `/healthz` 健康检查。依赖网关／执行器 healthy；通过 `cyberguard-readonly`、`cyberguard-execution` 内部网络及 `agentteams-net` 连接所需服务。
