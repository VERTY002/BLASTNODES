# Imagen base ligera y rápida
FROM python:3.11-slim

# Crear una carpeta dentro del contenedor
WORKDIR /app

# Copiar el exporter
COPY sidecar-exporter.py /app/

# Instalar dependencias
RUN pip install prometheus_client

# Exponer puerto de métricas
EXPOSE 9100

# Ejecutar exporter
CMD ["python", "sidecar-exporter.py"]
