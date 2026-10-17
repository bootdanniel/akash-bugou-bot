FROM python:3.12-slim

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1

RUN apt-get update && apt-get install -y --no-install-recommends \
    bash \
    curl \
    jq \
    ca-certificates \
    coreutils \
    grep \
    sed \
    procps \
    && rm -rf /var/lib/apt/lists/*

RUN pip install --no-cache-dir requests

WORKDIR /app

COPY bot.py f68b.sh ./

RUN chmod +x /app/f68b.sh && sed -i 's/\r$//' /app/bot.py /app/f68b.sh

CMD ["python3", "bot.py"]
