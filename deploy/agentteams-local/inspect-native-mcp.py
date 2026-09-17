"""Print only MCP discovery result names or a redacted local diagnostic."""
import json, os, urllib.request, urllib.error
opener=urllib.request.build_opener(urllib.request.ProxyHandler({}))
for key in ('mcp-cyberguard-investigation-readonly','mcp-cyberguard-investigation-report'):
    try:
        with opener.open('http://127.0.0.1:8088/api/mcp/tools/'+key,timeout=20) as r:
            value=json.load(r)
        print(json.dumps({'client':key,'tools':[{'name':v['name'],'enabled':v['enabled']} for v in value]}))
    except urllib.error.HTTPError as e:
        value=e.read().decode()
        category='saved_but_inactive' if 'saved but not active yet' in value else 'remote_error_redacted'
        print(json.dumps({'client':key,'status':e.code,'category':category}))
