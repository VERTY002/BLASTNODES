FROM python

WORKDIR /app
COPY exporter.py /app/exporter.py
COPY requirements.txt /app/requirements.txt

RUN pip install --no-cache-dir -r requirements.txt

ENV PROM_URL=http://prometheus-operated.monitoring.svc:9090

EXPOSE 9100
CMD ["python", "/app/exporter.py"]
