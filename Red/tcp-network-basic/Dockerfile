# Imagen base con Python
FROM python:3.10-slim

# Establecer directorio de trabajo
WORKDIR /app

# Copiar dependencias
COPY requirements.txt .

# Instalar dependencias
RUN pip install --no-cache-dir -r requirements.txt

# Copiar el código fuente
COPY app.py .

# Comando por defecto para arrancar la app
CMD ["python", "app.py"]