FROM python:3.12-slim

WORKDIR /app
ENV PYTHONPATH=/app/src \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1
COPY src ./src
COPY config ./config
ENTRYPOINT ["python", "-m", "kb_ai_pipeline.local_run"]
