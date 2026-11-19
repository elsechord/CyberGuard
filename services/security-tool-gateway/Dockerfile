FROM python:3.15.2-slim-bookworm@sha256:96599df822d0e1c6bb700014a05c7f3c8cabc6e0f7ff3c4f9f69cee033b4b5d9

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1

# DLA-4772-1: patched pcre2 (10.42-1+deb12u1) is not yet in the pinned base
# image rebuild (CVE-2026-86145/89157/89161); install it explicitly until the
# next base digest bump and drop this layer then.
RUN apt-get update \
    && apt-get install -y --no-install-recommends libpcre2-8-0=10.42-1+deb12u1 \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app
COPY services/requirements.lock ./
RUN pip install --no-cache-dir --require-hashes -r requirements.lock \
    && pip check
COPY services/security-tool-gateway/app ./app
COPY cyberguard_investigation ./cyberguard_investigation
COPY services/security-tool-gateway/entrypoint.py ./

RUN useradd --system --uid 10001 --create-home cyberguard \
    && mkdir -p /data \
    && chown -R cyberguard:cyberguard /data /app
USER 10001

EXPOSE 8080
CMD ["python", "entrypoint.py"]
