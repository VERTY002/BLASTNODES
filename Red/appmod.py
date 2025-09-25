import socket
import threading
import os
import time

# Configuración
HOST = "0.0.0.0"
PORT = int(os.getenv("PORT", 5000))
NODE_NAME = os.getenv("NODE_NAME", "nodo")
PEERS = os.getenv("PEERS", "").split(",")

# Conjunto de mensajes ya procesados para evitar duplicados
processed_messages = set()
lock = threading.Lock()  # Asegura acceso seguro al conjunto desde varios hilos

def handle_client(conn, addr):
    try:
        data = conn.recv(1024).decode("utf-8")
        if not data:
            return

        # Control de duplicados simple: se usa el contenido del mensaje
        with lock:
            if data in processed_messages:
                return
            processed_messages.add(data)

        print(f"[{NODE_NAME}] Mensaje recibido de {addr}: {data}")

        # Reenviar a todos los peers excepto al que lo envió
        for peer in PEERS:
            if not peer.strip():
                continue
            host, port = peer.split(":")
            if f"{addr[0]}:{addr[1]}" == peer:
                continue  # No reenviar al remitente
            try:
                with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
                    s.connect((host, int(port)))
                    s.sendall(data.encode("utf-8"))
            except:
                pass

        conn.sendall(f"Respuesta de {NODE_NAME}".encode("utf-8"))
    finally:
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
            except Exception as e:
                print(f"[{NODE_NAME}] No se pudo conectar a {peer}: {e}")
        time.sleep(5)

if __name__ == "__main__":
    threading.Thread(target=start_server, daemon=True).start()
    connect_to_peers()
