import socket, threading, time, os, json, random, uuid
from datetime import datetime
from typing import Optional

HOST = "0.0.0.0"
PORT = int(os.getenv("PORT", "5000"))
SELF_NAME = os.getenv("SELF_NAME", socket.gethostname())

# ---- Configuración ajustable ----
CONNECT_TIMEOUT = float(os.getenv("CONNECT_TIMEOUT", "30"))
CLIENT_INTERVAL = float(os.getenv("CLIENT_INTERVAL", "5"))
CLIENT_JITTER   = float(os.getenv("CLIENT_JITTER", "1.0"))
BACKOFF_BASE    = float(os.getenv("BACKOFF_BASE", "1.0"))
BACKOFF_MAX     = float(os.getenv("BACKOFF_MAX", "10.0"))
RETRIES_DIRECT  = int(os.getenv("RETRIES_DIRECT", "1"))
RETRIES_ROUTE   = int(os.getenv("RETRIES_ROUTE", "1"))
RETRIES_BROAD   = int(os.getenv("RETRIES_BROAD", "0"))
IDLE_SLEEP      = float(os.getenv("IDLE_SLEEP", "1.0"))

# ---- Topología ----
PEERS = [p for p in os.getenv("PEERS", "").split(",") if p]
peers_list = []
for p in PEERS:
    if ":" in p:
        ip, port = p.split(":")
        peers_list.append({"ip": ip.strip(), "port": int(port)})

DESTINOS = [d for d in os.getenv("DESTINOS", "").split(",") if d]

ROUTES = [r for r in os.getenv("ROUTES", "").split(",") if r]
routing_table = {}
for r in ROUTES:
    if ":" in r:
        dest, next_ip, next_port = r.split(":")
        routing_table[dest.strip()] = {"ip": next_ip.strip(), "port": int(next_port)}

# --- Mapeo de IP a Nombre y Nombre a IP ---
NODE_MAP_STR = os.getenv("NODE_MAP", "")
IP_TO_NAME = {}  # IP -> Nombre (ej: "10.104.224.255" -> "node1")
NAME_TO_IP = {}  # Nombre -> IP (ej: "node1" -> "10.104.224.255")
for item in NODE_MAP_STR.split(","):
    if ":" in item:
        name, ip = item.split(":")
        name = name.strip()
        ip = ip.strip()
        IP_TO_NAME[ip] = name
        NAME_TO_IP[name] = ip

# ---- Estado ----
peer_backoff = {}

# ---------------- JSON logger ----------------
def log_json(level: str, event: str, msg: str, data: Optional[dict] = None):
    entry = {
        "timestamp": datetime.utcnow().isoformat() + "Z",
        "level": level,
        "node": SELF_NAME,
        "event": event,
        "message": msg,
    }
    if data:
        entry["data"] = data
    print(json.dumps(entry, ensure_ascii=False), flush=True)

# ---------------- Backoff helpers ----------------
def _allow_attempt(peer_ip):
    _, next_ts = peer_backoff.get(peer_ip, (0.0, 0.0))
    return time.time() >= next_ts

def _on_success(peer_ip):
    peer_backoff[peer_ip] = (BACKOFF_BASE, time.time())

def _on_failure(peer_ip):
    cur, _ = peer_backoff.get(peer_ip, (BACKOFF_BASE, 0.0))
    nxt = min(max(cur * 2, BACKOFF_BASE), BACKOFF_MAX)
    peer_backoff[peer_ip] = (nxt, time.time() + cur + random.uniform(0, cur * 0.25))

# ---------------- Servidor ----------------
def server():
    delay = 0.5
    while True:
        try:
            s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            s.bind((HOST, PORT))
            s.listen()
            log_json("INFO", "server_start", f"Listening on {HOST}:{PORT}")
            break
        except Exception as e:
            log_json("WARNING", "server_retry", f"Bind failed: {e}, retrying {delay}s")
            time.sleep(delay)
            delay = min(delay * 2, 5.0)
    with s:
        while True:
            try:
                conn, _ = s.accept()
                threading.Thread(target=handle_connection, args=(conn,), daemon=True).start()
            except Exception as e:
                log_json("ERROR", "server_accept", f"Error: {e}")
                time.sleep(0.1)

def handle_connection(conn):
    with conn:
        data = conn.recv(4096).decode()
        if not data:
            return
        try:
            msg = json.loads(data)
            dest = msg.get("destination")
            prev = msg.get("last_hop")  # 'prev' es un NOMBRE
            route = msg.get("route", [])
            if SELF_NAME not in route:
                route.append(SELF_NAME)
            msg["route"] = route

            if dest == SELF_NAME:
                msg["status"] = "DELIVERED"
                log_json("INFO", "msg_received", f"Delivered to {SELF_NAME}", msg)
            else:
                log_json("INFO", "msg_forward", f"Forwarding to {dest}", msg)
                forward_message(msg, exclude_node=prev)
        except Exception as e:
            log_json("ERROR", "msg_error", f"Failed to process: {e}")

# ---------------- Envíos ----------------
def _try_send(peer_ip, port, msg, retries, label):
    peer_name = IP_TO_NAME.get(peer_ip, peer_ip)
    
    for attempt in range(retries + 1):
        if not _allow_attempt(peer_ip):
            log_json("DEBUG", "backoff_skip", f"Skipping {peer_name} (backoff active)", {"peer": peer_name})
            return False
        try:
            with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
                s.settimeout(CONNECT_TIMEOUT)
                s.connect((peer_ip, port))
                s.sendall(json.dumps(msg).encode())
            _on_success(peer_ip)
            log_json("INFO", label, f"Sent to {peer_name}", {"peer": peer_name})
            return True
        except Exception as e:
            _on_failure(peer_ip)
            log_json("WARNING", "send_fail", f"Failed to send to {peer_name}: {e}", {"attempt": attempt, "peer": peer_name})
            time.sleep(min(0.2 * (attempt + 1), 1.0))
    return False

# ---------------- Rutas ----------------
def forward_message(msg, exclude_node=None):
    """
    exclude_node: NOMBRE del nodo del que NO queremos recibir mensajes de vuelta
    """
    dest = msg["destination"]
    msg["last_hop"] = SELF_NAME

    # 1) Intento directo a peer si es el destino
    dest_ip = NAME_TO_IP.get(dest)
    if dest_ip:
        for peer in peers_list:
            if peer["ip"] == dest_ip:
                # Verificar que no sea el nodo que nos envió el mensaje
                if exclude_node and IP_TO_NAME.get(peer["ip"]) == exclude_node:
                    continue
                    
                if _try_send(peer["ip"], peer["port"], msg, RETRIES_DIRECT, "direct_send"):
                    return
                else:
                    # Fallo directo, intentar re-ruta
                    return handle_reroute(msg, exclude_node, dest, prev_failed_ip=peer["ip"])

    # 2) Ruta estática
    if dest in routing_table:
        next_hop = routing_table[dest]
        next_hop_ip = next_hop["ip"]
        next_hop_name = IP_TO_NAME.get(next_hop_ip)
        
        # Evitar enviar de vuelta al nodo que nos lo mandó
        if exclude_node and next_hop_name == exclude_node:
            log_json("WARNING", "route_skip", f"Skipping route via {next_hop_name} (would loop back)", {"dest": dest})
            return handle_reroute(msg, exclude_node, dest, prev_failed_ip=None)
        
        if _try_send(next_hop_ip, next_hop["port"], msg, RETRIES_ROUTE, "route_forward"):
            return
        else:
            return handle_reroute(msg, exclude_node, dest, prev_failed_ip=next_hop_ip)

    # 3) Desconocido: re-ruta
    handle_reroute(msg, exclude_node, dest, prev_failed_ip=None)

def handle_reroute(msg, exclude_node, dest, prev_failed_ip):
    """
    Busca alternativa entre vecinos:
      - NO reintenta por el que ya falló (prev_failed_ip es una IP).
      - NO reintenta por el que lo envió (exclude_node es un NOMBRE).
    Si envía con éxito, actualiza routing_table[dest].
    """
    for peer in peers_list:
        peer_ip = peer["ip"]
        peer_name = IP_TO_NAME.get(peer_ip)
        
        # Evitar devolver al que nos lo envió
        if exclude_node and peer_name == exclude_node:
            continue
        
        # Evitar reintentar con el que ya falló
        if prev_failed_ip and peer_ip == prev_failed_ip:
            continue

        if _try_send(peer_ip, peer["port"], msg, RETRIES_ROUTE, "reroute_success"):
            routing_table[dest] = {"ip": peer_ip, "port": peer["port"]}
            log_json("INFO", "route_update", f"Updated route to {dest} via {peer_name}", {"dest": dest})
            return
            
    msg["status"] = "FAILED"
    log_json("ERROR", "route_failed", f"No available route to {dest}", {"dest": dest})

def broadcast_message(msg, exclude_node=None):
    any_ok = False
    exclude_ip = NAME_TO_IP.get(exclude_node) if exclude_node else None
    
    for peer in peers_list:
        if exclude_ip and peer["ip"] == exclude_ip:
            continue
        if _try_send(peer["ip"], peer["port"], msg, RETRIES_BROAD, "broadcast"):
            any_ok = True
    if not any_ok:
        time.sleep(IDLE_SLEEP)

# ---------------- Cliente ----------------
def client():
    time.sleep(2)
    while True:
        if not DESTINOS:
            time.sleep(IDLE_SLEEP)
            continue
        interval = max(0.1, CLIENT_INTERVAL + random.uniform(-CLIENT_JITTER, CLIENT_JITTER))
        for dest in DESTINOS:
            msg = {
                "id": str(uuid.uuid4()),
                "type": "data",
                "source": SELF_NAME,
                "destination": dest,
                "payload": f"Hola desde {SELF_NAME} a {dest}",
                "last_hop": SELF_NAME,
                "route": [SELF_NAME],
                "status": "IN_PROGRESS"
            }
            log_json("INFO", "msg_send", f"Sending message to {dest}", msg)
            forward_message(msg)
        time.sleep(interval)

# ---------------- Lanzar ----------------
threading.Thread(target=server, daemon=True).start()
threading.Thread(target=client, daemon=True).start()
while True:
    time.sleep(1)
