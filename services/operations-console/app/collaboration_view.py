"""Present exported WorkerFlow snapshots without treating claims as transport proof."""


def _text(value, limit=2000):
    return value[:limit] if isinstance(value, str) else ''


def _rows(value):
    return [row for row in value if isinstance(row, dict)] if isinstance(value, list) else []


def _strings(value):
    return [_text(item, 300) for item in value if isinstance(item, str)][:32] if isinstance(value, list) else []


def normalize(collaboration, workflow=None):
    """Return a bounded display projection; unknown fields never become UI markup."""
    runs, temporary, workers = [], set(), set()
    workflow = workflow if isinstance(workflow, dict) else {}
    for task in _rows(workflow.get('nodes')):
        if isinstance(task.get('assignee'), str) and task['assignee']:
            workers.add(task['assignee'])
    for source in _rows(collaboration)[-32:]:
        run = {key: _text(source.get(key), 500) for key in
               ('job_id', 'task_id', 'parent_worker', 'run_id', 'reason', 'status')}
        if run['parent_worker']:
            workers.add(run['parent_worker'])
        run['nodes'] = []
        for node in _rows(source.get('nodes'))[:64]:
            row = {key: _text(node.get(key)) for key in
                   ('id', 'agent_id', 'role', 'question', 'status', 'summary')}
            row.update(material_ids=_strings(node.get('material_ids')),
                       artifact_paths=_strings(node.get('artifact_paths')))
            if row['agent_id']:
                temporary.add((run['parent_worker'], row['agent_id']))
            run['nodes'].append(row)
        run['messages'] = []
        for message in _rows(source.get('messages'))[:128]:
            row = {key: _text(message.get(key)) for key in
                   ('from', 'to', 'kind', 'question', 'answer', 'event_id')}
            changed = message.get('changed_conclusion')
            row['changed_conclusion'] = changed if isinstance(changed, bool) else _text(changed)
            run['messages'].append(row)
        cleanup = source.get('cleanup')
        run['cleanup'] = {key: _text(cleanup.get(key)) for key in ('status', 'summary')} if isinstance(cleanup, dict) else {}
        run['cleanup_recorded'] = isinstance(cleanup, dict) and bool(cleanup)
        runs.append(run)
    return dict(runs=runs, team_worker_count=len(workers), temporary_agent_count=len(temporary),
                message_count=sum(len(run['messages']) for run in runs),
                provenance='worker_exported_native_snapshot')
