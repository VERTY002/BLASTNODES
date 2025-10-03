# Imagen ligera de Python
FROM python

# Crear carpeta de la app
WORKDIR /app

RUN pip install --no-cache-dir prometheus-client

# Copiar el código
COPY app.py /app/

# Exponer un puerto 
EXPOSE 5000:8000

# Ejecutar el script por defecto
CMD ["python", "app.py"]