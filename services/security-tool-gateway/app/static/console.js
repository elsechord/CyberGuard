const state = { token: sessionStorage.getItem("cyberguardReadToken") || "", selected: null, detail: null, run: null, export: null, exportText: null, runRequest: 0 };
const $ = (id) => document.getElementById(id);

function node(tag, className, text) {
  const item = document.createElement(tag);
  if (className) item.className = className;
  if (text !== undefined) item.textContent = text;
  return item;
}

async function api(path, raw = false) {
  const response = await fetch(path, { headers: { Authorization: `Bearer ${state.token}` }, cache: "no-store" });
  if (response.status === 401) throw new Error("令牌无效或已失效");
  if (!response.ok) throw new Error(`接口返回 ${response.status}`);
  return raw ? response.text() : response.json();
}

function setConnected(connected) {
  $("connection").className = `connection ${connected ? "online" : "offline"}`;
  $("connection").lastChild.textContent = connected ? "只读链路正常" : "未连接";
}

async function connect() {
  try {
    const data = await api("/incidents");
    sessionStorage.setItem("cyberguardReadToken", state.token);
    $("auth-panel").classList.add("hidden");
    $("workspace").classList.remove("hidden");
    $("auth-error").textContent = "";
    setConnected(true);
    renderIncidents(data.incidents);
  } catch (error) {
    setConnected(false);
    $("auth-error").textContent = error.message;
  }
}

function renderIncidents(incidents) {
  const list = $("incident-list");
  list.replaceChildren();
  $("incident-count").textContent = String(incidents.length);
  if (!incidents.length) {
    $("empty-state").classList.remove("hidden");
    $("incident-detail").classList.add("hidden");
    list.append(node("p", "hero-copy", "暂无事件"));
    return;
  }
  incidents.forEach((incident) => {
    const button = node("button", `incident-card${state.selected === incident.incident_id ? " active" : ""}`);
    button.type = "button";
    button.append(node("strong", "", incident.incident_id));
    const quality = incident.quality_mean == null ? "待评估" : `质量 ${Math.round(incident.quality_mean * 100)}%`;
    const scope = incident.run_count ? `${incident.run_count} 次运行` : statusLabel(incident.status);
    button.append(node("span", "", `${scope} · ${incident.evidence_count} 条证据 · ${quality}`));
    button.addEventListener("click", () => selectIncident(incident.incident_id));
    list.append(button);
  });
  const available = incidents.some((item) => item.incident_id === state.selected);
  selectIncident(available ? state.selected : incidents[0].incident_id);
}

async function selectIncident(incidentId) {
  state.selected = incidentId;
  ++state.runRequest;
  state.export = null;
  state.exportText = null;
  $("export-run").disabled = true;
  $("export-preview").classList.add("hidden");
  $("export-json").value = "";
  try {
    const [detail, graph, quality] = await Promise.all([
      api(`/incidents/${encodeURIComponent(incidentId)}`),
      api(`/incidents/${encodeURIComponent(incidentId)}/graph`).catch(() => ({ nodes: [], edges: [] })),
      api(`/incidents/${encodeURIComponent(incidentId)}/quality`).catch(() => ({ quality_mean: 0, quality_min: 0, gate: "review" })),
    ]);
    if (state.selected !== incidentId) return;
    renderDetail(detail, graph, quality);
    document.querySelectorAll(".incident-card").forEach((card) => {
      card.classList.toggle("active", card.querySelector("strong").textContent === incidentId);
    });
  } catch (error) {
    setConnected(false);
  }
}

function statusLabel(status) {
  if (status === "execution_rejected") return "对象已变化或不在允许范围，执行被拒绝";
  const labStates = { execution_dispatched: "执行已发出，等待回执", execution_unknown: "执行结果未知，等待对账", rollback_dispatched: "回滚已发出", rollback_unknown: "回滚结果未知", inconclusive: "证据不足", verified: "观测通过", failed: "验证未通过" };
  if (labStates[status]) return labStates[status];
  return ({ received: "已接收", investigating: "调查中", evidence_validation: "证据校验", timed_out: "会话超时", failed: "失败", rejected: "已拒绝", completed: "已完成", executing: "执行中", pending_approval: "等待审批", awaiting_approval: "等待审批", approved: "已批准", executed: "已执行", responding: "响应中", verified: "已验证", rolled_back: "已回滚", audit_error: "审计异常", audit_corruption: "审计损坏" })[status] || status;
}

function renderDetail(detail, graph, quality) {
  state.detail = detail;
  $("empty-state").classList.add("hidden");
  $("incident-detail").classList.remove("hidden");
  $("detail-id").textContent = detail.summary.incident_id;
  $("detail-status").textContent = statusLabel(detail.summary.status);
  $("detail-status").className = `status-pill ${detail.summary.status}`;
  $("metric-evidence").textContent = detail.evidence.length;
  $("metric-sources").textContent = detail.summary.sources.length;
  $("metric-actions").textContent = detail.summary.action_count;
  $("metric-quality").textContent = `${Math.round(quality.quality_mean * 100)}%`;
  $("metric-quality").title = `最低 ${Math.round(quality.quality_min * 100)}% · ${quality.gate}`;
  renderEvidence(detail.evidence);
  renderActions(detail.actions);
  renderWorkflow(detail.workflow);
  renderGraph(graph);
  const selector = $("run-select");
  selector.replaceChildren(new Option("事件汇总 · 包含历史及未绑定运行的数据", ""));
  (detail.runs || []).forEach((id) => selector.add(new Option(id, id)));
  const previous = state.run;
  state.run = (detail.runs || []).includes(previous) ? previous : detail.evidence.slice().reverse().find((e) => e.run_id)?.run_id || "";
  selector.value = state.run;
  renderSelectedRun();
}

async function renderSelectedRun() {
  const request = ++state.runRequest;
  state.export = null;
  state.exportText = null;
  $("export-run").disabled = true;
  $("export-preview").classList.add("hidden");
  $("export-json").value = "";
  $("run-states").replaceChildren();
  $("run-notice").className = "run-notice";
  const detail = state.detail;
  document.querySelector(".graph-panel").classList.toggle("hidden", Boolean(state.run));
  document.querySelector(".workflow-panel").classList.toggle("hidden", Boolean(state.run));
  if (!state.run) {
    $("run-notice").textContent = "事件汇总不代表同一次任务。请选择运行编号查看关联的动作和探针；历史 fixture 结果仅用于模拟契约验证。";
    renderEvidence(detail.evidence); renderActions(detail.actions);
    $("metric-evidence").textContent = detail.evidence.length;
    $("metric-actions").textContent = detail.summary.action_count;
    $("metric-sources").textContent = detail.summary.sources.length;
    $("metric-quality").textContent = detail.summary.quality_mean == null ? "—" : `${Math.round(detail.summary.quality_mean * 100)}%`;
    $("detail-status").textContent = "事件汇总";
    return;
  }
  $("run-notice").textContent = "正在读取本次运行的证据与认证审计快照…";
  $("detail-status").textContent = "读取中";
  renderEvidence([]); renderActions([]);
  for (const metric of ["metric-evidence", "metric-actions", "metric-sources", "metric-quality"]) $(metric).textContent = "—";
  try {
    const exportText = await api(`/incidents/${encodeURIComponent(state.selected)}/runs/${encodeURIComponent(state.run)}`, true);
    const data = JSON.parse(exportText);
    if (request !== state.runRequest) return;
    state.export = data;
    state.exportText = exportText;
    $("export-run").disabled = false;
    const modes = [...new Set(data.action_states.map((a) => a.execution_mode))];
    const models = [...new Set(data.action_states.map((a) => a.model_mode))];
    const modeText = modes.map((m) => m === "host_lab" ? "Linux 进程实验 · 真实状态变化" : m === "lab" ? "账户隔离实验 · 真实状态变化" : "模拟执行").join(" / ") || "尚无可核验动作";
    $("run-notice").textContent = `${modeText}。模型模式（调用方声明）：${models.join(" / ") || "未知"}。审计快照：${data.audit_status === "valid" ? "已由执行器校验" : "不可用"}；证据完整性：${data.evidence_integrity === "valid" ? "通过" : "异常"}。探针结果仅代表记录的观测时刻，页面刷新不会重测。AgentTeams 任务及 Worker/Skill 对应关系尚未核验。`;
    if (data.audit_status !== "valid" || data.evidence_integrity !== "valid") $("run-notice").classList.add("error");
    $("detail-status").textContent = data.audit_status !== "valid" || data.evidence_integrity !== "valid" ? "证据待核验" : "运行记录";
    renderEvidence(data.evidence); renderActions(data.actions);
    $("metric-evidence").textContent = data.evidence.length;
    $("metric-actions").textContent = data.action_states.length;
    $("metric-sources").textContent = new Set(data.evidence.map((e) => e.source)).size;
    const scores = data.evidence.map((e) => e.quality?.score || 0);
    $("metric-quality").textContent = scores.length ? `${Math.round(scores.reduce((a,b) => a+b, 0) / scores.length * 100)}%` : "—";
    data.action_states.forEach((item) => {
      const card = node("article", "action-item");
      card.append(node("strong", "", `${item.action_id} · ${item.target}`));
      card.append(node("p", "", `${statusLabel(item.status)} · 验证：${statusLabel(item.verification)}`));
      if (item.observation) card.append(node("p", "probe-check", `最近观测 ${new Date(item.observation.collected_at).toLocaleString("zh-CN", {hour12: false})} · ${item.observation.evidence_id}`));
      $("run-states").append(card);
    });
  } catch (error) {
    if (request !== state.runRequest) return;
    $("run-notice").textContent = `无法读取本次运行：${error.message}`;
    $("run-notice").classList.add("error");
    $("detail-status").textContent = "读取失败";
  }
}

function renderWorkflow(workflow) {
  const list = $("workflow-list"), alert = $("approval-alert");
  const sessions = workflow?.sessions || [], approvals = workflow?.awaiting_approval || [];
  list.replaceChildren();
  alert.classList.toggle("hidden", approvals.length === 0);
  alert.textContent = approvals.length ? `等待你审批 · ${approvals.length}` : "无需审批";
  if (!sessions.length) { list.append(node("p", "hero-copy", "尚无 Agent 会话状态。")); return; }
  sessions.slice().reverse().forEach((item) => {
    const article = node("article", `action-item ${item.state}`), header = node("header");
    header.append(node("strong", "", item.session_id), node("time", "", new Date(item.recorded_at).toLocaleTimeString("zh-CN", { hour12: false })));
    article.append(header, node("p", "", `${statusLabel(item.state)} · ${item.actor}${item.message ? ` · ${item.message}` : ""}`));
    if (item.requires_human_approval) article.append(node("span", "tag", "需要人工审批"));
    list.append(article);
  });
}

function renderEvidence(items) {
  const list = $("evidence-list");
  list.replaceChildren();
  items.slice().reverse().forEach((item) => {
    const article = node("article", "timeline-item");
    const header = node("header");
    header.append(node("strong", "", `${item.kind} · ${item.source}`));
    const time = node("time", "", new Date(item.collected_at).toLocaleString("zh-CN", { hour12: false }));
    header.append(time);
    article.append(header, node("p", "", item.summary));
    const tags = node("div", "tags");
    tags.append(node("span", "tag", item.evidence_id), node("span", "tag", `置信度 ${Math.round(item.confidence * 100)}%`));
    tags.append(node("span", "tag", `质量 ${Math.round((item.quality?.score || 0) * 100)}%`));
    (item.attack_techniques || []).forEach((value) => tags.append(node("span", "tag", value)));
    [...(item.supports || []), ...(item.contradicts || [])].forEach((value) => tags.append(node("span", "tag", value)));
    article.append(tags);
    if (item.run_id) article.append(node("p", "probe-check", `运行 ${item.run_id} · ${item.environment || "unknown"} / ${item.execution || "unknown"}`));
    if (item.data?.verification_scope === "simulated_response_contract") article.append(node("p", "probe-check", "模拟契约结果 · 未观测真实环境恢复"));
    if (item.environment === "lab" && item.kind === "recovery_metrics") {
      article.append(node("p", "probe-check", `观测结论：${statusLabel(item.data?.verdict || "inconclusive")} · ${item.data?.reason || "—"}`));
      (item.data?.checks || []).forEach((check) => {
        if (Array.isArray(check.processes)) {
          const target = check.processes.find((p) => p.role === "compute");
          const control = check.processes.find((p) => p.role === "control");
          article.append(node("p", "probe-check", `${check.observed_at} · 目标进程 ${target ? `PID ${target.pid}` : "未观测到"} · 持久化 ${check.persistence?.present ? "仍存在" : "不存在"} · 正常进程 heartbeat ${control?.heartbeat?.sequence ?? "不可用"}`));
        } else {
          article.append(node("p", "probe-check", `${check.account}：${check.allowed ? "允许访问" : "拒绝访问"} · HTTP ${check.http_status} · ${check.observed_at}`));
        }
      });
    }
    if (item.scenario_id === "lab_host") {
      const detail = node("details", "probe-check");
      detail.append(node("summary", "", "查看 Linux 实验原始观测（无害进程，不是真实入侵）"));
      const raw = node("pre", "", JSON.stringify(item.data, null, 2));
      raw.style.whiteSpace = "pre-wrap";
      raw.style.overflowWrap = "anywhere";
      detail.append(raw);
      article.append(detail);
    }
    list.append(article);
  });
}

function renderActions(items) {
  const list = $("action-list");
  list.replaceChildren();
  if (!items.length) {
    list.append(node("p", "hero-copy", "尚无响应行动。调查 Agent 保持只读。"));
    return;
  }
  items.slice().reverse().forEach((item) => {
    const article = node("article", `action-item ${item.status || ""}`);
    const header = node("header");
    header.append(node("strong", "", item.action || item.status || "审计事件"));
    header.append(node("time", "", item.recorded_at ? new Date(item.recorded_at).toLocaleTimeString("zh-CN", { hour12: false }) : `Line ${item.line || "-"}`));
    article.append(header);
    article.append(node("p", "", `${statusLabel(item.status || "unknown")}${item.target ? ` · ${item.target}` : ""}${item.approver ? ` · 审批人 ${item.approver}` : ""}`));
    const tags = node("div", "tags");
    if (item.action_id) tags.append(node("span", "tag", item.action_id));
    if (item.risk) tags.append(node("span", "tag", item.risk));
    if (item.record_sha256) tags.append(node("span", "tag", `SHA ${item.record_sha256.slice(0, 10)}`));
    article.append(tags);
    list.append(article);
  });
}

function renderGraph(graph) {
  const svg = $("graph");
  svg.replaceChildren();
  const typeX = { source: 70, evidence: 250, entity: 450, observable: 650, attack_technique: 830, hypothesis: 1010, incident: 1190, action: 1370 };
  const grouped = {};
  graph.nodes.forEach((item) => { (grouped[item.type] ||= []).push(item); });
  const positions = new Map();
  Object.entries(grouped).forEach(([type, items]) => {
    const gap = Math.min(78, 330 / Math.max(items.length, 1));
    const start = 42 + (330 - gap * Math.max(items.length - 1, 0)) / 2;
    items.forEach((item, index) => positions.set(item.id, { x: typeX[type] || 600, y: start + index * gap }));
  });
  const NS = "http://www.w3.org/2000/svg";
  graph.edges.forEach((edge) => {
    const a = positions.get(edge.source), b = positions.get(edge.target);
    if (!a || !b) return;
    const line = document.createElementNS(NS, "line");
    line.setAttribute("x1", a.x); line.setAttribute("y1", a.y); line.setAttribute("x2", b.x); line.setAttribute("y2", b.y);
    line.setAttribute("stroke", edge.type === "contradicts" ? "#ff6b6b" : "#29413a");
    line.setAttribute("stroke-width", edge.type === "contradicts" ? "2" : "1");
    if (edge.type === "contradicts") line.setAttribute("stroke-dasharray", "5 5");
    svg.append(line);
  });
  const colors = { source: "#5aa9ff", evidence: "#50e3c2", entity: "#9b8cff", observable: "#68d5ff", attack_technique: "#ff7b72", hypothesis: "#ffad5a", incident: "#e9f4ef", action: "#b8f34a" };
  graph.nodes.forEach((item) => {
    const p = positions.get(item.id); if (!p) return;
    const circle = document.createElementNS(NS, "circle");
    circle.setAttribute("cx", p.x); circle.setAttribute("cy", p.y); circle.setAttribute("r", item.type === "incident" ? "10" : "6"); circle.setAttribute("fill", colors[item.type] || "#fff");
    svg.append(circle);
    const label = document.createElementNS(NS, "text");
    label.setAttribute("x", p.x + 11); label.setAttribute("y", p.y + 4); label.setAttribute("fill", "#b9cbc5"); label.setAttribute("font-size", "10");
    label.textContent = String(item.label || item.id).slice(0, 28);
    svg.append(label);
  });
}

$("auth-form").addEventListener("submit", (event) => {
  event.preventDefault(); state.token = $("token").value.trim(); connect();
});
$("refresh").addEventListener("click", () => { if (state.token) connect(); });
$("run-select").addEventListener("change", () => { state.run = $("run-select").value; renderSelectedRun(); });
$("export-run").addEventListener("click", () => {
  if (!state.export || !state.exportText) return;
  // Preserve numeric tokens (e.g. 1.0) used by the server's integrity digest.
  const json = state.exportText + "\n";
  $("export-json").value = json;
  $("export-preview").classList.remove("hidden");
  $("export-preview").open = true;
  const url = URL.createObjectURL(new Blob([json], {type: "application/json"}));
  const link = document.createElement("a"); link.href = url;
  link.download = `cyberguard-run-${state.export.run_id.replace(/[^a-zA-Z0-9_-]/g, "_")}.json`;
  link.hidden = true;
  document.body.append(link);
  link.click(); link.remove(); setTimeout(() => URL.revokeObjectURL(url), 1000);
});
if (state.token) { $("token").value = state.token; connect(); }
