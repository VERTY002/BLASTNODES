#Imagen base con Phython: que indica la imagen base sobre la que se va construir la nueva imagen de Docker.
FROM python:3.10-slim


# Evitar buffers en la salida de Python para ver logs en tiempo real
ENV PYTHONUNBUFFERED=1

# Establecer el directorio de trabajo
WORKDIR /app


# Instalar dependencias
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copia todos los archivos del contexto build 
COPY . .


#EXPONE LOS PUERTOS 5000 Y 8000 PARA COMUNICACION ENTRE NODOS Y METRICAS PROMETHEUS:
EXPOSE 5000 8000 

# Comando por defecto para arrancar la app
CMD ["python", "nodo-app(v2).py"]
