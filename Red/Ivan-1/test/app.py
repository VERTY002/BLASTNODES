import socket
import threading
import time
import os
import json

# Configuración del host y puerto en el que escuchará el servidor
HOST = "0.0.0.0"
PORT = int(os.getenv("PORT"))  # Puerto obtenido desde una variable de entorno

# --------------------------
# Configuración de vecinos y rutas
# --------------------------

# Lista de vecinos directamente conectados (formato: nombre:puerto)
PEERS = os.getenv("PEERS", "").split(",")
peers_list = []
for p in PEERS:
    if ":" in p:
        name, port = p.split(":")
        peers_list.append({"name": name, "port": int(port)})

# Lista de destinos a los que este nodo debe enviar mensajes
DESTINOS = os.getenv("DESTINOS", "").split(",")

# Tabla de enrutamiento estática (formato: destino:nombre_vecino:puerto_vecino)
ROUTES = os.getenv("ROUTES", "").split(",")
routing_table = {}
for r in ROUTES:
    if ":" in r:
        dest, next_name, next_port = r.split(":")
        routing_table[dest] = {"name": next_name, "port": int(next_port)}

# -------------------------
# Función del servidor TCP
# -------------------------
def server():
    """Inicia un servidor TCP para recibir conexiones entran tes de otros nodos."""
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind((HOST, PORT))
        s.listen()
        print(f"Servidor escuchando en {HOST}:{PORT}", flush=True)
        while True:
            conn, addr = s.accept()
            # Cada conexión se maneja en un hilo separado
            threading.Thread(target=handle_connection, args=(conn,), daemon=True).start()

def handle_connection(conn):
    """Procesa un mensaje entrante recibido a través de una conexión TCP."""
    with conn:
        data = conn.recv(4096).decode()
        if data:
            try:
                msg = json.loads(data)
                dest = msg["destination"]
                payload = msg["payload"]
                prev_hop = msg.get("last_hop")

                # Si el mensaje es para este nodo, se imprime
                if dest == socket.gethostname():
                    print(f"{socket.gethostname()} recibió mensaje: {payload}", flush=True)
                else:
                    # Si no, se reenvía al siguiente nodo
                    forward_message(msg, exclude_host=prev_hop)
            except Exception as e:
                print("Error procesando mensaje:", e, flush=True)

# -------------------------
# Funciones de reenvío de mensajes
# -------------------------

def forward_message(msg, exclude_host=None):
    """
    Reenvía un mensaje hacia su destino usando:
    1. Conexión directa si el destino es un vecino
    2. Ruta especificada en la tabla de enrutamiento
    3. Broadcast a todos los vecinos si no hay ruta directa o en tabla
    """
    dest = msg["destination"]
    msg["last_hop"] = socket.gethostname()

    # 1. Verificar si el destino es un vecino directo
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
                # Si falla, intenta broadcast
                return broadcast_message(msg, exclude_host)

    # 2. Verificar si hay una ruta definida en la tabla de enrutamiento
    if dest in routing_table:
        peer = routing_table[dest]
        try:
            with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
                s.settimeout(1)
                s.connect((peer["name"], peer["port"]))
                s.sendall(json.dumps(msg).encode())
            print(f"{socket.gethostname()} reenvía a {peer['name']} hacia {dest}", flush=True)
            return
        except Exception as e:
            print(f"{socket.gethostname()} fallo ruta en tabla a {peer['name']}: {e}", flush=True)
            return broadcast_message(msg, exclude_host)

    # 3. Si no hay ruta conocida, hacer broadcast
    broadcast_message(msg, exclude_host)

def broadcast_message(msg, exclude_host=None):
    """
    Reenvía un mensaje a todos los vecinos (excepto al que lo envió)
    como último recurso si no se encuentra una ruta directa o en la tabla.
    """
    for peer in peers_list:
        if peer["name"] == exclude_host:
            continue  # Evitar reenvío al remitente

        try:
            with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
                s.settimeout(1)
                s.connect((peer["name"], peer["port"]))
                s.sendall(json.dumps(msg).encode())
            print(f"{socket.gethostname()} broadcast a {peer['name']} hacia {msg['destination']}", flush=True)
        except Exception as e:
            print(f"{socket.gethostname()} fallo broadcast a {peer['name']}: {e}", flush=True)

# --------------------------
# Cliente que genera tráfico
# --------------------------

def client():
    """
    Cliente que periódicamente envía mensajes a los destinos configurados,
    utilizando el sistema de enrutamiento para llegar a ellos.
    """
    while True:
        if not DESTINOS or DESTINOS == [""]:
            time.sleep(1)
            continue

        for dest in DESTINOS:
            msg = {
                "source": socket.gethostname(),
                "destination": dest,
                "payload": f"Hola desde {socket.gethostname()} a {dest}",
                "last_hop": socket.gethostname()
            }
            forward_message(msg)
        time.sleep(5)  # Espera antes de volver a enviar

# --------------------------
# Lanzamiento de hilos del servidor y cliente
# --------------------------

# Se ejecutan como demonios para que terminen con el proceso principal
threading.Thread(target=server, daemon=True).start()
threading.Thread(target=client, daemon=True).start()

# Bucle principal que mantiene el programa activo
while True:
    time.sleep(1)