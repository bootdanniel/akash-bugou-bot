FROM python:3.12-slim

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PATH=/usr/local/bin:/usr/bin:/bin

RUN apt-get update && apt-get install -y --no-install-recommends \
    bash \
    curl \
    jq \
    ca-certificates \
    tini \
    tzdata \
    && rm -rf /var/lib/apt/lists/*

# Instala o requests e o cloudscraper
RUN pip install --no-cache-dir requests cloudscraper

WORKDIR /app

COPY bot.py /app/

RUN sed -i 's/\r$//' /app/bot.py

ENTRYPOINT ["tini", "--"]
CMD ["python3", "-u", "/app/bot.py"]
