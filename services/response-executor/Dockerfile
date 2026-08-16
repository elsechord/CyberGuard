FROM python:3.12.13-slim-bookworm@sha256:d50fb7611f86d04a3b0471b46d7557818d88983fc3136726336b2a4c657aa30b

ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 PIP_NO_CACHE_DIR=1
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
