import socket
import threading
import os
import time
from prometheus_client import start_http_server, Counter

# Configuración
HOST = "0.0.0.0"
PORT = int(os.getenv("PORT", 5000))
NODE_NAME = os.getenv("NODE_NAME", "nodo")
PEERS = os.getenv("PEERS", "").split(",")
METRICS_PORT = int(os.getenv("METRICS_PORT", 8000))

# Métricas Prometheus
mensajes_enviados = Counter('mensajes_enviados_total', 'Total de mensajes enviados', ['destino'])
mensajes_recibidos = Counter('mensajes_recibidos_total', 'Total de mensajes recibidos', ['origen'])

print(f"[{NODE_NAME}] Arrancando nodo en puerto {PORT}, métricas en {METRICS_PORT}, peers: {PEERS}")

def handle_client(conn, addr):
    data = conn.recv(1024).decode("utf-8")
    print(f"[{NODE_NAME}] Mensaje recibido de {addr}: {data}")
    mensajes_recibidos.labels(origen=str(addr)).inc()
    conn.sendall(f"Respuesta de {NODE_NAME}".encode("utf-8"))
    conn.close()

def start_server():
    server = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    server.bind((HOST, PORT))
    server.listen()
    print(f"[{NODE_NAME}] Escuchando en {HOST}:{PORT}")
    while True:
        conn, addr = server.accept()
        threading.Thread(target=handle_client, args=(conn, addr)).start()

def connect_to_peers():
    while True:
        for peer in PEERS:
            if not peer.strip():
                continue
            host, port = peer.split(":")
            try:
                with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
                    s.connect((host, int(port)))
                    message = f"Hola desde {NODE_NAME}"
                    s.sendall(message.encode("utf-8"))
                    response = s.recv(1024).decode("utf-8")
                    print(f"[{NODE_NAME}] Respuesta de {peer}: {response}")
                    mensajes_enviados.labels(destino=peer).inc()
            except Exception as e:
                print(f"[{NODE_NAME}] No se pudo conectar a {peer}: {e}")
        time.sleep(5)

if __name__ == "__main__":
    # Servidor de métricas Prometheus
    start_http_server(METRICS_PORT)
    print(f"[{NODE_NAME}] Exponiendo métricas en puerto {METRICS_PORT}")

    # Hilo para escuchar
    threading.Thread(target=start_server, daemon=True).start()
    # Conectar a peers
    connect_to_peers()
