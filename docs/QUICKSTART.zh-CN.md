# 快速开始：从源码到第一份证据

[English](QUICKSTART.md) · [中文文档导航](README.zh-CN.md)

希望直接在网页配置模型和调查团队，请从[网页安装向导](WEB_ONBOARDING.zh-CN.md)开始。

需要完整的 AgentTeams 调查服务时，请接着阅读[原生安装指南](NATIVE_INSTALL.md)，完成模型、团队、Worker 兼容工具与 Console 连接。本页先启动基础证据服务；基础服务启动成功并不表示推理后端已配置。

准备 Git、Python 3.12；Docker 路径还需要 Docker Engine 或 Docker Desktop。2026-09-18 在 Windows 11、Git Bash、Python 3.12.10 的新克隆上，从创建虚拟环境到控制台出现第一份证据实测 **6 分 07 秒**，其中当时的 23 个测试文件耗时 2 分 01 秒。该数字是历史基础 Python 路径记录，不包含完整原生团队安装；Docker 首次运行另有镜像构建时间。

## 路径 A：Docker Compose

### 1. 获取源码

```bash
git clone https://github.com/elsechord/CyberGuard.git
cd CyberGuard
```

### 2. 生成服务凭据

```bash
python deploy/init_secrets.py
```

脚本只依赖 Python 标准库，读取 `.env.example`，创建权限为 0600 的 `.env`，为网关、执行器、审批、审计 HMAC 与审计读取分别生成随机凭据，不打印秘密值，不覆盖已有文件。后续调用需要其中的 `CYBERGUARD_API_TOKEN`；不要把 `.env` 提交到仓库。

### 3. 构建并启动

```bash
python deploy/agentteams-local/ensure-private-network.py
docker compose up -d --build
```

`agentteams-net` 是外部网络，新主机也需要先创建。上面的网络脚本为自动发布端口设置 loopback 默认值，后续可继续接入原生 AgentTeams。若已有同名网络配置不同，脚本会保留原网络并提示处理，不会直接迁移其容器。

网关监听 `127.0.0.1:18100`，响应执行器监听 `127.0.0.1:18105`。容器以非 root 身份运行，根文件系统只读，不保留 Linux capabilities。多用户 Console 位于 `127.0.0.1:18120`，首次设置见[控制台部署](OPERATIONS_DEPLOY.zh-CN.md)。

### 4. 采集第一份证据

打开 <http://127.0.0.1:18100/console>。事件列表初始为空，采集证据后才会出现事件。在 Bash 中执行：

```bash
curl -X POST http://127.0.0.1:18100/tools/alert/snapshot \
  -H "Authorization: Bearer $(grep -m1 CYBERGUARD_API_TOKEN .env | cut -d= -f2)" \
  -H "Content-Type: application/json" \
  -d '{"incident_id":"CG-QUICKSTART","scenario_id":"credential_compromise"}'
```

刷新页面，可看到 `CG-QUICKSTART` 的证据数量、来源、ATT&CK 技术标签和质量检查结果。这一步使用仓库中的演练材料。

停止服务用 `docker compose down`，数据卷默认保留。仅在确实要删除本地证据时使用 `docker compose down -v`。

## 路径 B：Python 虚拟环境

此路径不需要 Docker。以下运行命令按已验证的 Windows Git Bash 编写；Linux 将 `.venv/Scripts/python` 换成 `.venv/bin/python`。

### 1. 获取源码并创建环境

```bash
git clone https://github.com/elsechord/CyberGuard.git
cd CyberGuard
python -m venv .venv
```

### 2. 安装依赖

Linux x86_64 可使用带哈希锁定的依赖：

```bash
.venv/bin/python -m pip install -r services/requirements.lock -r tests/requirements.lock
```

锁文件包含 `pydantic-core` 等包的 Linux wheel，Windows 不适用。Windows 使用服务依赖和测试 HTTP 客户端：

```bash
.venv/Scripts/python -m pip install \
  -r services/security-tool-gateway/requirements.txt \
  -r services/response-executor/requirements.txt httpx
```

### 3. 运行测试（可选）

```bash
for f in tests/test_*.py; do .venv/Scripts/python "$f" || break; done
```

每个测试文件使用独立解释器。不同服务都使用名为 `app` 的包，不能把全仓测试直接放进同一个 `pytest tests/` 进程收集。历史计时中的 23 个文件并非当前测试文件总数。

### 4. 启动只读网关

```bash
export PYTHONPATH="$PWD" CYBERGUARD_API_TOKEN=dev-read-token
export CYBERGUARD_SCENARIO_DIR="$PWD/scenarios" \
       CYBERGUARD_DATA_DIR="$PWD/tmp/data" \
       CYBERGUARD_KNOWLEDGE_DIR="$PWD/knowledge"
mkdir -p tmp/data
.venv/Scripts/python -m uvicorn app.main:app \
  --app-dir services/security-tool-gateway --host 127.0.0.1 --port 18100
```

在另一个终端采集演练证据：

```bash
curl -X POST http://127.0.0.1:18100/tools/alert/snapshot \
  -H "Authorization: Bearer dev-read-token" \
  -H "Content-Type: application/json" \
  -d '{"incident_id":"CG-QUICKSTART","scenario_id":"credential_compromise"}'
```

打开 <http://127.0.0.1:18100/console> 查看结果。`dev-read-token` 仅为本机示例；缺少 `Authorization` 时工具/API 返回 401。

响应执行器采用相同启动方式，将 `--app-dir` 改成 `services/response-executor`，并设置它独立的执行与审批凭据。完整流程见[实验运行手册](LAB_EXECUTION.md)。默认端口为网关 18100、执行器 18105、模型预算服务 18110（`compose.model-guard.yaml`）。

## 预构建镜像

发布工作流 [publish-images.yml](../.github/workflows/publish-images.yml) 可在发布或手动触发时构建 GHCR 镜像。最早一次已验证的历史标签为：

```bash
docker pull ghcr.io/elsechord/cyberguard-gateway:sha-3b34e4c
docker pull ghcr.io/elsechord/cyberguard-executor:sha-3b34e4c
```

这是历史镜像，不代表当前源码版本。发布工作流会为正式版本附加 `vX.Y.Z` 与 `latest` 标签；使用前确认对应发布确实已完成。镜像目标平台为 `linux/amd64`。需要当前代码时优先按上面从源码构建。

## 新环境常见问题

| 现象 | 原因与处理 |
| --- | --- |
| 18100 被占用，uvicorn 返回 code 3 / winerror 10048 | 改用空闲端口，例如 `--port 18255`，同时修改访问地址。 |
| token 正确仍报 invalid bearer token | 可能访问了占用该端口的另一实例。先核对自己启动的服务和端口，再排查凭据。 |
| pip 连接超时 | 检查失效的代理配置，删除相应代理环境变量或换成可用代理。 |
| Windows 无法安装哈希锁定依赖 | 锁文件目标为 Linux x86_64，改用路径 B 的 Windows 依赖命令。 |
| 首次事件列表为空 | 先调用 `alert/snapshot` 或导入真实材料，事件由证据产生。 |
| 整套 pytest 出现 app 包冲突 | 每个测试文件使用独立解释器。 |

## 下一步

- [中文文档导航](README.zh-CN.md)：按安装、使用、接入、运维查找文档。
- [完整调查服务安装](NATIVE_INSTALL.md)：配置原生 AgentTeams。
- [连接已有 Agent](EXTERNAL_AGENT_SKILL.md)：从 Console 生成 Skill 提示词。
- [真实日志导入](INGEST.zh-CN.md)：导入 Suricata EVE。
- [威胁模型](THREAT_MODEL.md)：了解部署边界。
