FROM alpine:latest

# Instala as dependências (incluindo o requests direto pelo apk)
RUN apk add --no-cache bash curl jq python3 py3-requests

# Cria a pasta de trabalho
WORKDIR /app

# Copia os arquivos
COPY f68_series_live.sh /app/
COPY bot.py /app/

# Dá permissão de execução
RUN chmod +x /app/f68_series_live.sh

# Roda o bot
CMD ["python3", "/app/bot.py"]
