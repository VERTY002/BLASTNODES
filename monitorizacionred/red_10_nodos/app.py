import socket
import threading
import time
import os
import json
from prometheus_client import start_http_server, Counter, Histogram

HOST = "0.0.0.0"
PORT = int(os.getenv("PORT"))
METRICS_PORT = int(os.getenv("METRICS_PORT", 8000))

mensajes_enviados = Counter('mensajes_enviados_total', 'Total de mensajes enviados', ['destino'])
mensajes_reenviados = Counter('mensajes_reenviados_total', 'Total de mensajes reenviados', ['destino'])
mensajes_totales = Counter('mensajes_totales_total', 'Total de mensajes enviados y reenviados', ['destino'])
mensajes_nodo_a_nodo = Counter(
    'mensajes_nodo_a_nodo_total',
    'Total de mensajes entre nodos',
    ['source', 'destination', 'from_node', 'to_node']
)


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
    from_node = msg.get("last_hop")
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
                mensajes_totales.labels(destino=dest).inc()
                to_node = peer["name"]  # nodo al que realmente se envía el mensaje
                mensajes_nodo_a_nodo.labels(
                    source=msg["source"],
                    destination=dest,
                    from_node=from_node,
                    to_node=to_node
                ).inc()
                return
            except Exception as e:
                print(f"{socket.gethostname()} fallo ruta directa a {peer['name']}: {e}", flush=True)
                # broadcast en caso de fallo
                return broadcast_message(msg, from_node, exclude_host)

    # --- 2. Si hay ruta en la tabla de enrutamiento ---
    if dest in routing_table:
        peer = routing_table[dest]
        try:
            with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
                s.settimeout(1)
                s.connect((peer["name"], peer["port"]))
                s.sendall(json.dumps(msg).encode())
            print(f"{socket.gethostname()} reenvía a {peer['name']} hacia {dest}", flush=True)
            mensajes_totales.labels(destino=dest).inc()
            to_node = peer["name"]
            mensajes_nodo_a_nodo.labels(
                source=msg["source"],
                destination=dest,
                from_node=from_node,
                to_node=to_node
            ).inc()
            return
        except Exception as e:
            print(f"{socket.gethostname()} fallo ruta en tabla a {peer['name']}: {e}", flush=True)
            # broadcast en caso de fallo
            return broadcast_message(msg, from_node, exclude_host)

    # --- 3. Si no hay ruta conocida ---
    broadcast_message(msg, from_node, exclude_host)


def broadcast_message(msg, from_node, exclude_host=None):
    # Reenvía el mensaje a todos los vecinos menos al que lo envió
    for peer in peers_list:
        if peer["name"] == exclude_host:
            continue
        try:
            with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
                s.settimeout(1)
                s.connect((peer["name"], peer["port"]))
                s.sendall(json.dumps(msg).encode())
            print(f"{socket.gethostname()} broadcast a {peer['name']} hacia {msg['destination']}", flush=True)
            mensajes_totales.labels(destino=msg["destination"]).inc()
            to_node = peer["name"]
            mensajes_nodo_a_nodo.labels(
                source=msg["source"],
                destination=msg["destination"],
                from_node=from_node,
                to_node=to_node
            ).inc()
        except Exception as e:
            print(f"{socket.gethostname()} fallo broadcast a {peer['name']}: {e}", flush=True)



# ---------------- Cliente ----------------
def client():
    while True:
        if not DESTINOS or DESTINOS == [""]:
            time.sleep(1)
            continue

        for dest in DESTINOS:
            msg = {
                "source": socket.gethostname(),
                "destination": dest,
                "payload": f"Hola desde {socket.gethostname()} a {dest}",
                "last_hop": socket.gethostname()  # el origen es el primer "last_hop"
            }
            forward_message(msg)
            mensajes_enviados.labels(destino=dest).inc()
        time.sleep(5)


# ---------------- Lanzar hilos ----------------
threading.Thread(target=server, daemon=True).start()
threading.Thread(target=client, daemon=True).start()
start_http_server(METRICS_PORT)

while True:
    time.sleep(1)
