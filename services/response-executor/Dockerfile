FROM python:3.14.7-slim-bookworm@sha256:9ab8d9c8514b44f90cf0029dd42fdd7e9e211e639c8b995304cc04568dee900f

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
