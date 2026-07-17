FROM python:3.12-slim

WORKDIR /app
RUN mkdir -p /app/state
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY monitor/ ./monitor/
COPY config.yaml ./

# state.json persisted via a mounted volume (see docker-compose.yml)
CMD ["python", "-m", "monitor.loop"]
