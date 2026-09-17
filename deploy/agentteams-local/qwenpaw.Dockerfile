# Pinned to the actual cg-inv005-planner base image inspected on 2026-09-17.
# Build from the repository root. This file does not alter any current container.
FROM higress-registry.cn-hangzhou.cr.aliyuncs.com/agentteams/agentteams-qwenpaw-worker@sha256:5a8c60926009551f7ce555f657d63c8791450196a79ab41ba8bafd2e1bd51834

COPY deploy/agentteams-local/patch-qwenpaw-readiness.py /tmp/patch-qwenpaw-readiness.py
RUN /opt/venv/qwenpaw/bin/python /tmp/patch-qwenpaw-readiness.py /opt/venv/qwenpaw/lib/python3.11/site-packages/qwenpaw_worker/worker.py
