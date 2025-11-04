FROM python:3.11-slim

ENV PYTHONUNBUFFERED=1 PYTHONDONTWRITEBYTECODE=1
WORKDIR /app

# Dependencia para exponer /metrics
RUN pip install --no-cache-dir prometheus-client

# Copia tu app instrumentada
COPY app.py .

# Expón puertos de app y métricas (informativo)
EXPOSE 5000 8000

# OJO: aquí estaba el bug; tu CMD apuntaba a /app.py (ruta raíz)
CMD ["python", "-u", "app.py"]