
# -*- coding: utf-8 -*-
import socket, threading, time, os, json, random, uuid
from datetime import datetime
from typing import Optional

HOST = "0.0.0.0"
PORT = int(os.getenv("PORT", "5000"))
SELF_NAME = os.getenv("SELF_NAME", socket.gethostname())

# ---- Configuración ajustable ----
CONNECT_TIMEOUT = float(os.getenv("CONNECT_TIMEOUT", "5"))
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
        n, port = p.split(":")
        peers_list.append({"name": n.strip(), "port": int(port)})

DESTINOS = [d for d in os.getenv("DESTINOS", "").split(",") if d]

ROUTES = [r for r in os.getenv("ROUTES", "").split(",") if r]
routing_table = {}
for r in ROUTES:
    if ":" in r:
        dest, next_name, next_port = r.split(":")
        routing_table[dest.strip()] = {"name": next_name.strip(), "port": int(next_port)}

# ---- Estado ----
peer_backoff = {}
peer_lastlog = {}

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
def _allow_attempt(peer):
    _, next_ts = peer_backoff.get(peer, (0.0, 0.0))
    return time.time() >= next_ts

def _on_success(peer):
    peer_backoff[peer] = (BACKOFF_BASE, time.time())

def _on_failure(peer):
    cur, _ = peer_backoff.get(peer, (BACKOFF_BASE, 0.0))
    nxt = min(max(cur * 2, BACKOFF_BASE), BACKOFF_MAX)
    peer_backoff[peer] = (nxt, time.time() + cur + random.uniform(0, cur * 0.25))

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
            prev = msg.get("last_hop")
            route = msg.get("route", [])
            if SELF_NAME not in route:
                route.append(SELF_NAME)
            msg["route"] = route

            if dest == SELF_NAME:
                msg["status"] = "DELIVERED"
                log_json("INFO", "msg_received", f"Delivered to {SELF_NAME}", msg)
            else:
                log_json("INFO", "msg_forward", f"Forwarding to {dest}", msg)
                forward_message(msg, exclude_host=prev)
        except Exception as e:
            log_json("ERROR", "msg_error", f"Failed to process: {e}")

# ---------------- Envíos ----------------
def _try_send(name, port, msg, retries, label):
    for attempt in range(retries + 1):
        if not _allow_attempt(name):
            log_json("DEBUG", "backoff_skip", f"Skipping {name} (backoff active)", {"peer": name})
            return False
        try:
            with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
                s.settimeout(CONNECT_TIMEOUT)
                s.connect((name, port))
                s.sendall(json.dumps(msg).encode())
            _on_success(name)
            log_json("INFO", label, f"Sent to {name}:{port}", {"peer": name})
            return True
        except Exception as e:
            _on_failure(name)
            log_json("WARNING", "send_fail", f"Failed to send to {name}:{port}: {e}", {"attempt": attempt})
            time.sleep(min(0.2 * (attempt + 1), 1.0))
    return False

# ---------------- Rutas ----------------
def forward_message(msg, exclude_host=None):
    dest = msg["destination"]
    msg["last_hop"] = SELF_NAME

    for peer in peers_list:
        if dest == peer["name"]:
            if _try_send(peer["name"], peer["port"], msg, RETRIES_DIRECT, "direct_send"):
                return
            else:
                return broadcast_message(msg, exclude_host)

    if dest in routing_table:
        peer = routing_table[dest]
        if peer["name"] != exclude_host:
            if _try_send(peer["name"], peer["port"], msg, RETRIES_ROUTE, "route_forward"):
                return
            else:
                return handle_reroute(msg, exclude_host, dest, peer)

    handle_reroute(msg, exclude_host, dest, None)

def handle_reroute(msg, exclude_host, dest, prev_peer):
    for peer in peers_list:
        if prev_peer and peer["name"] == prev_peer["name"]:
            continue
        if exclude_host and peer["name"] == exclude_host:
            continue
        if _try_send(peer["name"], peer["port"], msg, RETRIES_ROUTE, "reroute_success"):
            routing_table[dest] = {"name": peer["name"], "port": peer["port"]}
            log_json("INFO", "route_update", f"Updated route to {dest} via {peer['name']}")
            return
    msg["status"] = "FAILED"
    log_json("ERROR", "route_failed", f"No available route to {dest}")

def broadcast_message(msg, exclude_host=None):
    any_ok = False
    for peer in peers_list:
        if peer["name"] == exclude_host:
            continue
        if _try_send(peer["name"], peer["port"], msg, RETRIES_BROAD, "broadcast"):
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
