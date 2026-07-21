FROM python:3.12-slim

WORKDIR /app
RUN mkdir -p /app/state

# Chromium for the browser tier (Target/PerimeterX via zendriver). Only used at
# runtime when an item has `fetcher: browser` and DISABLE_BROWSER_TIER is unset.
# It adds ~400 MB to the image (fine on 25 GB disk) but needs ~2 GB RAM to run;
# on a 1 GB box set DISABLE_BROWSER_TIER=1 so Chromium is never launched.
RUN apt-get update && apt-get install -y --no-install-recommends \
        chromium \
        fonts-liberation \
    && rm -rf /var/lib/apt/lists/*

# Point zendriver/Chrome at the apt-installed binary.
ENV ZENDRIVER_BROWSER_PATH=/usr/bin/chromium

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY monitor/ ./monitor/
COPY config.yaml ./

# state.json persisted via a mounted volume (see docker-compose.yml)
CMD ["python", "-m", "monitor.loop"]
