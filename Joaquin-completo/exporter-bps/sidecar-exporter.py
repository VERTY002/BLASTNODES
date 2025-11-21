import os
import json
import time
from prometheus_client import start_http_server, Counter, Gauge

LOG_FILE = "/var/log/app.log"

# Asegurar que el archivo existe siempre
os.makedirs(os.path.dirname(LOG_FILE), exist_ok=True)
open(LOG_FILE, "a").close()

# Métricas
bytes_total = Counter(
    "app_edge_bytes_total",
    "Total bytes enviados por edge",
    ["src", "dst"]
)

messages_total = Counter(
    "app_edge_messages_total",
    "Total mensajes enviados por edge",
    ["src", "dst"]
)

last_payload_bytes = Gauge(
    "app_edge_last_payload_bytes",
    "Último tamaño de mensaje por edge",
    ["src", "dst"]
)

def tail_f(path):
    while not os.path.exists(path):
        print(f"[exporter] Esperando a que {path} exista…")
        time.sleep(1)

    with open(path, "r") as f:
        f.seek(0, 2)
        while True:
            line = f.readline()
            if not line:
                time.sleep(0.1)
                continue
            yield line


def main():
    print("[exporter] Iniciando server Prometheus en :9100")
    start_http_server(9100)

    for line in tail_f(LOG_FILE):
        try:
            log = json.loads(line)
        except Exception:
            continue

        # SOLO procesamos los logs de edge
        if log.get("event") != "edge":
            continue

        data = log.get("data", {})
        if "src" not in data or "dst" not in data or "bytes" not in data:
            print(f"[exporter] Log ignorado, falta src/dst/bytes: {data}")
            continue

        src = data["src"]
        dst = data["dst"]
        size = int(data["bytes"])

        # Actualizar métricas
        bytes_total.labels(src=src, dst=dst).inc(size)
        messages_total.labels(src=src, dst=dst).inc()
        last_payload_bytes.labels(src=src, dst=dst).set(size)


if __name__ == "__main__":
    main()
