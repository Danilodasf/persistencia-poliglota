# Imagem que roda os scripts de carga e demonstração.
# Assim ninguém do grupo precisa instalar Python nem drivers na própria máquina.
FROM python:3.11-slim

# Saída sem buffer: o print aparece na hora no terminal (importante na gravação do vídeo).
ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1 \
    PYTHONPATH=/projeto \
    TZ=America/Sao_Paulo

# tzdata: para o horário impresso nas saídas ser o de Brasília, e não UTC.
RUN apt-get update && apt-get install -y --no-install-recommends tzdata \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt /tmp/requirements.txt
RUN pip install -r /tmp/requirements.txt

# O repositório é montado aqui pelo docker-compose (volume .:/projeto).
WORKDIR /projeto
