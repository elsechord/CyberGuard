FROM python:3.12.14-slim-bookworm@sha256:782412e85d0f0984994c290652577d4018aff08145c85b262bb63dc0c7522254

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1

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
