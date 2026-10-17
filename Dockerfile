FROM alpine:latest
RUN apk add --no-cache bash curl jq python3 py3-requests coreutils findutils
WORKDIR /app
COPY f68_series_live.sh /app/
COPY bot.py /app/
RUN chmod +x /app/f68_series_live.sh
CMD ["python3", "/app/bot.py"]
