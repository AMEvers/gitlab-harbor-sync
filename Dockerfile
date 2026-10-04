FROM python:3.12-slim AS runtime

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1

WORKDIR /app

COPY pyproject.toml README.md ./
COPY src ./src
RUN pip install --no-cache-dir .

# Numeric UID/GID keeps the image independent of /etc/passwd and works with the
# Kubernetes runAsUser/runAsGroup settings in deploy/kubernetes/base/cronjob.yaml.
USER 65532:65532

ENTRYPOINT ["gitlab-harbor-sync"]
