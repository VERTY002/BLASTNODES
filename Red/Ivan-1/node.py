import socket
import threading
import time
import os

# Configuración del nodo a través de variables de entorno
NODE_NAME = os.getenv("NODE_NAME", "Node")  # Nombre identificador del nodo
NODE_PORT = int(os.getenv("NODE_PORT", 9000))  # Puerto en el que escucha este nodo
PEER_NODES = os.getenv("PEER_NODES", "")  # Lista de peers p.ej. "node2:9001,node3:9002"
DELAY = int(os.getenv("DELAY", 5))  # Tiempo entre paquetes enviados

peer_connections = []  # Lista de sockets conectados a peers

def handle_client(conn, addr):
    """Maneja una conexión entrante desde otro nodo."""
    print(f"[{NODE_NAME}] Connection from {addr}")
    try:
        while True:
            data = conn.recv(1024)
            if not data:
                break  # El cliente cerró la conexión
            message = data.decode()
            print(f"[{NODE_NAME}] Received from {addr}: {message}")

            # Responder con un 'pong' o confirmación
            response = f"Reply from {NODE_NAME} to {addr[0]}:{addr[1]}"
            conn.sendall(response.encode())
    except Exception as e:
        print(f"[{NODE_NAME}] Error: {e}")
    finally:
        conn.close()

def listen_to_peer(conn):
    """Escucha lo que el peer envía en una conexión saliente."""
    try:
        while True:
            data = conn.recv(1024)
            if not data:
                break
            print(f"[{NODE_NAME}] Received from peer: {data.decode()}")
    except Exception as e:
        print(f"[{NODE_NAME}] Error receiving from peer: {e}")
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
        client_thread.start()

def connect_to_peers():
    """Establece conexiones salientes con los nodos definidos en PEER_NODES, con reintentos."""
    global peer_connections
    peers = PEER_NODES.split(",")
    
    while True:
        remaining_peers = []
        for peer in peers:
            if not peer:
                continue
            host, port = peer.split(":")
            try:
                s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
                s.connect((host, int(port)))
                peer_connections.append(s)
                print(f"[{NODE_NAME}] Connected to peer {host}:{port}")
                threading.Thread(target=listen_to_peer, args=(s,), daemon=True).start()
            except Exception as e:
                print(f"[{NODE_NAME}] Could not connect to {host}:{port} - {e}")
                remaining_peers.append(peer)

        if not remaining_peers:
            break  # todos conectados
        print(f"[{NODE_NAME}] Retrying connection to remaining peers in 5s...")
        peers = remaining_peers
        time.sleep(5)

def send_heartbeat():
    """Envía mensajes de ping periódicos a todos los peers conectados."""
    while True:
        for conn in peer_connections:
            try:
                msg = f"Ping from {NODE_NAME}"
                conn.sendall(msg.encode())
            except Exception as e:
                print(f"[{NODE_NAME}] Failed to send ping: {e}")
        time.sleep(DELAY)

if __name__ == "__main__":
    threading.Thread(target=start_server, daemon=True).start()

    time.sleep(2)  # Espera para asegurar que el servidor está listo

    connect_to_peers()
    send_heartbeat()
