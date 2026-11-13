FROM python:3.12-slim
WORKDIR /app
COPY backend/requirements.lock.txt /app/backend/requirements.lock.txt
RUN pip install --no-cache-dir pip==26.2 && pip install --no-cache-dir -r backend/requirements.lock.txt
RUN useradd --uid 10001 --create-home metro
COPY backend /app/backend
COPY data/operator-network.json /app/data/operator-network.json
COPY alembic.ini /app/alembic.ini
USER 10001:10001
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1
CMD ["uvicorn", "backend.app.main:app", "--host", "0.0.0.0", "--port", "8000", "--no-proxy-headers", "--no-server-header", "--ws-max-size", "4096", "--limit-concurrency", "300"]
