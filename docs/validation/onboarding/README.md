# 网页安装向导传输验收

2026-09-20，使用 `cyberguard/operations-console:0.15.1`、独立 Console 数据卷和 18138 端口完成 **10 项真实传输检查，耗时 16.45 秒**。结果见 [summary.json](summary.json)。

实际路径：首次管理员创建并自动登录 → 向导页面 → Console 后端 → Unix socket 宿主服务 → 临时 HTTPS OpenAI 兼容测试服务 → 私有配置保存 → 宿主服务重启 → 配置仍可读取。

仅发送了一次认证正确、输出上限 32 tokens 的本地 HTTPS 请求。证书由临时 openssl CA 提供，信任仅通过测试宿主服务进程的 `SSL_CERT_FILE` 设置，不修改系统证书。API Key、管理员密码、服务 token 和证书私钥均在临时目录生成，不进入仓库；配置文件权限实测为 `0600`。所有测试容器、数据卷、进程和临时文件已清理。

第一次运行暴露 Console 的 uid 为 10003、主 gid 实际为 999，而 socket/token 属于组 10003 的权限问题。保留的 [failure-001.json](failure-001.json) 对应此失败；`compose.onboarding.yaml` 增加补充组 10003 后复验通过。

复现需要 Linux/WSL2 root、Docker、openssl 和 Python：

```sh
sudo python3 scripts/validate-onboarding.py --image cyberguard/operations-console:0.15.1
```

此次验证没有调用真实供应商、初始化原生团队或开启付费预算，也未改动已有部署。模型配置更新、账本延续、鉴权和故障恢复另由 `tests/test_onboarding_service.py` 覆盖；本记录证明的是真实 HTTP/HTTPS/Unix socket 与首次管理员流程，不能代替全新主机的完整原生安装验收。
