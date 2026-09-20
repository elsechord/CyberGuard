# 网页安装向导：从启动到第一份调查

[中文文档导航](README.zh-CN.md) · [命令行安装](NATIVE_INSTALL.md)

网页向导把模型配置、AgentTeams 初始化和预算开启放进管理员控制台。你先在部署主机运行一次启动器，之后在浏览器完成配置。使用已包含 `deploy/onboarding/bootstrap.py` 的源码版本；旧版发布包没有这一入口时，按命令行指南操作或升级到包含向导的版本。

## 1. 启动基础服务

准备 Linux 或 WSL2、Git、Python 3.12、Bash、patch、Docker Engine／Docker Desktop 与 Compose 插件。建议 8 核、16 GB 内存、100 GB SSD，并能访问代码和镜像下载源。

```bash
git clone https://github.com/elsechord/CyberGuard.git
cd CyberGuard
sudo python3 deploy/onboarding/bootstrap.py
```

启动器需要管理本机 Docker 与安装服务，因此使用 root。它生成私有配置、准备网络、启动宿主机部署服务，并构建／启动基础 Console。模型密钥不用写到命令行。

启动结束打开 <http://127.0.0.1:18120/setup>。远程主机请通过 SSH 隧道／私有网络访问，或配置自己的 HTTPS 入口和 `--console-origin https://YOUR_DOMAIN`；该参数不会自动创建域名或 HTTPS 代理。

宿主机部署服务通过受限 Unix socket 与 Console 通信；**Console 容器不挂载 Docker socket，也不挂载宿主机模型配置目录**。部署服务本身具备主机管理权限，仅供该部署管理员使用。

## 2. 创建管理员

```bash
docker compose logs operations-console
```

从日志的 `CYBERGUARD SETUP TOKEN (first boot only)` 行复制一次性 token，在 `/setup` 创建首个管理员。密码至少 12 个字符；不要共享日志中的 token。

完成后登录，进入「部署向导」(`/settings/onboarding`)。已有管理员可以直接打开这个地址；普通成员没有修改部署配置的权限。

## 3. 配置模型

填写兼容 OpenAI Chat Completions 的 HTTPS 服务。仅提供 HTTP 的内网模型需先加 TLS 代理；网页测试、保存和初始化采用相同要求：

| 字段 | 填写方式 |
| --- | --- |
| API Base URL | 如 `https://api.example.com/v1`，不放入 key、查询参数或账号密码 |
| 模型名称 | 服务商接受的精确 model 名称 |
| API Key | 首次填写真实密钥；相同 Base URL 下留空可保留已有 key，更换地址必须重新提供 |

点击「测试连接」会发送一条简短请求（`Reply OK.`，请求输出上限 32 token），可能产生少量模型费用。它验证地址、模型和凭据是否能返回响应，不自动保存新 key。

测试后页面保留本次输入，可直接点击「保存配置」，不必重复输入密钥；状态刷新不会覆盖尚未保存的表单。服务端不把 key 返回到浏览器。保存成功后密钥输入框清空，仅显示是否已有配置。

「保存配置」只写配置，下一步初始化／应用后才进入调查服务。已有团队需要更换模型时，可点击「保存并应用到调查服务」，等待成功再开启新的调查预算。首次部署仍要完成团队初始化。

已经有案件运行或预算尚未结束时，配置变更可能被拒绝。先等案件和在途请求结束，再按[预算操作](NATIVE_INSTALL.md#5-开始第一案)结束原窗口；不要为改配置而清空账本。应用新模型会创建新的 run ID，保留角色凭据、路由别名与旧账本；模型服务通过健康检查后才报告应用成功，失败时保留恢复信息。

## 4. 初始化调查团队

点击「初始化 / 应用配置」。后台依次准备平台、构建缺失镜像、创建模型路由与原生团队、唤醒 Worker、安装材料／协作组件与兼容修正、重启加载，再连接 Console。

页面展示当前状态、具体步骤、Controller 和模型网关状态。首次镜像下载及编译可能需要较长时间；浏览器关闭不会替代后台服务停止操作，确保部署主机与部署服务持续运行。连接 Console 的步骤可能重建控制台，短暂连接中断后刷新页面。

该流程针对当前固定的本地嵌入式拓扑。它不是任意 Kubernetes／厂商集群的一键适配器，也不会迁移未声明的旧 AgentTeams 环境。

## 5. 显式开启预算

初始化就绪后，在页面核对本轮预算限额，再点击「启用调查预算」。保存和初始化不等于允许持续付费调查；只有开启后，提交任务才会经模型通道运行。

页面展示是否开启及配置限额。已经关闭的账本不会清零重用；需要新窗口时部署服务创建新的 run ID，保留旧账本。在途用量未结算时等待完成，不删除数据卷绕过限制。

## 6. 提交或连接已有 Agent

- 点击「提交第一份调查」进入 `/investigations`，输入明确目标和一份小材料，观察调查、独立复核与报告生成。多源材料可用高级 JSON，见[调查任务](INVESTIGATION_TASKS.md)。
- 点击「连接已有 Agent」进入 `/connect`，生成所选客户端的 Skill 提示词。将专用 API Key 放到 Agent 机器的私有文件，提示词只引用路径，见[Skill 使用](EXTERNAL_AGENT_SKILL.md)。

调用方 Agent 提交材料，后台 AgentTeams 负责调查；安装 Skill 不会把客户端自动改造成后台模型 API，也不会自动上传本机文件。

## 复用已有安装

已有相同部署拓扑时，显式传入原目录，避免误建第二套计划：

```bash
sudo python3 deploy/onboarding/bootstrap.py \
  --private-dir /ABSOLUTE/PATH/native-private \
  --plan /ABSOLUTE/PATH/native-plan \
  --service-env /ABSOLUTE/PATH/agentteams-local.env
```

三个值必须对应同一套原安装，`service-env` 文件名为 `agentteams-local.env`。原安装使用 root 默认路径时可继续使用默认值；普通用户先前创建的配置不会因为 sudo 自动变成 root 的同一目录，应显式传路径。`--run-dir` 可指定部署服务 Unix socket 所在目录，默认 `/run/cyberguard-onboarding`。

## 常见问题

| 页面情况 | 处理 |
| --- | --- |
| 尚未连接宿主机部署服务 | 确认已运行启动器，使用包含 `compose.onboarding.yaml` 的部署配置；基础 Console 仍可使用。 |
| 模型连接失败 | 核对 HTTPS Base URL、model 和 key，确认主机可达服务；不要将 key 放在 URL 中。 |
| 保存后模型未变更 | 保存与应用分开，继续点击初始化／应用，等待状态就绪。 |
| 当前有运行中任务／初始化 | 等待已开始操作完成，不重复创建团队或清空数据。 |
| 重建 Console 时短暂断开 | 稍等后刷新，核对后台状态。 |
| 重启主机后向导不可用 | 有 systemd 的主机由 `cyberguard-onboarding.service` 启动；无 systemd 的环境需重新运行启动器。 |
| 初始化失败 | 检查私有部署服务日志或 `journalctl -u cyberguard-onboarding.service`，保留失败状态后定位，不公开含秘密的日志。 |

systemd 环境会安装并启用对应服务；无 systemd 时使用后台进程与私有 PID／日志文件。应用升级后继续运行启动器保留向导连接。仅查看状态不会调用模型，测试连接与实际调查会产生模型请求。
