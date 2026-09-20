# 调查任务：材料接入与异步处理

[中文文档导航](README.zh-CN.md) · [部署与模型配置](WEB_ONBOARDING.zh-CN.md)

调查任务把用户或 Agent 提交的材料、调查目标、处理状态和报告放在同一个持久化任务中。控制台入口为 `/investigations`。安全调查为默认领域；财务、法律和通用领域用于材料归纳、矛盾定位与待核实问题整理，报告是待人工复核草稿，不代表审计结论、法律意见或司法可采性认定。

## 提交材料

简易表单接收标题、目标、领域和一份材料。高级 JSON 可一次提交 1–32 份材料；填写高级 JSON 后忽略简易表单字段。

```json
{
  "title": "核对登录告警与服务器日志",
  "objective": "比较两个来源的时间与主张，指出尚缺的证据",
  "domain": "security",
  "materials": [
    {
      "source_type": "agent",
      "name": "Agent 提交的原始记录",
      "media_type": "text/plain",
      "content": "2026-09-20T01:00:00Z user=demo result=denied",
      "interpretation": "提交者认为可能存在异常登录，尚待核实"
    },
    {
      "source_type": "server_log",
      "name": "服务器日志节选",
      "media_type": "text/plain",
      "content": "2026-09-20T01:00:01Z user=demo reason=expired_password",
      "source_uri": "server-a/auth.log",
      "observed_at": "2026-09-20T01:00:01Z"
    }
  ]
}
```

`domain` 支持 `security`、`finance`、`legal`、`general`。`source_type` 支持 `agent`、`firewall`、`edr`、`honeypot`、`server_log`、`financial_record`、`audit_report`、`judicial_document`、`other`。来源类型是提交者声明，不构成产品连接器或已验证设备身份。

接收格式仅为 UTF-8 文本：`text/plain`、`application/json`、`text/markdown`、`text/csv`。JSON/CSV 材料作为原始文本保存，媒体类型不意味着已做结构或语义校验。不提供原生 PDF、Office、图像 OCR、压缩包解析或任意 URL 抓取；`source_uri` 仅保存为标签。自行提取的文本应标明提取方式及原文件引用；当前材料哈希覆盖提交文本，不覆盖未上传的原文件。

标题和材料名最多 200 字符，目标最多 8000 字符；单份原文及解释分别最多 128 KiB UTF-8，整个提交最多 1 MiB。网页表单也限制编码后的请求体大小，因此大量非 ASCII 内容经表单编码后可能更早达到限制。拒绝控制/二进制数据、未知字段、重复 JSON 字段和重复材料身份。

## 原文、解释与来源身份

原文逐字保存，提交者解释保存在独立 `interpretation` 字段。`sha256` 覆盖原文 UTF-8 字节；`material_id` 根据原文和来源元数据确定，不因解释变化而改变。请求指纹同时覆盖解释，用于区分不同提交。每份材料初始标为 `source_authenticity: unverified`、`submitted_as: original_input`；认证用户的提交身份由服务端记录，客户端不能指定。

哈希用于完整性检查和身份引用，不能证明来源身份、时间真实性或内容正确。材料中的命令、提示词及 URL 都是待分析的数据，不授予工具调用或系统访问权限。任何推断应引用具体材料和原文片段，将观察、提交者主张、Agent 推断与证据不足分开。原文与解释一起进入部署配置的 Agent 处理环境；应先确认数据使用授权。

## 状态与运行边界

任务与阶段事件持久化保存。`queued` 表示已入队，`running` 表示处理阶段已开始，`waiting_backend` 表示等待可用后端，`completed`、`failed`、`canceled` 为终态。网页刷新读取真实记录，不使用动画或计时器推断完成进度。失败与等待状态应保留错误和既有记录；接收成功不代表已产生报告。

当前默认使用 AgentTeams 原生 Project/Task。Console 创建 Project 并一次性通知 Leader；Leader 决定任务依赖、委派和验收。任务详情展示原生节点状态，完成报告从 Controller 的 Task artifact 接口读取。CyberGuard ID 与原生 Project/Task ID 分别保留。取消调用原生 Project pause，停止后续调度；在途任务可能继续完成。

取消停止后续阶段，已经发出的远程请求可能继续执行。幂等键防止同一次提交重试创建重复任务；更换目标或材料后应使用新键。任务持久化不等于任意远程操作可自动安全重放，进程恢复时须按实际阶段状态处理。

对采用模型预算守卫的部署，可设置 `CYBERGUARD_INVESTIGATION_REQUIRE_GUARD_ARMED=true`，并配置 Console 的守卫地址和管理凭据。新任务会等待预算开启后再开始分发；已经发出的阶段仍继续读取实际结果。该检查不预留费用，实际请求仍由守卫的请求数和 token 限额约束。未使用此类守卫的部署保持默认 `false`。

## 权限

网页仅接受控制台会话，提交与取消要求分析员或更高角色并校验 CSRF。API 调查任务使用独立的 `investigations:read` / `investigations:write` 授权；原有 `incidents:read` 只读连接凭据不会自动获得任务提交权限。通常只能访问创建者自己的任务；管理员会话可以查看全部。API 凭据持有者应只获得必要 scope，并使用每个 Agent 独立、可撤销的凭据。

调查任务产出材料审阅报告，不直接授权防火墙修改、封禁、财务操作或法律决策。既有安全处置审批流程仍需独立遵守。
