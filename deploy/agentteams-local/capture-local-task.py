#!/usr/bin/env python3
"""Use the existing capture tool with explicit local networking and Matrix Host."""
from pathlib import Path
import runpy
import urllib.request
import urllib.parse


class LocalMatrixHost(urllib.request.BaseHandler):
    def http_request(self, request):
        url = urllib.parse.urlsplit(request.full_url)
        if url.hostname == "127.0.0.1" and url.port == 18080:
            request.add_unredirected_header("Host", "matrix-local.agentteams.io")
        return request


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


urllib.request.install_opener(urllib.request.build_opener(
    urllib.request.ProxyHandler({}), LocalMatrixHost(), NoRedirect()))
runpy.run_path(str(Path(__file__).resolve().parents[2] / "scripts/capture-agentteams-task.py"), run_name="__main__")
