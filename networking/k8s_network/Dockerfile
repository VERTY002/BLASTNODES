FROM python:3.11-slim

ENV PYTHONUNBUFFERED=1 PYTHONDONTWRITEBYTECODE=1
WORKDIR /app

# Si tienes requirements.txt, descoméntalo y añade tus deps (Flask, requests, etc.)
# COPY app/requirements.txt /app/requirements.txt
# RUN pip install --no-cache-dir -r /app/requirements.txt

COPY app.py
EXPOSE 5000
CMD ["python", "-u", "/app.py"]




