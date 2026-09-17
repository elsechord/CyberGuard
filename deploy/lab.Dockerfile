FROM python:3.12.13-slim-bookworm@sha256:d50fb7611f86d04a3b0471b46d7557818d88983fc3136726336b2a4c657aa30b
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 PIP_NO_CACHE_DIR=1
WORKDIR /app
COPY services/requirements.lock services/requirements.lock
COPY tests/requirements.lock tests/requirements.lock
RUN pip install --require-hashes -r services/requirements.lock -r tests/requirements.lock && pip check
COPY services services
COPY cyberguard_investigation cyberguard_investigation
COPY scripts scripts
COPY tests tests
COPY scenarios scenarios
COPY knowledge knowledge
COPY benchmark/investigation/cases benchmark/investigation/cases
ARG SOURCE_COMMIT=unknown
ENV CYBERGUARD_SOURCE_COMMIT=$SOURCE_COMMIT
RUN useradd --system --uid 10003 --create-home cyberguard \
    && mkdir /artifacts && chown cyberguard:cyberguard /artifacts
USER 10003
CMD ["python", "scripts/lab-demo.py", "--output", "/artifacts"]
