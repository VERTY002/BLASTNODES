# import socket
# import threading
# import time
# import os
# import json
# import random

# HOST = "0.0.0.0"
# PORT = int(os.getenv("PORT", "5000"))
# SELF_NAME = os.getenv("SELF_NAME", socket.gethostname())

# # ---- Config tunable por ENV (valores prudentes para K8s) ----
# CONNECT_TIMEOUT = float(os.getenv("CONNECT_TIMEOUT", "5"))      # antes 1–3s → ahora 5s
# CLIENT_INTERVAL = float(os.getenv("CLIENT_INTERVAL", "5"))      # cada cuánto generar mensajes
# CLIENT_JITTER   = float(os.getenv("CLIENT_JITTER", "1.0"))      # jitter [+/-] al intervalo
# BACKOFF_BASE    = float(os.getenv("BACKOFF_BASE", "1.0"))       # backoff inicial por peer
# BACKOFF_MAX     = float(os.getenv("BACKOFF_MAX", "10.0"))       # tope de backoff por peer
# RETRIES_DIRECT  = int(os.getenv("RETRIES_DIRECT", "1"))         # reintentos extra en envíos directos
# RETRIES_ROUTE   = int(os.getenv("RETRIES_ROUTE", "1"))          # reintentos extra en envío por tabla
# RETRIES_BROAD   = int(os.getenv("RETRIES_BROAD", "0"))          # reintentos extra por peer en broadcast
# IDLE_SLEEP      = float(os.getenv("IDLE_SLEEP", "1.0"))         # cuando no hay destinos/peers
# PRINT_THROTTLE  = float(os.getenv("PRINT_THROTTLE", "1.0"))     # anti-spam logs por peer

# # ---- Topología desde ENV ----
# PEERS = [p for p in os.getenv("PEERS", "").split(",") if p]
# peers_list = []
# for p in PEERS:
#     if ":" in p:
#         name, port = p.split(":")
#         peers_list.append({"name": name, "port": int(port)})

# DESTINOS = [d for d in os.getenv("DESTINOS", "").split(",") if d]

# ROUTES = [r for r in os.getenv("ROUTES", "").split(",") if r]
# routing_table = {}
# for r in ROUTES:
#     if ":" in r:
#         dest, next_name, next_port = r.split(":")
#         routing_table[dest] = {"name": next_name, "port": int(next_port)}

# # ---- Estado para backoff/log-throttle por peer ----
# peer_backoff = {}   # peer_name -> (current_backoff_seconds, next_allowed_ts)
# peer_lastlog = {}   # peer_name -> last_log_ts


# def _allow_attempt(peer_name: str) -> bool:
#     """Devuelve True si ya podemos reintentar contra peer_name (según backoff)."""
#     now = time.time()
#     _, next_ts = peer_backoff.get(peer_name, (0.0, 0.0))
#     return now >= next_ts


# def _on_success(peer_name: str):
#     """Resetea backoff al éxito."""
#     peer_backoff[peer_name] = (BACKOFF_BASE, time.time())


# def _on_failure(peer_name: str):
#     """Aumenta backoff exponencialmente (con cap) al fallo."""
#     cur, _ = peer_backoff.get(peer_name, (BACKOFF_BASE, 0.0))
#     nxt = min(max(cur * 2, BACKOFF_BASE), BACKOFF_MAX)
#     # jitter pequeño para evitar sincronía
#     jitter = random.uniform(0, cur * 0.25)
#     peer_backoff[peer_name] = (nxt, time.time() + cur + jitter)


# def _log_throttled(peer_name: str, text: str):
#     """Evita spamear logs por peer más de una vez cada PRINT_THROTTLE segs."""
#     now = time.time()
#     last = peer_lastlog.get(peer_name, 0.0)
#     if now - last >= PRINT_THROTTLE:
#         print(text, flush=True)
#         peer_lastlog[peer_name] = now


# # ---------------- Servidor ----------------
# def server():
#     import errno
#     delay = 0.5
#     while True:
#         try:
#             s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
#             s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
#             s.bind((HOST, PORT))
#             s.listen()
#             print(f"Servidor escuchando en {HOST}:{PORT}", flush=True)
#             break
#         except Exception as e:
#             print(f"[BOOT] No pude bindear {HOST}:{PORT}: {e}; reintento en {delay:.1f}s", flush=True)
#             time.sleep(delay)
#             delay = min(delay * 2, 5.0)
#     with s:
#         while True:
#             try:
#                 conn, addr = s.accept()
#                 threading.Thread(target=handle_connection, args=(conn,), daemon=True).start()
#             except Exception as e:
#                 print(f"[ACCEPT] Error: {e}", flush=True)
#                 time.sleep(0.05)


# def handle_connection(conn):
#     with conn:
#         data = conn.recv(4096).decode()
#         if not data:
#             return
#         try:
#             msg = json.loads(data)
#             dest = msg.get("destination")
#             payload = msg.get("payload")
#             prev_hop = msg.get("last_hop")

#             if dest == SELF_NAME:
#                 print(f"{SELF_NAME} recibió mensaje: {payload}", flush=True)
#             else:
#                 forward_message(msg, exclude_host=prev_hop)
#         except Exception as e:
#             print("Error procesando mensaje:", e, flush=True)


# # ---------------- Reenvío ----------------
# def _try_send(name: str, port: int, msg: dict, retries: int) -> bool:
#     """Intenta enviar con reintentos ligeros y backoff por peer_name."""
#     for attempt in range(retries + 1):
#         if not _allow_attempt(name):
#             _log_throttled(name, f"{SELF_NAME} omite intento a {name}: en backoff")
#             return False
#         try:
#             with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
#                 s.settimeout(CONNECT_TIMEOUT)
#                 s.connect((name, port))
#                 s.sendall(json.dumps(msg).encode())
#             _on_success(name)
#             return True
#         except Exception as e:
#             _on_failure(name)
#             _log_throttled(name, f"{SELF_NAME} fallo envío a {name}: {e}")
#             # pequeño sleep para no girar el bucle pegado
#             time.sleep(min(0.2 * (attempt + 1), 1.0))
#     return False


# def forward_message(msg, exclude_host=None):
#     dest = msg["destination"]
#     msg["last_hop"] = SELF_NAME

#     # 1) Envío directo si el destino es vecino
#     for peer in peers_list:
#         if dest == peer["name"]:
#             if _try_send(peer["name"], peer["port"], msg, RETRIES_DIRECT):
#                 print(f"{SELF_NAME} envía directo a {dest}", flush=True)
#                 return
#             else:
#                 # si no se pudo, intentamos broadcast (sin martillar)
#                 broadcast_message(msg, exclude_host)
#                 return

#     # 2) Rutas estáticas
#     if dest in routing_table:
#         peer = routing_table[dest]
#         if _try_send(peer["name"], peer["port"], msg, RETRIES_ROUTE):
#             print(f"{SELF_NAME} reenvía a {peer['name']} hacia {dest}", flush=True)
#             return
#         else:
#             broadcast_message(msg, exclude_host)
#             return

#     # 3) Desconocido: broadcast
#     broadcast_message(msg, exclude_host)


# def broadcast_message(msg, exclude_host=None):
#     # Reenvía a todos los vecinos (excepto de quien vino) respetando backoff por peer.
#     sent_any = False
#     for peer in peers_list:
#         if peer["name"] == exclude_host:
#             continue
#         ok = _try_send(peer["name"], peer["port"], msg, RETRIES_BROAD)
#         if ok:
#             sent_any = True
#             print(f"{SELF_NAME} broadcast a {peer['name']} hacia {msg['destination']}", flush=True)
#     if not sent_any and not peers_list:
#         # Evita bucles rápidos si ni siquiera hay vecinos definidos
#         time.sleep(IDLE_SLEEP)


# # ---------------- Cliente ----------------
# def client():
#     # pequeño retardo inicial para que DNS/Endpoints asienten
#     time.sleep(2)
#     while True:
#         if not DESTINOS:
#             time.sleep(IDLE_SLEEP)
#             continue

#         # intervalo con jitter ligero para desincronizar envíos
#         interval = max(0.1, CLIENT_INTERVAL + random.uniform(-CLIENT_JITTER, CLIENT_JITTER))

#         for dest in DESTINOS:
#             msg = {
#                 "source": SELF_NAME,
#                 "destination": dest,
#                 "payload": f"Hola desde {SELF_NAME} a {dest}",
#                 "last_hop": SELF_NAME
#             }
#             forward_message(msg)

#         time.sleep(interval)


# # ---------------- Lanzar hilos ----------------
# threading.Thread(target=server, daemon=True).start()
# threading.Thread(target=client, daemon=True).start()

# # Hilo principal en idle light
# while True:
#     time.sleep(1.0)

#!/usr/bin/env python3
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
