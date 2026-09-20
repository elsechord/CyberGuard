# 从零部署 AgentTeams 调查服务

本页从一台 Linux / WSL2 Docker 主机开始，部署 Console、原生 AgentTeams 团队和受预算控制的模型通道。所有命令在仓库根目录执行。已有平台可以直接从第 4 步接入自己的配置；基础 Console 安装见 [Quickstart](QUICKSTART.md)。

## 1. 准备主机与私有配置

需要 Git、Python 3.12、Bash、patch、Docker Engine 与 Compose 插件。建议 8 核、16 GB 内存和 100 GB 可用磁盘；首次构建还需要访问 GitHub、容器与 Python/Go 包镜像。以下单主机配方使用固定容器名和端口，请在没有另一套 AgentTeams 的主机上安装。Windows 请在 WSL2 内执行，保持同一 Linux 用户；该用户须能操作 Docker。

```sh
git clone https://github.com/elsechord/CyberGuard.git
cd CyberGuard
python3 deploy/init_secrets.py
python3 deploy/agentteams-local/prepare-local.py
export CYBERGUARD_AGENTTEAMS_SERVICE_ENV="$HOME/.config/cyberguard/agentteams-local.env"
export CG_PRIVATE="$HOME/.config/cyberguard/native-task-service"
export CG_PLAN="$HOME/.local/share/cyberguard/native-plan"
mkdir -p "$HOME/.config/cyberguard"
umask 077
```

使用编辑器创建 `$HOME/.config/cyberguard/agentteams-llm.env`，填写你自己的 OpenAI 兼容服务。示例中的值需要替换；`BASE_URL` 截止到 `/v1`，不包含 `/chat/completions`。密钥仅保存在此私有文件，不填写到 Skill 提示词。

```dotenv
AGENTTEAMS_DEFAULT_MODEL=YOUR_MODEL_NAME
AGENTTEAMS_OPENAI_BASE_URL=https://YOUR_PROVIDER/v1
AGENTTEAMS_LLM_API_KEY=YOUR_API_KEY
```

```sh
chmod 600 "$HOME/.config/cyberguard/agentteams-llm.env"
```

## 2. 构建并启动平台

控制器构建脚本固定 AgentTeams v1.2.3 提交 `223ddc2b8073e4c8b93bcbb15e1d717f196c04d9`，只加入自动发布 Worker 端口绑定本机的补丁。Worker 镜像也固定 digest。

```sh
python3 deploy/agentteams-local/ensure-private-network.py
bash deploy/investigation-service/build-controller.sh
docker build -f services/model-guard/Dockerfile -t cyberguard/model-guard:native .
docker compose -f deploy/investigation-service/compose.native.yaml up -d
docker compose -f deploy/investigation-service/compose.native.yaml ps
```

等待 Controller 健康，再运行下一步。镜像下载和首次 Go 构建耗时与网络相关。此时 Manager 关闭，尚未开放模型调用。

## 3. 创建原生团队及预算通道

```sh
python3 deploy/investigation-service/prepare-native-team.py \
  --private-dir "$CG_PRIVATE" --plan "$CG_PLAN" \
  --model-env "$HOME/.config/cyberguard/agentteams-llm.env" \
  --run-id CG-FIRST-001 --name-prefix cg-native001
python3 deploy/agentteams-local/register-guarded-routes.py \
  --plan "$CG_PLAN" --guard-env "$CG_PRIVATE/model-guard.env"
python3 deploy/agentteams-local/apply-guarded-team.py \
  --plan "$CG_PLAN" --out "$CG_PLAN/deployment.json"
docker exec agentteams-controller agt worker wake --name cg-native001-planner
docker exec agentteams-controller agt worker wake --name cg-native001-investigator
docker exec agentteams-controller agt worker wake --name cg-native001-verifier
docker exec agentteams-controller agt get workers -o json
```

准备器生成新的不可变计划、三条角色模型路由和独立预算账本，不读取开发者机器上的旧验证配置。它拒绝覆盖已有计划。初始预算为 120 次请求、500 万输入 token、15 万输出 token、最多 4 个并发；这是费用上限，不是单案成本承诺。启动时预算未开启。可以在首次启动前审阅私有 `model-guard-config.json` 中的限额。

等三个 Worker 就绪后，安装材料传递、协作工具与 v1.2.3 兼容修正，然后重启加载：

```sh
python3 deploy/investigation-service/install-collaboration.py --manifest "$CG_PLAN/manifest.json"
docker restart agentteams-worker-cg-native001-planner agentteams-worker-cg-native001-investigator agentteams-worker-cg-native001-verifier
```

等待 Worker 就绪后再执行第 4 步。补丁解决原生委派短名到 Matrix ID 的解析，以及本地嵌入式部署重启后的模型数据路由；不会改写原生 Task 状态。普通重启保留安装结果，**容器重新创建后需要重装并重启**。不要在案件处理中升级或重启 Worker。

## 4. 连接 Console

```sh
python3 deploy/investigation-service/configure-native-team.py \
  --private-dir "$CG_PRIVATE" --plan "$CG_PLAN" \
  --service-env "$CYBERGUARD_AGENTTEAMS_SERVICE_ENV"
docker compose -f compose.yaml -f "$CG_PRIVATE/console.override.json" up -d --build
curl -fsS http://127.0.0.1:18120/healthz
```

配置器使用这台主机的 AgentTeams 管理员身份登录 Matrix，将持久 token 写入私有目录；重复配置复用该身份，不依赖历史 demo 的 token。它保留原生工具，设置 40 次迭代上限，并把 Console 连接到新团队。输出 `runtime-ready.json` 可用于核对团队和工具状态。

打开 `http://127.0.0.1:18120`，按 [Console 首次管理员配置](OPERATIONS_DEPLOY.md) 完成设置。在接入页面创建 API Key 并生成 Skill 提示词。调用方提交材料后，Console 自动创建案件 TaskRoom、邀请团队并投递完整请求，无需手工创建 Matrix 房间。

已有 v1.2.3 团队可通过 [原生连接变量](AGENTTEAMS_TASK_SERVICE.md#配置) 配置自己的 Controller/Matrix 地址、团队与 Leader ID；所有参与 Worker 均需安装上述材料 helper。自有预算系统不必使用此处 Model Guard，但需提供可用的模型服务。

## 5. 开始第一案

确认模型服务、材料与预算后：

```sh
python3 deploy/investigation-service/budget.py status --private-dir "$CG_PRIVATE"
python3 deploy/investigation-service/budget.py arm --private-dir "$CG_PRIVATE"
```

使用 Console 生成的 Skill 提示词提交 `deploy/investigation-service/cases/miner-recovery.json` 中的材料，或在 Console 提交自己的调查请求。案件经过原生任务规划、调查、独立复核后，可从 Console 与 Skill 查询同一个报告。示例材料是合成挖矿案件；[已验证报告与原生任务证据](FULL_CASE_VALIDATION.md) 可在不调用模型的情况下查看。

完成测试、不再接收新案件时关闭预算：

```sh
python3 deploy/investigation-service/budget.py close --private-dir "$CG_PRIVATE"
python3 deploy/investigation-service/budget.py status --private-dir "$CG_PRIVATE"
```

`close` 是结束本次账本，不能重新开启已关闭账本。后续新一轮运行应使用新的 run ID 和审阅后的预算，保留旧账本，不删除卷来清零用量。在关闭前也可在同一预算窗口内连续提交多个案件；查询报告不需要开启模型预算。

确认 `status` 中在途请求数 `concurrency_used` 为 0 后，可以保持角色凭据和原卷创建下一预算窗口。新窗口仍需显式开启：

```sh
python3 deploy/investigation-service/budget.py new-run --private-dir "$CG_PRIVATE" --run-id CG-SECOND-001
python3 deploy/investigation-service/budget.py status --private-dir "$CG_PRIVATE"
python3 deploy/investigation-service/budget.py arm --private-dir "$CG_PRIVATE"
```

新窗口沿用配置中的限额。它会重建预算服务容器，不会删除账本卷、重建团队或重新注册模型路由。

## 运维与验收

| 情况 | 操作 |
| --- | --- |
| Console 重建 | 保留 `console.override.json` 和原数据卷，重复第 4 步 Compose 命令 |
| Worker 普通重启 | 已安装的兼容层保留；核对模型路由与原生工具就绪 |
| Worker 容器重建 / 镜像升级 | 重新安装 helper/兼容层，重启，再运行配置器；不要中断正在执行的案件 |
| 请求处于等待 | 检查 Controller/Team 就绪、预算 armed、模型连通和 Console 配置，不重复提交同一案件 |
| 迁移主机 | 保存 Console 数据、AgentTeams 数据/工作区与模型预算卷；私有配置单独加密备份 |

当前发布验收包括：独立临时目录生成新配置、计划 SHA256 校验、秘密不进入公开计划、重复执行不覆盖配置，以及现有 Docker 环境真实重启后连续两案完成。**全新主机从拉镜像到真实模型交付的整套计时尚未重新测量**；Quickstart 的旧基础服务耗时不能代指这套原生团队安装耗时。

本次无模型安装预检命令：`python3 deploy/investigation-service/test_portable_preparation.py`（Windows 和 WSL 均 3 项通过）、`bash -n deploy/investigation-service/build-controller.sh`、使用临时服务 env 的 `docker compose ... config --quiet`、固定 v1.2.3 源码上的 localhost 补丁 dry-run。预检没有启动或修改当前运行容器。
