import socket
import threading
import time
import os
import json

HOST = "0.0.0.0"
PORT = int(os.getenv("PORT"))
PEERS = os.getenv("PEERS", "").split(",")  # vecinos físicos
DESTINOS = os.getenv("DESTINOS", "").split(",")  # nodos finales a los que enviar

peers_list = []
for p in PEERS:
    if ":" in p:
        name, port = p.split(":")
        peers_list.append({"name": name, "port": int(port)})

# Servidor que recibe y reenvía mensajes
def server():
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind((HOST, PORT))
        s.listen()
        print(f"Servidor escuchando en {HOST}:{PORT}", flush=True)
        while True:
            conn, addr = s.accept()
            threading.Thread(target=handle_connection, args=(conn, addr), daemon=True).start()

def handle_connection(conn, addr):
    with conn:
        data = conn.recv(4096).decode()
        if data:
            try:
                msg = json.loads(data)
                dest = msg["destination"]
                payload = msg["payload"]
                if dest == socket.gethostname():
                    print(f"Recibido mensaje para mí: {payload}", flush=True)
                else:
                    # Reenviar a todos los peers menos al que nos lo envió
                    forward_message(msg, exclude_host=addr[0])
            except Exception as e:
                print("Error procesando mensaje:", e, flush=True)

def forward_message(msg, exclude_host=None):
    for peer in peers_list:
        if peer["name"] != exclude_host:
            try:
                with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
                    s.settimeout(1)
                    s.connect((peer["name"], peer["port"]))
                    s.sendall(json.dumps(msg).encode())
                    print(f"Reenvio el mensaje porque es para {dest}, y yo soy {socket.gethostname()}",flush=True)
            except Exception:
                pass

# Cliente que envía mensajes a destinos finales
def client():
    while True:
        for dest in DESTINOS:
            msg = {
                "source": socket.gethostname(),
                "destination": dest,
                "payload": f"Hola desde {socket.gethostname()} a {dest}"
            }
            forward_message(msg)
        time.sleep(5)

threading.Thread(target=server, daemon=True).start()
threading.Thread(target=client, daemon=True).start()

while True:
    time.sleep(1)
#CODIGO JOAQUÍN

