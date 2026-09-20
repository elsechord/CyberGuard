# 本机网页安装桥接服务

`service.py` 是运行在 Linux / WSL 宿主上的 Python 标准库服务。Console 只连接固定 Unix socket；Docker socket 留在宿主服务，不进入 Web Console。启动入口由 `bootstrap.py` 提供，生成私有配置、服务 token 和 Compose overlay。

```sh
sudo python3 deploy/onboarding/bootstrap.py
```

已有部署应传入原计划与私有目录，复用团队、角色凭据和数据卷：

```sh
sudo python3 deploy/onboarding/bootstrap.py \
  --private-dir /root/.config/cyberguard/native-task-service \
  --plan /absolute/path/to/existing/native-plan
```

服务也可独立运行：

```sh
python3 deploy/onboarding/service.py \
  --config /private/onboarding-service.json \
  --socket /run/cyberguard-onboarding/service.sock
```

配置包含固定的 `repo`、`private_dir`、`plan`、`service_env`、`token_file` 路径；可选 `run_dir`、`console_origin`、`console_containers`、`compose_overlays`。这些都由宿主管理员设置，HTTP 请求不能提供脚本、命令或路径。Unix socket 权限为 `0660`、组 `10003`；目录和 token 由启动器准备。测试可以用 `--host 127.0.0.1 --port 18140` 替代 socket。

## HTTP 接口

所有请求需 `Authorization: Bearer <host service token>`。该 token 由 Console 后端读取，不能进入浏览器 JavaScript。成功返回 `{data: ...}`，错误返回 `{error: {code, message}}`；服务不转发子进程输出或供应商错误原文。

| 接口 | 请求 | 结果 |
| --- | --- | --- |
| `GET /v1/status` | 无 | 安装阶段、固定步骤名、脱敏错误、模型名称/地址/是否有密钥、待应用状态、服务状态、预算限额与用量 |
| `POST /v1/model/test` | `base_url, model, api_key?` | 一个真实兼容 Chat Completions 请求，输出上限 32 tokens；仅返回成功和延时 |
| `POST /v1/model/save` | 同上，`apply` 默认 false | 密钥写入宿主 `0600` 私有文件；从不返回密钥 |
| `POST /v1/initialize` | `{}` | 异步固定安装流程，返回 operation_id，轮询 status |
| `POST /v1/budget/open` | `{}` | 显式启用调查；现有 open 幂等，closed 且已排空则创建新 run 并保留旧账本 |

只在相同规范化 base URL 下复用已保存密钥；更换供应商地址必须重新提供密钥。保存新配置与立即应用分开：`pending_apply=true` 时先应用或初始化，再启用调查。

当前模型通道接入 HTTPS OpenAI 兼容服务。内网模型若只提供 HTTP，应先在其前面配置 TLS 代理；测试、保存和初始化统一检查这一条件。

安装流程依次复用或建立 Controller、生成原生计划、注册路由、创建新团队、唤醒 Worker、安装协作 helper、重启并配置团队、应用 Console 私有 override。已有 runtime-ready 计划不重新创建团队。脚本拒绝覆盖其他既有身份。首次构建可能耗时数分钟；页面轮询不会阻塞后台安装。初始化不主动调用模型，也不自动开启预算。

更新已经部署的模型，要求当前预算关闭、没有在途模型请求，且配置中的 Console 容器没有 queued/running 调查。只更新上游地址、模型名称和 key，不更改 role aliases、角色凭据或账本卷；由于模型配置绑定到 run，更新会创建新 run ID 并保留旧账本。新 guard 通过启动健康检查后才报告已应用。重建失败时恢复旧配置并报告 failed，私有 previous 配置可用于恢复。

本目录的 mock / 本地 HTTP 验证不进行真实模型调用或部署：

```sh
python3 -m unittest discover -s tests -p test_onboarding_service.py
```
