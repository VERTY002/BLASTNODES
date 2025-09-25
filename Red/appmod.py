import socket
import threading
import os
import time
import uuid

# Configuración
HOST = "0.0.0.0"
PORT = int(os.getenv("PORT", 5000))
NODE_NAME = os.getenv("NODE_NAME", "nodo")
PEERS = os.getenv("PEERS", "").split(",")

# Mensajes ya procesados para evitar loops
processed_messages = set()
lock = threading.Lock()  # Para acceder a processed_messages de forma segura

def handle_client(conn, addr):
    try:
        data = conn.recv(1024).decode("utf-8")
        if not data:
            return

        # Separar ID y contenido
        msg_id, msg_content = data.split(";", 1)

        with lock:
            if msg_id in processed_messages:
                return  # Ya procesado, ignorar
            processed_messages.add(msg_id)

        print(f"[{NODE_NAME}] Mensaje recibido de {addr}: {msg_content}")

        # Reenviar a todos los peers excepto el que lo envió
        for peer in PEERS:
            if not peer.strip() or f"{addr[0]}:{addr[1]}" == peer:
                continue
            host, port = peer.split(":")
            try:
                with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
                    s.settimeout(2)
                    s.connect((host, int(port)))
                    s.sendall(data.encode("utf-8"))
            except:
                pass

        # Responder al cliente original
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

def send_message_to_network(message):
    msg_id = str(uuid.uuid4())  # ID único para este mensaje
    full_message = f"{msg_id};{message}"

    for peer in PEERS:
        if not peer.strip():
            continue
        host, port = peer.split(":")
        try:
            with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
                s.settimeout(2)
                s.connect((host, int(port)))
                s.sendall(full_message.encode("utf-8"))
        except Exception as e:
            print(f"[{NODE_NAME}] No se pudo enviar a {peer}: {e}")

if __name__ == "__main__":
    # Hilo para escuchar conexiones entrantes
    threading.Thread(target=start_server, daemon=True).start()

    # Ejemplo: enviar mensaje a toda la red cada 10 segundos
    while True:
        msg = f"Hola desde {NODE_NAME}"
        send_message_to_network(msg)
        time.sleep(10)

