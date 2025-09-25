FROM python:3.11-slim

WORKDIR /app

COPY node.py .

RUN pip install --no-cache-dir --upgrade pip

CMD ["python", "node.py"]
