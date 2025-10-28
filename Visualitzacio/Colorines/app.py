
import socket
import threading
import time
import os
import json
from prometheus_client import start_http_server, Counter, Histogram, Gauge

HOST = "0.0.0.0"
PORT = int(os.getenv("PORT"))
METRICS_PORT = int(os.getenv("METRICS_PORT", 8000))

mensajes_enviados = Counter('mensajes_enviados_total', 'Total de mensajes enviados', ['destino'])
mensajes_recibidos = Counter('mensajes_recibidos_total', 'Total de mensajes recibidos', ['origen'])
mensajes_reenviados = Counter('mensajes_reenviados_total', 'Total de mensajes reenviados', ['destino'])
mensajes_totales = Counter('mensajes_totales_total', 'Total de mensajes enviados y reenviados', ['destino'])
mensajes_nodo_a_nodo = Counter(
    'mensajes_nodo_a_nodo_total',
    'Total de mensajes entre nodos',
    ['source', 'destination', 'from_node', 'to_node']
)
# Añadido para visualizacion
conexiones_activas = Gauge(
    'conexiones_activas',
    'Estado de la conexión entre nodos (1=activa, 0=caida)',
    ['desde_nodo', 'hacia_nodo']
)

estado_nodo = Gauge(
    'estado_nodo',
    'Estado del nodo (1=activo, 0=caido)',
    ['nodo']
)

mensajes_en_conexion = Gauge(
    'mensajes_en_conexion',
    'Numero de mensajes en una conexión',
    ['source', 'target']
)

latencia_conexion = Gauge(
    'latencia_conexion_ms',
    'Latencia en milisegundos entre nodos',
    ['desde_nodo', 'hacia_nodo', 'color']
)

latencia_mensajes = Histogram(
    'latencia_histogram_seconds',
    'Distribución de latencias',
    ['desde_nodo', 'hacia_nodo'],
    buckets=(0.001, 0.005, 0.01, 0.05, 0.1, 0.5, 1.0, 2.0, 5.0)
)

color_estado_conexion = Gauge(
    'color_estado_conexion',
    'Código de color de la conexión (1=verde,2=amarillo,3=naranja,4=rojo)',
    ['desde_nodo', 'hacia_nodo']
)

estado_salud_nodo = Gauge(
    'estado_salud_nodo',
    'Estat de salut del node (0-100)',
    ['nodo']
)

trafico_exitoso = Counter(
    'trafico_exitoso_total',
    'Trànsit exitós del node',
    ['nodo']
)

trafico_fallido = Counter(
    'trafico_fallido_total', 
    'Trànsit fallit del node',
    ['nodo']
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

print(f"[{socket.gethostname()}] Configuración cargada: {len(peers_list)} peers, {len(DESTINOS)} destinos", flush=True)

def calcular_color(latency_ms):
    if latency_ms >= 9999:
        return "rojo"
    elif latency_ms > 200:
        return "naranja"
    elif latency_ms > 50:
        return "amarillo"
    else:
        return "verde"

# ---------------- Servidor ----------------
def server():
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        s.bind((HOST, PORT))
        s.listen()
        print(f"Servidor escuchando en {HOST}:{PORT}", flush=True)
        # el servidor es un nodo asi que marcamos este en activo
        estado_nodo.labels(nodo=socket.gethostname()).set(1)
        while True:
            conn, addr = s.accept()
            threading.Thread(target=handle_connection, args=(conn,), daemon=True).start()


def handle_connection(conn, addr):
    with conn:
        data = conn.recv(4096).decode()
        if not data:
            return
        if data == "PING":
            conn.sendall(b"PONG")
            return
        try:
            msg = json.loads(data)
            dest = msg["destination"]
            payload = msg["payload"]
            prev_hop = msg.get("last_hop")
            #registramos el mensaje que se recibe
            mensajes_recibidos.labels(origen=str(addr)).inc()
            if prev_hop:
                mensajes_en_conexion.labels(
                    source=prev_hop,
                    target=socket.gethostname()
                ).inc()
            if dest == socket.gethostname():
                print(f"{socket.gethostname()} recibió mensaje: {payload}", flush=True)
            else:
                forward_message(msg, exclude_host=prev_hop)
            conn.sendall(f"OK de {socket.gethostname()}".encode("utf-8"))
        except json.JSONDecodeError:
            print(f"[{socket.gethostname()}] mensaje no válido: '{data}'", flush=True)
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
            success, latency = send_with_latency(peer, msg)
            if success:
                print(f"[{socket.gethostname()}] Envío directo a {dest} (latencia: {latency:.2f}ms)", flush=True)
                mensajes_totales.labels(destino=dest).inc()
                mensajes_en_conexion.labels(
                    source=socket.gethostname(),
                    target=peer["name"]
                ).inc()
                mensajes_nodo_a_nodo.labels(
                    source=msg["source"],
                    destination=dest,
                    from_node=from_node,
                    to_node=peer["name"]
                ).inc()
                return
            else:
                print(f"[{socket.gethostname()}] fallo ruta directa a {peer['name']}", flush=True)
                return broadcast_message(msg, from_node, exclude_host)

    # --- 2. Si hay ruta en la tabla de enrutamiento ---
    if dest in routing_table:
        peer = routing_table[dest]
        success, latency = send_with_latency(peer, msg)
        if success:
            print(f"[{socket.gethostname()}] reenvío a {peer['name']} hacia {dest} (latencia: {latency:.2f}ms)", flush=True)
            mensajes_totales.labels(destino=dest).inc()
            mensajes_en_conexion.labels(
                source=socket.gethostname(),
                target=peer["name"]
            ).inc()
            mensajes_nodo_a_nodo.labels(
                source=msg["source"],
                destination=dest,
                from_node=from_node,
                to_node=peer["name"]
            ).inc()
            return
        else:
            print(f"[{socket.gethostname()}] fallo ruta en tabla a {peer['name']}", flush=True)
            return broadcast_message(msg, from_node, exclude_host)

    # --- 3. Si no hay ruta conocida ---
    broadcast_message(msg, from_node, exclude_host)

def send_with_latency(peer, msg):
    try:
        start_time = time.time()
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            s.settimeout(2)
            s.connect((peer["name"], peer["port"]))
            s.sendall(json.dumps(msg).encode())
            s.recv(1024)
        latency_seconds = time.time() - start_time
        latency_ms = latency_seconds * 1000
        color = calcular_color(latency_ms)
        # Actualizar métricas con color como label
        latencia_mensajes.labels(
            desde_nodo=socket.gethostname(),
            hacia_nodo=peer["name"]
        ).observe(latency_seconds)
        latencia_conexion.labels(
            desde_nodo=socket.gethostname(),
            hacia_nodo=peer["name"],
            color=color
        ).set(latency_ms)
        return True, latency_ms
    except Exception:
        color = "rojo"
        latencia_conexion.labels(
            desde_nodo=socket.gethostname(),
            hacia_nodo=peer["name"],
            color="rojo"
        ).set(9999)
        return False, 0

def broadcast_message(msg, from_node, exclude_host=None):
    # Reenvía el mensaje a todos los vecinos menos al que lo envió
    for peer in peers_list:
        if peer["name"] == exclude_host:
            continue
        success, latency = send_with_latency(peer, msg)
        if success:
            print(f"[{socket.gethostname()}] broadcast a {peer['name']} hacia {msg['destination']} (latencia: {latency:.2f}ms)", flush=True)
            mensajes_totales.labels(destino=msg["destination"]).inc()
            mensajes_en_conexion.labels(
                source=socket.gethostname(),
                target=peer["name"]
            ).inc()
            mensajes_nodo_a_nodo.labels(
                source=msg["source"],
                destination=msg["destination"],
                from_node=from_node,
                to_node=peer["name"]
            ).inc()
        else:
            print(f"[{socket.gethostname()}] fallo broadcast a {peer['name']}", flush=True)

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
                "payload": f"Hola desde {socket.gethostname()} a {dest} [{time.time():.0f}]",
                "last_hop": socket.gethostname()  # el origen es el primer "last_hop"
            }
            forward_message(msg)
            mensajes_enviados.labels(destino=dest).inc()
        time.sleep(5)



# ---------------- Conexiones ----------------
def connection_state():
    while True:
        my_name = socket.gethostname()
        # Actualitzar estat del node com actiu
        estado_nodo.labels(nodo=my_name).set(1)
        estado_salud_nodo.labels(nodo=my_name).set(95)  # 95% de salut per defecte
        
        total_connections = 0
        successful_connections = 0

        for peer in peers_list:
            try:
                start_time = time.time()
                with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
                    s.settimeout(2)
                    s.connect((peer["name"], peer["port"]))
                    s.sendall(b"PING")
                    response = s.recv(1024)
                
                if response == b"PONG":
                    successful_connections += 1
                    trafico_exitoso.labels(nodo=my_name).inc()

                latency_seconds = time.time() - start_time
                latency_ms = latency_seconds * 1000
                color = calcular_color(latency_ms)
                # Conexión activa
                conexiones_activas.labels(
                    desde_nodo=my_name,
                    hacia_nodo=peer["name"]
                ).set(1)

                 # Actualitzar color de connexió
                color_valor = {"verde": 1, "amarillo": 2, "naranja": 3, "rojo": 4}.get(color, 4)
                color_estado_conexion.labels(
                    desde_nodo=my_name,
                    hacia_nodo=peer["name"]
                ).set(color_valor)

                latencia_conexion.labels(
                    desde_nodo=my_name,
                    hacia_nodo=peer["name"],
                    color=color
                ).set(latency_ms)
            except Exception:
                trafico_fallido.labels(nodo=my_name).inc()
                conexiones_activas.labels(
                    desde_nodo=my_name,
                    hacia_nodo=peer["name"]
                ).set(4) #vermell
                latencia_conexion.labels(
                    desde_nodo=my_name,
                    hacia_nodo=peer["name"],
                    color="rojo"
                ).set(9999)
            total_connections += 1
         # Calcular estat de salut basat en connexions exitoses
        if total_connections > 0:
            health_percentage = (successful_connections / total_connections) * 100
            estado_salud_nodo.labels(nodo=my_name).set(health_percentage)
            
        time.sleep(3)

# ---------------- Lanzar hilos ----------------
if __name__ == "__main__":
    threading.Thread(target=server, daemon=True).start()
    threading.Thread(target=client, daemon=True).start()
    threading.Thread(target=connection_state, daemon=True).start()
    start_http_server(METRICS_PORT)
    print(f"{socket.gethostname()} iniciado. Métricas en puerto {METRICS_PORT}", flush=True)
    while True:
        time.sleep(1)
