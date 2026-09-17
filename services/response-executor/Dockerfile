FROM python:3.12.14-slim-bookworm@sha256:782412e85d0f0984994c290652577d4018aff08145c85b262bb63dc0c7522254

ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 PIP_NO_CACHE_DIR=1

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
COPY services/response-executor/app ./app
COPY services/response-executor/entrypoint.py ./
RUN useradd --system --uid 10002 --create-home cyberguard \
    && mkdir -p /data \
    && chown -R cyberguard:cyberguard /data /app
USER 10002
EXPOSE 8080
CMD ["python", "entrypoint.py"]
