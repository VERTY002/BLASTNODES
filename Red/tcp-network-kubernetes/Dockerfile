FROM python:3.11-slim

WORKDIR /app
COPY app.py /app/
RUN pip install --no-cache-dir --upgrade pip

EXPOSE 5000
CMD ["python", "app.py"]
