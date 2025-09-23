import socket
import threading
import os
import time
import uuid

# Configuración del nodo
HOST = "0.0.0.0"
PORT = int(os.getenv("PORT", 5000))
NODE_NAME = os.getenv("NODE_NAME", "nodo")
PEERS = [p.strip() for p in os.getenv("PEERS", "").split(",") if p.strip()]

# Evita reenviar mensajes ya vistos
seen_messages = set()
lock = threading.Lock()  # Para concurrencia segura

# Maneja un mensaje recibido
def handle_client(conn, addr):
    try:
        data = conn.recv(1024).decode("utf-8")
        if not data:
            return

        # Formato: origen|destino|mensaje|id
        try:
            origen, destino, msg, msg_id = data.split("|", 3)
        except ValueError:
            print(f"[{NODE_NAME}] Mensaje malformado: {data}")
            return

        with lock:
            if msg_id in seen_messages:
                return
            seen_messages.add(msg_id)

        if destino == NODE_NAME:
            print(f"[{NODE_NAME}] Mensaje recibido de {origen}: {msg}")
        else:
            # Reenvía a peers
            forward_message(origen, destino, msg, msg_id, exclude=addr[0])

    finally:
        conn.close()

# Función para reenviar mensajes a todos los peers excepto al que lo envió
def forward_message(origen, destino, msg, msg_id, exclude=None):
    for peer in PEERS:
        host, port = peer.split(":")
        if host == exclude:
            continue
        try:
            with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
                s.settimeout(2)
                s.connect((host, int(port)))
                s.sendall(f"{origen}|{destino}|{msg}|{msg_id}".encode("utf-8"))
        except:
            pass

# Inicia servidor TCP
def start_server():
    server = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    server.bind((HOST, PORT))
    server.listen()
    print(f"[{NODE_NAME}] Escuchando en {HOST}:{PORT}")
    while True:
        conn, addr = server.accept()
        threading.Thread(target=handle_client, args=(conn, addr), daemon=True).start()

# Enviar mensaje desde este nodo a un destino
def send_message(destino, msg):
    msg_id = str(uuid.uuid4())
    for peer in PEERS:
        host, port = peer.split(":")
        try:
            with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
                s.settimeout(2)
                s.connect((host, int(port)))
                s.sendall(f"{NODE_NAME}|{destino}|{msg}|{msg_id}".encode("utf-8"))
        except:
            pass

# Interfaz simple de envío por consola
def input_loop():
    while True:
        line = input(f"[{NODE_NAME}] Escribe destino:mensaje >> ").strip()
        if ":" not in line:
            print("Formato inválido. Usa destino:mensaje")
            continue
        destino, mensaje = line.split(":", 1)
        send_message(destino.strip(), mensaje.strip())

if __name__ == "__main__":
    threading.Thread(target=start_server, daemon=True).start()
    input_loop()
