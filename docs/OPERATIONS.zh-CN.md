# 日常运维与历史验收脚本

[English](OPERATIONS.md) · [中文文档导航](README.zh-CN.md)

当前原生 v1.2.3 调查服务按[原生安装指南](NATIVE_INSTALL.md)运行；多用户控制台备份见[部署手册](OPERATIONS_DEPLOY.zh-CN.md)。本页同时保留较早的服务器验收与七角色 Manager 启动流程，它们不能替代当前原生团队安装。

## 健康检查

```bash
docker ps --filter name=agentteams
docker compose ps
curl -fsS http://127.0.0.1:18100/health
curl -fsS http://127.0.0.1:18105/health
```

只读证据台位于 <http://127.0.0.1:18100/console>。使用 SSH 隧道或私有 VPN，不直接开放原始端口。

## 基础服务端到端验收

以下是历史服务器 bootstrap 路径，先核对其部署目录、已有平台和版本，再在对应实验主机使用：

```bash
sudo bash deploy/bootstrap-server.sh
```

脚本检查主机、缺失时安全生成 `.env`、验证两份环境配置、在网络不存在时安装 AgentTeams，再执行服务器验收。验收默认构建服务（`CYBERGUARD_SKIP_BUILD=1` 可跳过），启动并检查服务，创建唯一的模拟事件，验证批准／执行／复核／回滚，并在 `artifacts/acceptance/` 生成带时间戳的证据包。

包中包含版本、镜像 ID、服务状态、脱敏日志、OpenAPI、API 证据、HMAC 审计检查点、校验清单及失败诊断，不包含 `.env`、审批秘密、bearer token 或完整容器 inspect 输出。`acceptance.log` 在脚本退出前仍在写入，因此明确标为未纳入哈希。保留提交用证据，不提交客户遥测。

五类秘密分别用于 Worker 读取、处置提案／执行、人工批准、审计认证和只读审计验证。审批与审计 HMAC 秘密不发给 Agent。审计 HMAC 轮换需要记录检查点，旧记录仍需旧 key 验证。

基础恢复判定比较已认证执行器返回的 action/target 与场景 `required_actions`：无关动作、错误目标、只完成部分动作、过期批准或回滚，不能产生 verified。

## 历史 Manager 启动与就绪核对

旧的七角色路径在一次性 Higress 工具注册后运行 `deploy/bootstrap-agentteams.sh`：通过配置的 `/host-share` 放置带校验的 Skill ZIP，向唯一 Manager 私聊发出绑定哈希的请求，核对七角色 manifest。`deploy/competition-readiness.sh` 将该 manifest 与真实 Worker／Team CR 快照交叉核对并生成带校验的报告。单独一条 Manager 回复不算就绪证明。

## 日志

```bash
docker compose logs --tail=200 security-tool-gateway
docker compose logs --tail=200 response-executor
docker exec agentteams-manager cat /var/log/agentteams/manager-agent.log
```

最后一条仅适用于存在 Manager 容器的旧部署。不要公开 `.env`、`agentteams-manager.env` 或原始日志；上游问题反馈使用脱敏调试导出。

## 备份与升级

分别备份平台数据、CyberGuard 证据／动作卷、旧部署的 `/srv/cyberguard/agentteams-manager`、以及版本管理内的 Skill／schema／场景。旧配方卷名为 `agentteams-data`、`cyberguard-evidence`、`cyberguard-actions`，实际部署可能带 Compose 前缀，应以容器 Mounts 为准。当前原生平台使用自己的 data/workspace 卷，见原生指南。

一致性备份前暂停新任务，在独立主机验证恢复。历史 bootstrap 固定 v1.2.2，当前原生调查固定 v1.2.3；不要把比赛主机改为 latest。先在克隆卷上验证升级和 smoke 测试，再明确更新固定版本。

## 为新演示准备事件

每轮使用新的 `incident_id`，可复用确定性场景。不要删除旧审计记录，用事件 ID 过滤即可。需要干净性能测量时，使用独立基准实例，不清空主要审计历史。
