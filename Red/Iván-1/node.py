import socket
import threading
import time
import os
import requests

# Configuración del nodo a través de variables de entorno
NODE_NAME = os.getenv("NODE_NAME", "Node")  # Nombre identificador del nodo
NODE_PORT = int(os.getenv("NODE_PORT", 9000))  # Puerto en el que escucha este nodo
PEER_NODES = os.getenv("PEER_NODES", "")  # Lista de peers con formato: "node2:9001,node3:9002"
DASHBOARD_HOST = os.getenv("DASHBOARD_HOST", "dashboard")  # Dirección del visor (dashboard)
DASHBOARD_PORT = int(os.getenv("DASHBOARD_PORT", 5000))  # Puerto del visor

peer_connections = []  # Lista de sockets conectados a peers

def handle_client(conn, addr):
    """Maneja una conexión entrante desde otro nodo."""
    print(f"[{NODE_NAME}] Connection from {addr}")
    try:
        while True:
            data = conn.recv(1024)
            if not data:
                break  # El cliente cerró la conexión
            print(f"[{NODE_NAME}] Received from {addr}: {data.decode()}")
    except Exception as e:
        print(f"[{NODE_NAME}] Error: {e}")
    finally:
        conn.close()

def start_server():
    """Inicia el servidor TCP que acepta conexiones entrantes de otros nodos."""
    server = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    server.bind(("0.0.0.0", NODE_PORT))
    server.listen()
    print(f"[{NODE_NAME}] Listening on port {NODE_PORT}...")

    while True:
        conn, addr = server.accept()
        client_thread = threading.Thread(target=handle_client, args=(conn, addr), daemon=True)
        client_thread.start()  # Cada conexión entrante se maneja en un hilo independiente

def connect_to_peers():
    """Establece conexiones salientes con los nodos definidos en PEER_NODES."""
    global peer_connections
    peers = PEER_NODES.split(",")
    for peer in peers:
        if not peer:
            continue
        host, port = peer.split(":")
        try:
            s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            s.connect((host, int(port)))
            peer_connections.append(s)
            print(f"[{NODE_NAME}] Connected to peer {host}:{port}")
        except Exception as e:
            print(f"[{NODE_NAME}] Could not connect to {host}:{port} - {e}")

def send_heartbeat():
    """Envía mensajes de ping periódicos a todos los peers conectados."""
    while True:
        for conn in peer_connections:
            try:
                msg = f"Ping from {NODE_NAME}"
                conn.sendall(msg.encode())
            except Exception as e:
                print(f"[{NODE_NAME}] Failed to send ping: {e}")
        time.sleep(5)

def report_status():
    """Envía periódicamente el estado del nodo al dashboard para su visualización."""
    while True:
        try:
            requests.post(f"http://{DASHBOARD_HOST}:{DASHBOARD_PORT}/report", json={
                "name": NODE_NAME,
                "port": NODE_PORT,
                "peers": PEER_NODES.split(",") if PEER_NODES else [],
                "timestamp": time.time()
            })
        except Exception as e:
            print(f"[{NODE_NAME}] Failed to report status: {e}")
        time.sleep(5)

if __name__ == "__main__":
    # Inicia servidor TCP y reporte al dashboard en hilos separados
    threading.Thread(target=start_server, daemon=True).start()
    threading.Thread(target=report_status, daemon=True).start()
    
    time.sleep(2)  # Pequeño retardo para asegurar que el servidor esté listo

    # Conecta a otros peers y comienza a enviar pings periódicos
    connect_to_peers()
    send_heartbeat()
