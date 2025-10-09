import socket
import threading
import time
import os
import json

HOST = "0.0.0.0"
PORT = int(os.getenv("PORT"))

# Vecinos físicos (nodos directamente conectados)
PEERS = os.getenv("PEERS", "").split(",")
peers_list = []
for p in PEERS:
    if ":" in p:
        name, port = p.split(":")
        peers_list.append({"name": name, "port": int(port)})

# Destinos a los que este nodo genera tráfico
DESTINOS = os.getenv("DESTINOS", "").split(",")

# Tabla de enrutamiento (destino -> vecino por el que salir)
ROUTES = os.getenv("ROUTES", "").split(",")
routing_table = {}
for r in ROUTES:
    if ":" in r:
        dest, next_name, next_port = r.split(":")
        routing_table[dest] = {"name": next_name, "port": int(next_port)}


# ---------------- Servidor ----------------
def server():
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind((HOST, PORT))
        s.listen()
        print(f"Servidor escuchando en {HOST}:{PORT}", flush=True)
        while True:
            conn, addr = s.accept()
            threading.Thread(target=handle_connection, args=(conn,), daemon=True).start()


def handle_connection(conn):
    with conn:
        data = conn.recv(4096).decode()
        if data:
            try:
                msg = json.loads(data)
                dest = msg["destination"]
                payload = msg["payload"]
                prev_hop = msg.get("last_hop")

                if dest == socket.gethostname():
                    print(f"{socket.gethostname()} recibió mensaje: {payload}", flush=True)
                else:
                    forward_message(msg, exclude_host=prev_hop)
            except Exception as e:
                print("Error procesando mensaje:", e, flush=True)


# ---------------- Reenvío ----------------
def forward_message(msg, exclude_host=None):
    dest = msg["destination"]
    msg["last_hop"] = socket.gethostname()

    # --- 1. Verificar si el destino está directamente conectado ---
    for peer in peers_list:
        if dest == peer["name"]:
            try:
                with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
                    s.settimeout(1)
                    s.connect((peer["name"], peer["port"]))
                    s.sendall(json.dumps(msg).encode())
                print(f"{socket.gethostname()} envía directo a {dest}", flush=True)
                return
            except Exception as e:
                print(f"{socket.gethostname()} fallo ruta directa a {peer['name']}: {e}", flush=True)
    # --- 2. Si hay ruta en la tabla de enrutamiento ---
    if dest in routing_table:
        peer = routing_table[dest]
        if peer["name"] == exclude_host:
            return fallo_ruta(msg,peer,exclude_host,dest)
        try:
            with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
                s.settimeout(1)
                s.connect((peer["name"], peer["port"]))
                s.sendall(json.dumps(msg).encode())
            print(f"{socket.gethostname()} reenvía a {peer['name']} hacia {dest}", flush=True)
            return
        except Exception as e:
            print(f"{socket.gethostname()} fallo ruta en tabla a {peer['name']}: {e}", flush=True)
            # fallo ruta en caso de fallo
            return fallo_ruta(msg,peer,exclude_host,dest)

    # --- 3. Si no hay ruta conocida ---
    
    print(f"{socket.gethostname()} no tiene ruta hacia {dest}, intenta enviar a algún vecino", flush=True)
    fallo_ruta(msg, {"name": None, "port": None}, exclude_host, dest)



def fallo_ruta(msg, prev_peer, exclude_host,dest):
    for peer in peers_list:
        # Evitar reenviar al peer que ya falló o al que lo envió antes
        if peer["name"] == prev_peer["name"]:
            continue
        if peer["name"] == exclude_host:
            continue
        try:
            with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
                s.settimeout(1)
                s.connect((peer["name"], peer["port"]))
                s.sendall(json.dumps(msg).encode())
            print(f"{socket.gethostname()} Después del fallo reenvío a {peer['name']} hacia {msg['destination']}", flush=True)
            routing_table[dest] = peer #Actualizamos ruta
            print(f"{socket.gethostname()} actualiza su ruta hacia {dest} a través de {peer}") 
            break  #Salimos después de reenviar a  uno
        except Exception as e:
            print(f"{socket.gethostname()} fallo reenvío a {peer['name']}: {e}", flush=True)

# ---------------- Cliente ----------------
def client():
    while True:
        if not DESTINOS or DESTINOS == [""]:
            time.sleep(1)
            continue

        for dest in DESTINOS:
            msg = {
                "type": "data",
                "source": socket.gethostname(),
                "destination": dest,
                "payload": f"Hola desde {socket.gethostname()} a {dest}",
                "last_hop": socket.gethostname()  # el origen es el primer "last_hop"
            }
            forward_message(msg)
        time.sleep(5)


# ---------------- Lanzar hilos ----------------
threading.Thread(target=server, daemon=True).start()
threading.Thread(target=client, daemon=True).start()

while True:
    time.sleep(1)
