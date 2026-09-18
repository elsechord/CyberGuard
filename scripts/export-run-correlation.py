"""Offline run-correlation one-pager from a gateway data directory (evidence + workflow JSONL).

Correlates, for one incident and optional run, the gateway-side timeline: workflow state
transitions (including human approval waits), evidence collection and metrics. The service
does not need to be running; no action/audit events are read here — those stay with the
executor's authenticated export. Native AgentTeams/Matrix task events are referenced via
docs/LIVE_TASK_EVIDENCE.md and are not covered by this view.
"""
import argparse
import hashlib
import json
import sys
from datetime import UTC, datetime
from pathlib import Path

POINTER_AGENTTEAMS = ("原生 AgentTeams/Matrix 任务事件（不在本视图范围）",
                      "docs/LIVE_TASK_EVIDENCE.md · v0.13.0 参考包 webshell-20260828T163202Z.tar.gz + .sha256")


def digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, ensure_ascii=False,
                                     separators=(",", ":")).encode()).hexdigest()


def read_jsonl(path: Path) -> list[dict]:
    if not path.is_file():
        return []
    records = []
    for line in path.read_text(encoding="utf-8").splitlines():
        if line.strip():
            records.append(json.loads(line))
    return records


def envelope_valid(evidence: dict) -> bool:
    """Same digest contract as app/run_view.py: everything except envelope_sha256."""
    if not evidence.get("envelope_sha256"):
        return False
    payload = {k: v for k, v in evidence.items() if k != "envelope_sha256"}
    return digest(payload) == evidence["envelope_sha256"]


def parse_time(value: str):
    try:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except (TypeError, ValueError):
        return None
    return parsed


def sort_key(entry: dict):
    parsed = entry.get("_parsed")
    return (0, parsed) if parsed is not None else (1, entry.get("time", ""))


def display_time(value: str) -> str:
    parsed = parse_time(value)
    if parsed is None:
        return str(value)
    if parsed.tzinfo is not None and parsed.utcoffset().total_seconds() == 0:
        return parsed.astimezone(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")
    return str(value)


def cell(value, limit: int = 96) -> str:
    text = " ".join(str(value or "").split())
    if len(text) > limit:
        text = text[: limit - 1] + "…"
    return text.replace("|", "\\|")


def timeline_entry_workflow(event: dict) -> dict:
    parsed = parse_time(event.get("recorded_at"))
    previous = event.get("previous_state") or "∅"
    detail = f"{previous} → {event.get('state')}"
    if event.get("requires_human_approval"):
        detail += "（需人工审批）"
    if event.get("terminal"):
        detail += "（终态）"
    message = event.get("message") or ""
    return {"time": event.get("recorded_at"), "_parsed": parsed, "type": "workflow",
            "actor": event.get("actor"), "detail": detail, "message": message,
            "id": event.get("event_id"), "session_id": event.get("session_id"),
            "previous_state": event.get("previous_state")}


def timeline_entry_evidence(evidence: dict) -> dict:
    parsed = parse_time(evidence.get("collected_at"))
    detail = evidence.get("kind", "")
    summary = evidence.get("summary", "")
    return {"time": evidence.get("collected_at"), "_parsed": parsed, "type": "evidence",
            "actor": evidence.get("source"), "detail": detail, "message": summary,
            "id": evidence.get("evidence_id"),
            "quality": evidence.get("quality", {}).get("score"),
            "attack": evidence.get("attack_techniques", []),
            "environment": evidence.get("environment"), "execution": evidence.get("execution")}


def build(incident_id: str, run_id: str | None, data_dir: Path) -> dict:
    all_evidence = [e for e in read_jsonl(data_dir / "evidence.jsonl")
                    if e.get("incident_id") == incident_id]
    workflow_events = [w for w in read_jsonl(data_dir / "workflow.jsonl")
                       if w.get("incident_id") == incident_id]
    evidence = [e for e in all_evidence if run_id is None or e.get("run_id") == run_id]
    excluded = len(all_evidence) - len(evidence)
    run_bindings = sorted({str(e.get("run_id")) for e in all_evidence if e.get("run_id")})
    timeline = [timeline_entry_workflow(w) for w in workflow_events]
    timeline += [timeline_entry_evidence(e) for e in evidence]
    timeline.sort(key=sort_key)
    for entry in timeline:
        entry.pop("_parsed", None)

    sources = sorted({e.get("source") for e in evidence if e.get("source")})
    scores = [float(e.get("quality", {}).get("score", 0)) for e in evidence]
    techniques = sorted({t for e in evidence for t in e.get("attack_techniques", [])})
    entity_sources: dict[str, set[str]] = {}
    for e in evidence:
        for entity in e.get("entities", []):
            entity_sources.setdefault(entity.get("entity_id"), set()).add(e.get("source"))
    sessions: dict[str, dict] = {}
    for event in workflow_events:
        sessions[event.get("session_id")] = event
    envelopes = [{"evidence_id": e.get("evidence_id"),
                  "envelope_sha256": e.get("envelope_sha256"),
                  "valid": envelope_valid(e)} for e in evidence]
    invalid = [item["evidence_id"] for item in envelopes if not item["valid"]]
    effective_run = run_id if run_id is not None else (run_bindings[0] if len(run_bindings) == 1 else None)

    doc = {
        "schema": "cyberguard-run-correlation", "schema_version": "1.0",
        "incident_id": incident_id, "run_id": run_id,
        "generated_at": datetime.now(UTC).isoformat(),
        "data_dir": data_dir.as_posix(), "source_files": {
            "evidence_records": len(all_evidence), "workflow_events": len(workflow_events)},
        "run_scope": {
            "filter": run_id, "evidence_in_scope": len(evidence),
            "evidence_out_of_scope": excluded, "run_bindings_in_incident": run_bindings,
            "workflow_runs_are_incident_scoped": True},
        "timeline": timeline,
        "metrics": {
            "evidence_count": len(evidence), "sources": sources,
            "quality_mean": round(sum(scores) / len(scores), 3) if scores else None,
            "quality_min": min(scores) if scores else None,
            "quality_review_count": sum(e.get("quality", {}).get("gate") == "review" for e in evidence),
            "attack_techniques": techniques,
            "entity_count": len(entity_sources),
            "cross_source_entity_count": sum(len(s) >= 2 for s in entity_sources.values()),
            "workflow_sessions": {sid: {"final_state": ev.get("state"),
                                        "events": sum(1 for w in workflow_events
                                                      if w.get("session_id") == sid)}
                                  for sid, ev in sessions.items()},
            "unresolved_approval_waits": [sid for sid, ev in sessions.items()
                                          if ev.get("state") == "awaiting_approval"]},
        "integrity": {"envelopes_total": len(evidence), "envelopes": envelopes,
                      "envelopes_invalid": invalid,
                      "status": "valid" if evidence and not invalid else
                      ("empty" if not evidence else "invalid")},
        "pointers": [
            {"label": "网关 run 导出（证据 + 经认证行动事件 + export_sha256）",
             "ref": f"GET /incidents/{incident_id}/runs/{effective_run or '<run_id>'}"},
            {"label": "执行器审计链（审批/执行/回滚事件）",
             "ref": f"GET /audit/incidents/{incident_id}/events?run_id={effective_run or '<run_id>'}"
                    "（CYBERGUARD_AUDIT_VERIFY_URL，需审计读者凭据）"},
            {"label": "控制台 run 视图", "ref": "/console"},
            {"label": POINTER_AGENTTEAMS[0], "ref": POINTER_AGENTTEAMS[1]},
        ],
        "boundaries": [
            "本视图离线读取网关数据目录（evidence.jsonl / workflow.jsonl），只关联网关侧证据与工作流；",
            "行动/审批/回滚事件以执行器认证导出为准，本视图仅提供链接位；",
            "workflow 事件按 incident/session 记录且不携带 run_id，run 过滤仅作用于证据；",
            "原生 Matrix/AgentTeams 任务事件（Task、Worker、Skill 调用及版本、模型 usage）不在覆盖范围，"
            "见 docs/LIVE_TASK_EVIDENCE.md。",
        ],
    }
    doc["export_sha256"] = digest(doc)
    return doc


def render_markdown(doc: dict) -> str:
    scope = doc["run_scope"]
    metrics = doc["metrics"]
    integrity = doc["integrity"]
    run_label = doc["run_id"] if doc["run_id"] is not None else (
        scope["run_bindings_in_incident"][0] if len(scope["run_bindings_in_incident"]) == 1
        else "事件级（未指定 run_id）")
    bindings = (f"；事件内出现的 run 绑定：{', '.join(scope['run_bindings_in_incident'])}"
                if scope["run_bindings_in_incident"] else "；证据未记录 run 绑定")
    lines = [
        f"# Run 关联视图 — {doc['incident_id']}", "",
        f"- 生成时间：{doc['generated_at']}",
        f"- 数据目录：`{doc['data_dir']}`（evidence {scope['evidence_in_scope']}"
        f"/{doc['source_files']['evidence_records']} 条在范围内，"
        f"workflow {doc['source_files']['workflow_events']} 条）",
        f"- run 范围：{run_label}{bindings}",
        f"- 证据完整性：{integrity['envelopes_total'] - len(integrity['envelopes_invalid'])}"
        f"/{integrity['envelopes_total']} envelope 校验通过（{integrity['status']}）",
        "",
        "## 时间线（工作流 × 证据采集）", "",
        "| 时间 (UTC) | 类别 | 角色/来源 | 变迁 / Evidence | 说明 | 质量 | ATT&CK |",
        "| --- | --- | --- | --- | --- | --- | --- |",
    ]
    for entry in doc["timeline"]:
        detail = cell(entry["detail"])
        message = cell(entry["message"])
        if entry["type"] == "workflow":
            lines.append(f"| {display_time(entry['time'])} | workflow | {cell(entry['actor'])} "
                         f"| {detail} | {message} | — | — |")
        else:
            quality = entry.get("quality")
            quality = f"{quality:.3f}" if isinstance(quality, (int, float)) else "—"
            lines.append(f"| {display_time(entry['time'])} | evidence | {cell(entry['actor'])} "
                         f"| {detail} `{entry['id']}` | {message} | {quality} "
                         f"| {cell(', '.join(entry.get('attack') or []), 40)} |")
    lines += ["", "## 指标汇总", "",
              f"- 证据：{metrics['evidence_count']} 条，独立来源 {len(metrics['sources'])} 个"
              + (f"（{', '.join(metrics['sources'])}）" if metrics["sources"] else ""),
              f"- 质量：均值 {metrics['quality_mean']} / 最低 {metrics['quality_min']}"
              f"；review 门 {metrics['quality_review_count']} 条",
              f"- ATT&CK：{', '.join(metrics['attack_techniques']) or '—'}",
              f"- 实体：{metrics['entity_count']} 个，其中跨源印证 {metrics['cross_source_entity_count']} 个"]
    for session_id, info in metrics["workflow_sessions"].items():
        lines.append(f"- 工作流会话 `{session_id}`：{info['events']} 次变迁，终态 `{info['final_state']}`"
                     + ("（未决人工审批等待）" if session_id in metrics["unresolved_approval_waits"]
                        else ""))
    lines += ["", "## 证据完整性", "",
              "| Evidence ID | Envelope SHA-256 | 状态 |", "| --- | --- | --- |"]
    for item in integrity["envelopes"]:
        lines.append(f"| `{item['evidence_id']}` | `{item['envelope_sha256']}` | "
                     f"{'valid' if item['valid'] else 'invalid'} |")
    lines += ["", "## 链接位（审计链与复现材料）", ""]
    lines += [f"- {pointer['label']}：`{pointer['ref']}`" for pointer in doc["pointers"]]
    lines += ["", "## 边界（诚实声明）", ""]
    lines += [f"{i}. {text}" for i, text in enumerate(doc["boundaries"], start=1)]
    lines += ["", f"导出摘要 `export_sha256`：`{doc['export_sha256']}`（覆盖除自身外全部字段）", ""]
    return "\n".join(lines)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("incident_id", help="e.g. CG-2026-0002")
    parser.add_argument("--data-dir", type=Path, default=Path("/data"),
                        help="gateway data directory containing evidence.jsonl / workflow.jsonl")
    parser.add_argument("--run-id", default=None,
                        help="filter evidence to one run; omit for incident-wide correlation")
    parser.add_argument("--output", type=Path, help="write the Markdown one-pager here")
    parser.add_argument("--json-output", type=Path, help="write the structured correlation JSON here")
    args = parser.parse_args()
    doc = build(args.incident_id, args.run_id, args.data_dir)
    markdown = render_markdown(doc)
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(markdown, encoding="utf-8")
    if args.json_output:
        args.json_output.parent.mkdir(parents=True, exist_ok=True)
        args.json_output.write_text(
            json.dumps(doc, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    if not args.output and not args.json_output:
        print(markdown, end="")
    print(json.dumps({"incident_id": doc["incident_id"], "run_id": doc["run_id"],
                      "evidence_in_scope": doc["run_scope"]["evidence_in_scope"],
                      "workflow_events": doc["source_files"]["workflow_events"],
                      "integrity": doc["integrity"]["status"],
                      "markdown": str(args.output) if args.output else None,
                      "json": str(args.json_output) if args.json_output else None,
                      "export_sha256": doc["export_sha256"]}))


if __name__ == "__main__":
    main()
