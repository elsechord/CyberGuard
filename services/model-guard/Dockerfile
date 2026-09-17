FROM python:3.12.13-slim-bookworm@sha256:d50fb7611f86d04a3b0471b46d7557818d88983fc3136726336b2a4c657aa30b
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 PIP_NO_CACHE_DIR=1
WORKDIR /app
COPY services/requirements.lock ./
RUN pip install --require-hashes -r requirements.lock && pip check
COPY cyberguard_investigation ./cyberguard_investigation
COPY services/model-guard/entrypoint.py ./
RUN useradd --system --uid 10001 --create-home cyberguard && mkdir -p /data && chown -R 10001:10001 /data /app
USER 10001
EXPOSE 8080
CMD ["python", "entrypoint.py"]
