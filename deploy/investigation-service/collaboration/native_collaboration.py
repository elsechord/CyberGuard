"""Thin AgentTeams v1.2.3 WorkerFlow CLI. The calling Worker remains scheduler.

No model calls are made here: send returned submitInstructions with native
submit_to_agent/chat_with_agent, then pass completed steps to update.
"""
from __future__ import annotations

import argparse
import importlib.util
import json
import os
from pathlib import Path
import sys
import time

DEFAULT_MODULE = '/opt/agentteams/qwenpaw-builtin/plugins/workerflow/workerflow/mcp/server.py'


def read(path):
    return json.loads(Path(path).read_text(encoding='utf-8'))


def write(path, value):
    path = Path(path)
    temporary = path.with_suffix(path.suffix + '.tmp')
    temporary.write_text(json.dumps(value, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    temporary.replace(path)


def load_native(path):
    path = Path(path)
    if not path.is_file():
        raise ValueError('Installed WorkerFlow module not found; set CYBERGUARD_WORKERFLOW_MODULE')
    spec = importlib.util.spec_from_file_location('cyberguard_installed_workerflow', path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class Collaboration:
    def __init__(self, native, plan, task_dir, max_agents=3, max_depth=1, max_iters=10, sleep=time.sleep):
        self.native, self.plan = native, plan
        self.task_dir = Path(task_dir)
        if not self.task_dir.is_dir():
            raise ValueError('task-dir must be an existing TeamHarness task directory')
        if not 1 <= max_agents <= 16 or max_depth != 1 or not 1 <= max_iters <= 100:
            raise ValueError('Use max_agents 1..16, max_depth 1 and max_iters 1..100')
        self.max_agents, self.max_depth, self.max_iters = max_agents, max_depth, max_iters
        self.sleep = sleep
        for field in ('job_id', 'task_id', 'run_id', 'parent_worker', 'reason'):
            if not isinstance(plan.get(field), str) or not plan[field].strip():
                raise ValueError('plan requires ' + field)
        if plan.get('parent_agent_id', 'default') != 'default' or plan.get('depth', 1) != 1:
            raise ValueError('This helper supports first-level children of the default Worker only')
        self.run_id = native._resolve_run_id(plan['run_id'], '')
        self.state_path = native._shared_root() / self.run_id / 'workflow.json'
        self.base = native._api_base()

    def arguments(self):
        return {'runId': self.run_id, 'apiBaseUrl': self.base}

    def start(self):
        if self.state_path.exists():
            raise ValueError('Run already exists; use update or export, not start')
        nodes = self.plan.get('nodes')
        if not isinstance(nodes, list) or not 1 <= len(nodes) <= self.max_agents:
            raise ValueError('Plan exceeds configured per-run temporary agent limit')
        materials = self.plan.get('materials', [])
        ids = [m['material_id'] for m in materials]
        if len(ids) != len(set(ids)):
            raise ValueError('material_id must be unique')
        known = set(ids)
        native_nodes = []
        for node in nodes:
            refs = node.get('material_ids')
            if not isinstance(refs, list) or not refs or not set(refs) <= known:
                raise ValueError('Every node must reference existing material_ids')
            if not node.get('question'):
                raise ValueError('Every node requires a question')
            native_nodes.append({
                'id': node['id'], 'subagent': node['subagent'],
                'name': node.get('role', node['subagent']),
                'role': node.get('role', node['subagent']),
                'task': node['question'] + '\nMaterial IDs: ' + ', '.join(refs),
                'dependsOn': node.get('depends_on', []),
            })
        # Explicit model inheritance: /api/agents does not inherit default's model.
        profile = self.native._json_request('GET', self.base, '/agents/default')
        active_model = profile.get('active_model')
        if not isinstance(active_model, dict) or not active_model:
            raise ValueError('Default Worker has no explicit active_model')
        try:
            result = self.native._workflow_run({
                **self.arguments(), 'roomId': self.plan['room_id'],
                'title': self.plan.get('title', self.plan['reason']),
                'input': json.dumps({'job_id': self.plan['job_id'], 'task_id': self.plan['task_id'],
                                     'materials': materials}, ensure_ascii=False),
                'nodes': native_nodes, 'activeModel': active_model,
                'merge': {'instruction': 'Return findings with exact material_id references, remaining questions and artifact paths.'},
            })
            for node in result.get('nodes', []):
                agent_id = node['agentId']
                child = self.native._json_request('GET', self.base, '/agents/' + agent_id)
                running = dict(child.get('running') or {})
                running['max_iters'] = self.max_iters
                running['auto_title_config'] = {**running.get('auto_title_config', {}), 'enabled': False}
                self.native._json_request('PUT', self.base, '/agents/' + agent_id,
                                          {**child, 'id': agent_id, 'running': running, 'active_model': active_model})
                actual = self.native._json_request('GET', self.base, '/agents/' + agent_id)
                actual_running = actual.get('running') or {}
                if (actual_running.get('max_iters') != self.max_iters
                        or actual_running.get('auto_title_config', {}).get('enabled') is not False
                        or any(actual.get('active_model', {}).get(k) != v for k, v in active_model.items())):
                    raise ValueError('Child model/running configuration readback mismatch')
            self.export()
        except Exception as original_error:
            if self.state_path.is_file():
                try:
                    self.advance('fail', {'summary': 'Collaboration startup failed'})
                except Exception as cleanup_error:
                    # Keep the actionable startup error even if cleanup or its
                    # optional snapshot export also fails. Native state survives.
                    if hasattr(original_error, 'add_note'):
                        original_error.add_note('Native cleanup/export also failed: ' + str(cleanup_error))
            raise
        # Includes native submitPrompt for the coordinator only, never the public artifact.
        peers = [node['agentId'] for node in result.get('nodes', [])]
        for key in ('submitInstructions', 'waitingInstructions'):
            for instruction in result.get(key, []):
                instruction['parent_id'] = 'default'
                instruction['peer_agent_ids'] = [peer for peer in peers if peer != instruction.get('agentId')]
        return result

    def advance(self, action, update=None):
        if not self.state_path.is_file():
            raise ValueError('Native run has not been started')
        update = update or {}
        allowed = {k: update[k] for k in ('steps', 'status', 'summary') if k in update}
        result = self.native._workflow({**allowed, **self.arguments(),
                                       'cleanupWorkspace': action in ('finish', 'fail')},
                                      'workflow_' + action)
        if action in ('finish', 'fail'):
            # Newly created QwenPaw agents briefly reject DELETE while starting.
            # Repeat only native cleanup; each outcome remains in native state.
            for delay in (1, 2, 4, 8):
                cleanup = result.get('cleanupTempAgents') or {}
                transient = any(not row.get('ok') and 'HTTP 409' in str(row.get('error', ''))
                                and 'start' in str(row.get('error', '')).lower()
                                for row in cleanup.get('agents', []))
                if not transient:
                    break
                self.sleep(delay)
                result = self.native._workflow({**allowed, **self.arguments(), 'cleanupWorkspace': True},
                                               'workflow_' + action)
        self.export()
        peers = [node.get('agentId') for node in read(self.state_path).get('nodes', [])]
        for instruction in result.get('readyInstructions', []):
            instruction['parent_id'] = 'default'
            instruction['peer_agent_ids'] = [peer for peer in peers if peer and peer != instruction.get('agentId')]
        return result

    def message(self, record):
        fields = ('from', 'to', 'kind', 'question', 'answer', 'changed_conclusion', 'event_id', 'task_id')
        row = {key: record[key] for key in fields if key in record}
        if not row.get('from') or not row.get('to'):
            raise ValueError('Message requires from and to')
        # An agent-written journal is not a transport receipt, even with an event id.
        row['provenance'] = 'agent_recorded'
        path = self.task_dir / ('collaboration-messages-' + self.run_id + '.json')
        rows = read(path) if path.exists() else []
        rows.append(row)
        write(path, rows)
        return self.export()

    def export(self):
        state = read(self.state_path)
        planned = {node['id']: node for node in self.plan.get('nodes', [])}
        nodes = []
        for row in state.get('nodes', state.get('subagents', [])):
            plan = planned.get(row['id'], {})
            nodes.append({'id': row['id'], 'agent_id': row.get('agentId', ''),
                          'role': row.get('role', ''), 'question': plan.get('question', ''),
                          'material_ids': plan.get('material_ids', []),
                          'status': row.get('status', 'unknown'), 'summary': row.get('summary', ''),
                          'artifact_paths': row.get('artifact_paths', []),
                          'depends_on': row.get('dependsOn', [])})
        journal = self.task_dir / ('collaboration-messages-' + self.run_id + '.json')
        snapshot = {'schema_version': 1, **{key: self.plan[key] for key in
                    ('job_id', 'task_id', 'parent_worker', 'run_id', 'reason')},
                    'status': state.get('status', 'unknown'), 'updated_at': state.get('updatedAt', ''),
                    'nodes': nodes, 'messages': read(journal) if journal.exists() else [],
                    'limits': {'max_agents': self.max_agents, 'max_depth': self.max_depth},
                    'cleanup': {}}
        # Native cleanup returns operational details; export only IDs and outcomes.
        cleanup = state.get('cleanupTempAgents')
        if isinstance(cleanup, dict):
            failed = cleanup.get('failed', 0)
            snapshot['cleanup'].update(status='partial_failed' if failed else 'completed',
                                       summary=f"Deleted {cleanup.get('deleted', 0)}; already absent {cleanup.get('missing', 0)}; failed {failed}.")
            snapshot['cleanup'].update({k: cleanup[k] for k in ('deleted', 'missing', 'failed') if k in cleanup})
            snapshot['cleanup']['agents'] = [{k: v for k, v in item.items()
                                             if k in ('agentId', 'ok', 'deleted')
                                             and isinstance(v, (str, bool, int))}
                                            for item in cleanup.get('agents', []) if isinstance(item, dict)]
        write(self.task_dir / 'collaboration.json', snapshot)
        return snapshot


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('action', choices=['start', 'update', 'finish', 'fail', 'export', 'message', 'record-message'])
    parser.add_argument('--plan', required=True)
    parser.add_argument('--task-dir', required=True)
    parser.add_argument('--data', help='JSON update or recorded message file')
    parser.add_argument('--native-module', default=os.getenv('CYBERGUARD_WORKERFLOW_MODULE', DEFAULT_MODULE))
    parser.add_argument('--max-agents', type=int, default=int(os.getenv('CYBERGUARD_MAX_SUBAGENTS', '3')))
    parser.add_argument('--max-depth', type=int, default=1)
    parser.add_argument('--max-iters', type=int, default=10)
    args = parser.parse_args()
    helper = Collaboration(load_native(args.native_module), read(args.plan), args.task_dir,
                           args.max_agents, args.max_depth, args.max_iters)
    data = read(args.data) if args.data else {}
    if args.action == 'start':
        result = helper.start()
    elif args.action == 'export':
        result = helper.export()
    elif args.action in ('message', 'record-message'):
        result = helper.message(data)
    else:
        result = helper.advance(args.action, data)
    print(json.dumps(result, ensure_ascii=False))


if __name__ == '__main__':
    try:
        main()
    except (ValueError, KeyError, OSError, RuntimeError) as exc:
        print(json.dumps({'ok': False, 'error': str(exc)}, ensure_ascii=False), file=sys.stderr)
        raise SystemExit(1)
