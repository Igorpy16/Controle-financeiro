FROM python:3.12-slim

# Produção: exige APP_PASSWORD, começa sem dados de exemplo e grava o banco em /data
ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    REQUIRE_AUTH=1 \
    SEMEAR_DEMO=0 \
    FINANCAS_DB=/data/financas.db

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY main.py .
COPY static ./static

# /data deve ser um disco/volume persistente na hospedagem, senão os dados somem a cada deploy
RUN mkdir -p /data

EXPOSE 8000

# Um único processo (o banco é SQLite). A porta vem de $PORT quando a plataforma define.
CMD ["sh", "-c", "exec uvicorn main:app --host 0.0.0.0 --port ${PORT:-8000} --proxy-headers --forwarded-allow-ips='*'"]
