# build จาก root ของ repo: docker build -f api/Dockerfile .
FROM python:3.12-slim

ARG EXTRAS=""
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1

WORKDIR /app
COPY contracts /app/contracts
COPY api /app/api
RUN pip install --no-cache-dir --root-user-action=ignore /app/contracts "/app/api${EXTRAS}" \
 && useradd --system --uid 10001 flock \
 && mkdir -p /data/images && chown flock /data/images

USER flock
EXPOSE 8000
CMD ["uvicorn", "flock_api.app:app", "--host", "0.0.0.0", "--port", "8000"]
