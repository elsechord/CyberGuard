import hashlib
import json
import os
from datetime import UTC, datetime
from pathlib import Path
from threading import Lock
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import quote
from urllib.request import Request, urlopen
from uuid import uuid4

from .connectors import ConnectorError, live_connectors
from .models import Evidence
from .normalization import normalize
from . import lab_verification, host_lab


class ScenarioStore:
    WORKFLOW_TRANSITIONS = {
        None: {"received"},
        "received": {"investigating", "failed", "timed_out"},
        "investigating": {"evidence_validation", "failed", "timed_out"},
        "evidence_validation": {"awaiting_approval", "completed", "failed"},
        "awaiting_approval": {"approved", "rejected", "timed_out"},
        "approved": {"executing", "failed"},
        "executing": {"completed", "failed"},
        "timed_out": {"investigating", "failed"},
        "failed": {"investigating"},
        "rejected": set(),
        "completed": set(),
    }
    def __init__(self) -> None:
        self.scenario_dir = Path(os.getenv("CYBERGUARD_SCENARIO_DIR", "/app/scenarios"))
        self.data_dir = Path(os.getenv("CYBERGUARD_DATA_DIR", "/data"))
        self.data_dir.mkdir(parents=True, exist_ok=True)
        self.action_audit_file = Path(os.getenv("CYBERGUARD_ACTION_AUDIT_FILE", "/actions/actions.jsonl"))
        self._lock = Lock()

    def load(self, scenario_id: str) -> dict[str, Any]:
        safe_name = Path(scenario_id).name
        path = self.scenario_dir / f"{safe_name}.json"
        if not path.is_file():
            raise FileNotFoundError(scenario_id)
        return json.loads(path.read_text(encoding="utf-8"))

    def collect(
        self,
        *,
        incident_id: str,
        scenario_id: str,
        tool: str,
        arguments: dict[str, Any] | None = None,
        run_id: str | None = None,
    ) -> Evidence:
        argument_run = (arguments or {}).get("run_id")
        if argument_run is not None and (not isinstance(argument_run, str) or not 3 <= len(argument_run) <= 128):
            raise ValueError("invalid run_id")
        if run_id is not None and argument_run is not None and run_id != argument_run:
            raise ValueError("conflicting run_id fields")
        run_id = run_id or argument_run
        if scenario_id == "lab_host":
            if not run_id:
                raise ValueError("lab_host requires run_id")
            try:
                if tool == "endpoint.timeline":
                    record = host_lab.collect()
                elif tool == "recovery.metrics":
                    record = host_lab.verify(incident_id, {**(arguments or {}), "run_id": run_id})
                else:
                    raise KeyError(tool)
            except lab_verification.ProbeError as exc:
                raise ConnectorError(str(exc)) from None
        elif scenario_id == "lab_identity":
            if tool != "recovery.metrics":
                raise KeyError(tool)
            try:
                record = lab_verification.verify(incident_id, {**(arguments or {}), "run_id": run_id})
            except lab_verification.ProbeError as exc:
                raise ConnectorError(str(exc)) from None
        elif scenario_id == "live":
            record = live_connectors.invoke(tool, arguments or {})
        else:
            scenario = self.load(scenario_id)
            tools = scenario.get("tools", {})
            if tool not in tools:
                raise KeyError(tool)
            record = tools[tool]
        if tool == "recovery.metrics" and scenario_id not in {"live", "lab_identity", "lab_host"}:
            record = self._recovery_record(record, incident_id)
            record["data"]["verification_scope"] = "simulated_response_contract"
            record["data"]["execution"] = "simulated"
        elif tool == "recovery.metrics" and scenario_id == "live":
            # A live connector needs its own validated outcome contract. Do not
            # overwrite observations with a fixture/action-set success verdict.
            record["data"]["reported_verdict"] = record["data"].get("verdict")
            record["data"]["verdict"] = "inconclusive"
            record["data"]["reason"] = "live_verifier_contract_not_validated"
        now = datetime.now(UTC).isoformat()
        canonical = json.dumps(record, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
        digest = hashlib.sha256(canonical.encode("utf-8")).hexdigest()
        normalized = normalize(tool, record, digest)
        minimum_quality = float(os.getenv("CYBERGUARD_MIN_EVIDENCE_QUALITY", "0.7"))
        if scenario_id == "live" and normalized["quality"]["score"] < minimum_quality:
            issues = ",".join(normalized["quality"]["issues"])
            raise ConnectorError(
                f"normalized evidence failed quality gate ({normalized['quality']['score']:.3f}"
                f" < {minimum_quality:.3f}): {issues}"
            )
        evidence = Evidence(
            evidence_id=f"EV-{uuid4().hex[:12]}",
            incident_id=incident_id,
            run_id=run_id,
            scenario_id=scenario_id,
            tool_call_id=f"CALL-{uuid4().hex}",
            environment="lab" if scenario_id in {"lab_identity", "lab_host"} else "live" if scenario_id == "live" else "fixture",
            execution="real" if scenario_id in {"lab_identity", "lab_host"} else "unknown" if scenario_id == "live" else "simulated",
            source=record.get("source", tool),
            collected_at=now,
            observed_at=record.get("observed_at"),
            kind=record.get("kind", tool),
            summary=record.get("summary", ""),
            data=record.get("data", {}),
            sha256=digest,
            confidence=float(record.get("confidence", 0.8)),
            supports=record.get("supports", []),
            contradicts=record.get("contradicts", []),
            handling=record.get("handling", "internal"),
            **normalized,
        )
        envelope = evidence.model_dump(exclude={"envelope_sha256"})
        evidence.envelope_sha256 = hashlib.sha256(json.dumps(
            envelope, sort_keys=True, ensure_ascii=False, separators=(",", ":")
        ).encode()).hexdigest()
        self._append(evidence)
        return evidence

    def list_evidence(self, incident_id: str) -> list[dict[str, Any]]:
        with self._lock:
            path = self.data_dir / "evidence.jsonl"
            if not path.exists():
                return []
            records = []
            for line in path.read_text(encoding="utf-8").splitlines():
                if not line:
                    continue
                record = json.loads(line)
                if record.get("incident_id") == incident_id:
                    records.append(record)
            return records

    def transition_workflow(self, incident_id: str, session_id: str, state: str,
                            actor: str, message: str = "") -> dict[str, Any]:
        current = self.workflow(incident_id, session_id)
        previous = current["state"] if current else None
        if state not in self.WORKFLOW_TRANSITIONS.get(previous, set()):
            raise ValueError(f"invalid workflow transition: {previous} -> {state}")
        event = {
            "event_id": f"WF-{uuid4().hex[:12]}", "incident_id": incident_id,
            "session_id": session_id, "previous_state": previous, "state": state,
            "actor": actor, "message": message, "recorded_at": datetime.now(UTC).isoformat(),
            "requires_human_approval": state == "awaiting_approval",
            "terminal": state in {"completed", "rejected", "failed"},
        }
        path = self.data_dir / "workflow.jsonl"
        with self._lock, path.open("a", encoding="utf-8") as stream:
            stream.write(json.dumps(event, ensure_ascii=False, separators=(",", ":")) + "\n")
        return event

    def workflow(self, incident_id: str, session_id: str | None = None) -> dict[str, Any] | None:
        path = self.data_dir / "workflow.jsonl"
        if not path.exists():
            return None
        events = []
        with self._lock:
            for line in path.read_text(encoding="utf-8").splitlines():
                item = json.loads(line)
                if item.get("incident_id") == incident_id and (
                    session_id is None or item.get("session_id") == session_id
                ):
                    events.append(item)
        if not events:
            return None
        sessions: dict[str, dict[str, Any]] = {}
        for item in events:
            sessions[item["session_id"]] = item
        if session_id is not None:
            return {"incident_id": incident_id, "session_id": session_id,
                    "state": events[-1]["state"], "events": events}
        return {"incident_id": incident_id, "sessions": list(sessions.values()),
                "awaiting_approval": [x for x in sessions.values()
                                      if x["state"] == "awaiting_approval"], "events": events}

    def validate_evidence_ids(self, incident_id: str, evidence_ids: list[str]) -> dict[str, Any]:
        """Fail closed for report citations that do not exist in the incident store."""
        known = {item["evidence_id"]: item for item in self.list_evidence(incident_id)}
        requested = list(dict.fromkeys(evidence_ids))
        resolved = [known[item] for item in requested if item in known]
        unknown = [item for item in requested if item not in known]
        return {
            "incident_id": incident_id,
            "valid": not unknown,
            "requested_count": len(requested),
            "resolved_count": len(resolved),
            "unknown_evidence_ids": unknown,
            "resolved": resolved,
        }

    def list_actions(self, incident_id: str) -> list[dict[str, Any]]:
        if not self.action_audit_file.exists():
            return []
        records = []
        for line_number, line in enumerate(
            self.action_audit_file.read_text(encoding="utf-8").splitlines(), start=1
        ):
            if not line:
                continue
            try:
                record = json.loads(line)
            except json.JSONDecodeError:
                records.append(
                    {"incident_id": incident_id, "status": "audit_corruption", "line": line_number}
                )
                continue
            if record.get("incident_id") == incident_id:
                records.append(record)
        return records

    def list_incidents(self) -> list[dict[str, Any]]:
        path = self.data_dir / "evidence.jsonl"
        incident_ids = set()
        with self._lock:
            if path.exists():
                for line in path.read_text(encoding="utf-8").splitlines():
                    if line:
                        incident_ids.add(json.loads(line).get("incident_id"))
            workflow_path = self.data_dir / "workflow.jsonl"
            if workflow_path.exists():
                for line in workflow_path.read_text(encoding="utf-8").splitlines():
                    if line:
                        incident_ids.add(json.loads(line).get("incident_id"))
        return [self.incident_summary(item) for item in sorted(incident_ids) if item]

    def incident_summary(self, incident_id: str) -> dict[str, Any]:
        evidence = self.list_evidence(incident_id)
        actions = self.list_actions(incident_id)
        statuses = [item.get("status") for item in actions]
        if "audit_corruption" in statuses:
            status = "audit_error"
        elif "rolled_back" in statuses:
            status = "rolled_back"
        elif (evidence and evidence[-1].get("kind") == "recovery_metrics"
              and evidence[-1].get("data", {}).get("verdict") == "verified"
              and "executed" in statuses):
            status = "verified"
        elif "executed" in statuses:
            status = "responding"
        elif "pending_approval" in statuses:
            status = "awaiting_approval"
        else:
            status = "investigating"
        entity_sources: dict[str, set[str]] = {}
        for item in evidence:
            for entity in item.get("entities", []):
                entity_sources.setdefault(entity["entity_id"], set()).add(item["source"])
        quality_scores = [float(item.get("quality", {}).get("score", 0)) for item in evidence]
        return {
            "incident_id": incident_id,
            "status": status,
            "evidence_count": len(evidence),
            "run_count": len({e["run_id"] for e in evidence if e.get("run_id")}),
            "action_count": len({item.get("action_id") for item in actions if item.get("action_id")}),
            "sources": sorted({item.get("source") for item in evidence if item.get("source")}),
            "last_updated": evidence[-1].get("collected_at") if evidence else None,
            "entity_count": len(entity_sources),
            "cross_source_entity_count": sum(len(sources) >= 2 for sources in entity_sources.values()),
            "attack_techniques": sorted({technique for item in evidence for technique in item.get("attack_techniques", [])}),
            "quality_mean": round(sum(quality_scores) / len(quality_scores), 3) if quality_scores else None,
            "quality_review_count": sum(item.get("quality", {}).get("gate") == "review" for item in evidence),
        }

    def incident_quality(self, incident_id: str) -> dict[str, Any]:
        evidence = self.list_evidence(incident_id)
        if not evidence:
            return {"incident_id": incident_id, "evidence_count": 0, "gate": "review", "issues": ["no_evidence"]}
        sources = {item["source"] for item in evidence}
        scores = [float(item["quality"]["score"]) for item in evidence]
        issue_counts: dict[str, int] = {}
        for item in evidence:
            for issue in item["quality"]["issues"]:
                issue_counts[issue] = issue_counts.get(issue, 0) + 1
        gate = "pass" if len(sources) >= 3 and min(scores) >= 0.7 else "review"
        return {
            "incident_id": incident_id, "evidence_count": len(evidence), "source_count": len(sources),
            "quality_mean": round(sum(scores) / len(scores), 3), "quality_min": min(scores),
            "gate": gate, "issue_counts": dict(sorted(issue_counts.items())),
        }

    def incident_graph(self, incident_id: str) -> dict[str, Any]:
        evidence = self.list_evidence(incident_id)
        actions = self.list_actions(incident_id)
        nodes: dict[str, dict[str, Any]] = {
            incident_id: {"id": incident_id, "type": "incident", "label": incident_id}
        }
        edges: list[dict[str, str]] = []
        for item in evidence:
            source_id = f'source:{item["source"]}'
            nodes[source_id] = {"id": source_id, "type": "source", "label": item["source"]}
            nodes[item["evidence_id"]] = {
                "id": item["evidence_id"],
                "type": "evidence",
                "label": item["kind"],
                "summary": item["summary"],
                "confidence": item["confidence"],
            }
            edges.append({"source": source_id, "target": item["evidence_id"], "type": "produced"})
            edges.append({"source": item["evidence_id"], "target": incident_id, "type": "belongs_to"})
            for entity in item.get("entities", []):
                nodes[entity["entity_id"]] = {
                    "id": entity["entity_id"], "type": "entity", "entity_type": entity["type"],
                    "label": entity["value"],
                }
                edges.append({"source": item["evidence_id"], "target": entity["entity_id"], "type": "mentions"})
            for observable in item.get("observables", []):
                nodes[observable["observable_id"]] = {
                    "id": observable["observable_id"], "type": "observable",
                    "observable_type": observable["stix_type"], "label": observable["value"],
                }
                edges.append({"source": item["evidence_id"], "target": observable["observable_id"], "type": "observed"})
            for technique in item.get("attack_techniques", []):
                technique_id = f"attack:{technique}"
                nodes[technique_id] = {"id": technique_id, "type": "attack_technique", "label": technique}
                edges.append({"source": item["evidence_id"], "target": technique_id, "type": "maps_to"})
            for relation, edge_type in (("supports", "supports"), ("contradicts", "contradicts")):
                for hypothesis in item.get(relation, []):
                    nodes[hypothesis] = {
                        "id": hypothesis,
                        "type": "hypothesis",
                        "label": hypothesis,
                    }
                    edges.append(
                        {"source": item["evidence_id"], "target": hypothesis, "type": edge_type}
                    )
        action_edges: set[str] = set()
        for item in actions:
            action_id = item.get("action_id")
            if not action_id:
                continue
            nodes[action_id] = {
                "id": action_id,
                "type": "action",
                "label": item.get("action", action_id),
                "status": item.get("status"),
            }
            if action_id not in action_edges:
                edges.append({"source": incident_id, "target": action_id, "type": "responded_with"})
                action_edges.add(action_id)
        return {"incident_id": incident_id, "nodes": list(nodes.values()), "edges": edges}

    def _recovery_record(self, base: dict[str, Any], incident_id: str) -> dict[str, Any]:
        verify_url = os.getenv("CYBERGUARD_AUDIT_VERIFY_URL", "").rstrip("/")
        if verify_url:
            token = os.getenv("CYBERGUARD_AUDIT_READER_TOKEN", "")
            request = Request(
                f"{verify_url}/audit/incidents/{quote(incident_id, safe='')}/active",
                headers={"Authorization": f"Bearer {token}", "Accept": "application/json"},
            )
            try:
                with urlopen(request, timeout=5) as response:
                    verified = json.loads(response.read().decode("utf-8"))
            except (HTTPError, URLError, TimeoutError, UnicodeDecodeError, json.JSONDecodeError):
                return self._inconclusive_recovery(base, "authenticated_audit_unavailable")
            return self._evaluate_required_response(base, verified.get("active_actions", []))

        events: list[dict[str, Any]] = []
        if self.action_audit_file.exists():
            for line in self.action_audit_file.read_text(encoding="utf-8").splitlines():
                if line:
                    event = json.loads(line)
                    if event.get("incident_id") == incident_id:
                        events.append(event)

        active_actions: dict[str, dict[str, Any]] = {}
        for event in events:
            action_id = event.get("action_id")
            if not action_id:
                continue
            if event.get("status") == "executed":
                active_actions[action_id] = event
            elif event.get("status") == "rolled_back":
                active_actions.pop(action_id, None)

        return self._evaluate_required_response(base, list(active_actions.values()))

    @staticmethod
    def _evaluate_required_response(base: dict[str, Any], active: list[dict[str, Any]]) -> dict[str, Any]:
        required = base.get("required_actions")
        if not isinstance(required, list) or not required:
            return ScenarioStore._inconclusive_recovery(base, "missing_required_response_contract")
        active_pairs = {(item.get("action"), item.get("target")) for item in active}
        missing = [item for item in required
                   if (item.get("action"), item.get("target")) not in active_pairs]
        if missing:
            reason = "no_authenticated_active_action" if not active else "required_response_not_satisfied"
            return ScenarioStore._inconclusive_recovery(base, reason, missing)
        verified = json.loads(json.dumps(base))
        verified["data"]["verdict"] = "verified"
        verified["data"]["required_actions_met"] = True
        verified["data"]["verified_actions"] = required
        return verified

    @staticmethod
    def _inconclusive_recovery(base: dict[str, Any], reason: str,
                               missing: list[dict[str, Any]] | None = None) -> dict[str, Any]:
        data = json.loads(json.dumps(base.get("data", {})))
        for key, value in list(data.items()):
            if isinstance(value, bool):
                data[key] = False
            elif key == "window_minutes":
                data[key] = 0
            elif isinstance(value, (int, float)) and any(
                marker in key for marker in ("suspicious", "shell", "connection")
            ):
                data[key] = None
        data.update({
            "verdict": "inconclusive", "reason": reason,
            "required_actions_met": False,
            "missing_required_actions": missing if missing is not None else base.get("required_actions", []),
        })
        return {
            "source": "verification-sensor",
            "kind": "recovery_metrics",
            "observed_at": datetime.now(UTC).isoformat(),
            "summary": "Containment cannot be verified because the required active action and target set is incomplete.",
            "confidence": 0.98,
            "attack_techniques": base.get("attack_techniques", []),
            "supports": base.get("failure_supports", ["H-active-compromise-after-containment"]),
            "data": data,
        }

    def _append(self, evidence: Evidence) -> None:
        path = self.data_dir / "evidence.jsonl"
        line = evidence.model_dump_json() + "\n"
        with self._lock, path.open("a", encoding="utf-8") as stream:
            stream.write(line)


store = ScenarioStore()
