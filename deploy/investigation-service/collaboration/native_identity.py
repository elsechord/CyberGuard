"""AgentTeams v1.2.3 compatibility fix for native task delegation addresses."""
from urllib.parse import urlsplit, urlunsplit


def normalize_local_gateway(value):
    """Correct this local embedded deployment's control/data-plane mismatch."""
    url = urlsplit(value)
    if url.scheme == 'http' and url.hostname == 'agentteams-controller' and url.port == 8080 and url.path.startswith('/cg-guard/'):
        return urlunsplit(('http', 'aigw-local.agentteams.io:8080', url.path, url.query, url.fragment))
    return value


def patch_runtime_source(source):
    marker = '        # CyberGuard local embedded gateway compatibility\n'
    if marker in source:
        return source
    old = '        api_key = _string(model.get("apiKey") or model.get("api_key"))\n'
    if source.count(old) != 1:
        raise ValueError('Unsupported Worker runtime source; review gateway compatibility patch')
    new = marker + (
        '        import runpy\n'
        '        base_url = runpy.run_path("/opt/cyberguard-collaboration/native_identity.py")["normalize_local_gateway"](base_url)\n'
    ) + old
    return source.replace(old, new)


def resolve_matrix_user_id(value, members):
    value = str(value or '').strip()
    if value.startswith('@') and ':' in value:
        return value
    matches = set()
    for member in members:
        aliases = {member.get(key) for key in ('name', 'runtimeName', 'runtime_name')}
        user_id = member.get('matrixUserId') or member.get('matrix_user_id')
        if value and value in aliases and isinstance(user_id, str) and user_id.startswith('@') and ':' in user_id:
            matches.add(user_id)
    if len(matches) != 1:
        raise ValueError('Task assignee must be a full Matrix ID or a uniquely resolved team Worker name')
    return matches.pop()


def patch_native_source(source):
    """Resolve before native membership checking, storage and notification."""
    marker = '            # CyberGuard v1.2.3 task assignee compatibility\n'
    if marker in source:
        return source
    old = '            assignment_mxid = str(assigned_to or "").strip()\n'
    if source.count(old) != 1:
        raise ValueError('Unsupported native taskflow source; review compatibility patch before installing')
    new = marker + (
        '            import runpy\n'
        '            resolve_assignee = runpy.run_path("/opt/cyberguard-collaboration/native_identity.py")["resolve_matrix_user_id"]\n'
        '            assigned_to = resolve_assignee(assigned_to, _section(_load_runtime_config(), "team").get("members", []))\n'
    ) + old
    return source.replace(old, new)
