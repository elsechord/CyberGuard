# 调查基础设施：来源与设计依据

核查日期：2026-09-20。本文区分已实现的文本接入边界与后续扩展建议，不宣称通过任何标准认证，也不替代金融、法律或取证专业判断。

## 前沿方案比较与本次选择

这里的“最佳实践”指官方可核查的架构模式，不表示经过统一基准测试的性能排名。

| 方案 | 可借鉴的机制 | CyberGuard 本次取舍 |
| --- | --- | --- |
| [A2A Task 生命周期](https://a2a-protocol.org/latest/topics/life-of-a-task/) | 将即时消息与有生命周期的任务分开；终态任务保持不变，后续工作形成新任务 | 提交后返回任务 ID，独立查询状态/结果和取消；终态不重开。本次是自有 HTTP API，未实现 A2A 协议或 Agent Card |
| [LangGraph Persistence](https://docs.langchain.com/oss/python/langgraph/persistence) | 检查点保存执行状态，使执行过程能够恢复和检查 | 保存每一阶段的游标、提交回执和 Worker 报告；使用 SQLite 与租约，不额外引入另一套 Agent 执行引擎 |
| [Azure 异步请求应答](https://learn.microsoft.com/en-us/azure/architecture/patterns/asynchronous-request-reply) | 接收请求与后台执行分离，返回 202 和状态地址 | CLI/Console 共享同一任务服务，客户端断开不丢任务；支持幂等提交 |
| [Supabase AI Tools](https://supabase.com/docs/guides/ai-tools) | Skills、连接与客户端安装是不同层次 | Console 生成连接提示词，Skill 只负责授权材料提交和结果获取，实际调查在 AgentTeams 中运行 |
| W3C PROV / Web Annotation | 来源关联与具体引文分离表示 | 原文、提交者解释和调查发现分开保存；报告关联材料标识与精确原文 |

组合后的主流程是“选择部署 → 连接调用方 Agent → 提交获准材料与目标 → AgentTeams 调查/方案/复核 → 获取可审阅报告”。外部 Agent 不充当 LLM API 代理，也无需先替后端完成调查。跨领域共享的是这个处理流程；领域判断质量仍需各自的数据和验收集验证。

## 统一材料，不强制统一专业解释

现有 `contracts/evidence.schema.json` 将安全证据限定为 `cyberguard-security-observation`，并要求 OCSF/STIX 对齐信息；`scripts/ingest-suricata.py` 已承担具体安全适配职责。司法文书或财务记录不宜为了进入同一系统而被伪装为安全事件。新的文本材料 envelope 保存跨领域共同属性，专业观察与解释由后续阶段产生并引用原文。

[W3C PROV Overview](https://www.w3.org/TR/prov-overview/) 把来源信息组织为实体、活动和责任主体，为记录“哪份材料经哪个过程由谁派生”为何种结果提供通用基础。这里借鉴这种分离，未实现完整 PROV 交换格式。原始材料、提取结果、解释与报告应各有版本和关联，而不是相互覆盖。

## 完整性与身份分开

[NISTIR 8387](https://nvlpubs.nist.gov/nistpubs/ir/2022/NIST.IR.8387.pdf) 讨论数字证据保存及哈希记录的保护。当前内容哈希只能帮助确认保存文本是否变化；导入者重新计算哈希并不能证明文本真实。`cyberguard_investigation/evidence.py` 已明确区分完整性、认证和事实正确性，新接入沿用这一原则。

后续若需要验证设备或 Agent 来源，应将认证主体、验证方法、密钥标识和验证结果由服务器独立记录。[RFC 9421 HTTP Message Signatures](https://www.rfc-editor.org/rfc/rfc9421.html) 提供消息组件签名机制，并强调覆盖组件、内容摘要与重放防护的应用约束。接入签名需要明确被签名的组件、可信密钥管理、时间窗口与 nonce 策略；单独携带签名或自报身份字段不足以建立信任。来源认证成功仍不证明内容事实正确。

## 不可信输入和安全解析

[OWASP File Upload Cheat Sheet](https://cheatsheetseries.owasp.org/cheatsheets/File_Upload_Cheat_Sheet.html) 建议组合使用类型白名单、大小限制、权限控制、安全存储以及适用的恶意文件扫描。当前最小实现只接收有界文本，不解析压缩包、不执行附件、不抓取 URL。未来支持 PDF、Office、OCR 时应另建隔离提取阶段，限制 CPU、内存、页数和展开后字节，保留提取器版本与原件摘要，明确失败或覆盖不足，不能把当前文本入口描述成已经具备这些能力。

[OWASP LLM Prompt Injection Prevention](https://cheatsheetseries.owasp.org/cheatsheets/LLM_Prompt_Injection_Prevention_Cheat_Sheet.html) 说明文档及工具输出也可能携带间接提示注入。材料须保持为不可信数据，不能根据其中的“系统指令”扩展权限。界面应转义原文和报告；分析阶段需要权限边界及输出校验，不能仅依赖提示词要求模型忽略恶意指令。

## 异步请求与可审阅状态

[Microsoft Asynchronous Request-Reply Pattern](https://learn.microsoft.com/en-us/azure/architecture/patterns/asynchronous-request-reply) 描述先校验请求、返回 HTTP 202、以 Location 指向状态资源，并通过 Retry-After 指导轮询。持久化状态应区分排队、处理中、失败与完成；可选进度百分比只在能真实估计时使用。幂等提交、明确错误和阶段记录有助于避免网络重试产生重复任务。该模式是设计依据，不意味着系统使用 Azure 服务。

本地任务持久化与远程 AgentTeams 原生 Task 调度是两个层次。现已将默认后端改为原生 Project/Task：本地保存用户请求，AgentTeams 负责任务规划、委派、验收；Console 保存原生任务 ID、节点状态及最终产物路径。旧 Matrix 串行后端仅保留兼容。

## 可复核引用与专业边界

[W3C Web Annotation Data Model](https://www.w3.org/TR/annotation-model/) 区分注释内容与其目标，并提供文本引用及位置选择器。后续结构化引用可采用材料标识、内容摘要、精确引文和字符位置，并明确所用文本版本。单独引用一个文件名不足以让审阅者复核具体主张；分页/OCR 引用还须明确页码和提取层。

跨领域复用的是接入、来源追踪、执行状态和审阅机制。财务差异、法律含义及司法可采性不能由统一 envelope 或通用 Agent 自动保证；报告应提供引用、冲突与缺失信息，交由适格人员结合任务背景作出专业结论。
