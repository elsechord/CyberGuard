# v0.15.0 干净目录部署验收

2026-09-20 09:25–09:29（北京时间），在 Windows 11 / WSL2 Linux 6.6.87.2、Docker Engine 29.7.2 上执行。测试使用当前待发布源码快照，含 tracked 与未忽略的新文件，不含开发机 `.env`；不是从旧运行容器导出应用。归档 SHA256 与版本见 [源码收据](source-receipt-v2.json)。

## 已完成

1. 解包到新的 `/tmp/cg-clean-release-v2-*`，运行 `deploy/init_secrets.py` 生成新密钥。
2. 在独立私有目录生成新的 AgentTeams 服务配置，以测试占位模型密钥生成新的原生计划。准备阶段未调用 Docker API 或模型。
3. Native Compose 和主 Compose 均通过 `config --quiet`；构建入口 Bash 语法、参数入口和三项隔离准备测试通过。
4. 从该目录构建 `cyberguard/operations-console:0.15.0-clean-check` 成功；首次候选构建 23.46 秒，修正后候选复建 1.17 秒。**这些数值复用了本机 Docker 层缓存，不是冷启动下载耗时。**
5. 用全新命名卷、独立容器和本机端口 18138 启动，不接入原有 AgentTeams 网络。通过真实 HTTP 页面完成首次管理员创建、登录、接入页访问和 Skill 文案读取，确认 setup 关闭。最终候选这段流程 4.25 秒。
6. 测试结束删除此次容器及此次命名卷，原有部署未变更。

命令、退出码与耗时见 [预检记录](clean-preflight-v2.json)；6 项 HTTP 验收、镜像 ID 和清理结果见 [Console 验收记录](console-smoke-receipt-v2.json)。模型调用为 0。测试没有保存或公开管理员密码、会话 Cookie、服务密钥。

## 本次发现并修复

- 原生准备和 Console 配置原来依赖开发机固定目录、旧测试 Matrix token；现在支持传入独立路径并从当前安装生成身份。
- `prepare-local.py` 新增 `--directory`，可在指定私有位置生成配置。
- HTTP 本机入口若沿用 Secure Cookie，会影响新用户登录；配置器现在仅对 loopback HTTP 关闭 Secure，HTTPS 部署仍启用。

## 尚未在新主机重复的步骤

本次没有启动第二套原生 Controller / Worker，没有重新下载全部依赖或向新模型路由付费发起调查。固定 v1.2.3 源码上的控制器 localhost 补丁已 dry-run 成功；原生运行时及兼容补丁实际重启后的两次完整调查见 [完整案件记录](../../FULL_CASE_VALIDATION.md)。不能将该既有环境实跑与本页新卷 Console 验收合并为一次全新主机端到端测试。
