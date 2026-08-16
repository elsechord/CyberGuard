@<team_leader_name>

请处理一条新的安全事件，并严格执行 CyberGuard 的证据、审批、验证和审计流程。

incident_id: CG-2026-0001
scenario_id: credential_compromise
客户：杭州示例金融科技公司
环境：VPN + Windows Endpoint + SIEM + EDR + Network Sensor

事件现象：
2026-08-13 09:12 起，财务运维账号出现不可能旅行、新设备登录和连续 MFA 请求；随后财务终端 FIN-LT-023 出现异常出站流量。

初始告警：
- 09:12 finance-ops impossible_travel P1
- 09:13 finance-ops new_device_login P1
- 09:14 FIN-LT-023 suspicious_outbound_volume P1

要求：
1. 主动查询证据，不得把初始告警直接当成结论；
2. 至少维护两个竞争假设并寻找反证；
3. 关联威胁情报、网络、边界策略、终端和资产上下文；
4. 提出覆盖账号、终端与恶意目的地的最小影响、可回滚处置方案；
5. L2 动作必须等待真实人工批准；
6. 处置后由独立 Agent 验证；
7. 输出包含 Evidence ID、Action ID、审批、回滚和残余风险的事故报告。
8. 若任何调查工具、遥测或证据校验不可用，明确输出 `PARTIAL`、`BLOCKED` 或 `INCONCLUSIVE`；不得补写缺失的 IP、端口、规则、进程或 Evidence ID。
