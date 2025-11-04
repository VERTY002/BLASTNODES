#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import os
import json
import time
import uuid
import socket
import random
import threading
import contextlib
from contextlib import closing
from datetime import datetime

from prometheus_client import (
    start_http_server,
    Counter,
    Gauge,
    Histogram,
)

# =========================
# Configuración por entorno
# =========================
SELF_NAME = os.getenv("SELF_NAME", None)                  # identidad lógica (node1…node10)
HOSTNAME  = socket.gethostname()                          # nombre del pod (solo logs)
PORT = int(os.getenv("PORT", "5000"))                     # puerto TCP de datos
METRICS_PORT = int(os.getenv("METRICS_PORT", "8000"))     # puerto Prometheus
SOCKET_TIMEOUT = float(os.getenv("SOCKET_TIMEOUT_SEC", "35"))  # para Chaos Mesh con delays largos
SEND_INTERVAL = float(os.getenv("SEND_INTERVAL_SEC", "5"))

# Umbrales de color (ms)
COLOR_YELLOW_MS = float(os.getenv("COLOR_YELLOW_MS", "50"))
COLOR_RED_MS    = float(os.getenv("COLOR_RED_MS", "200"))

# PEERS: "node2,node3,node4"
PEERS = [p.strip() for p in os.getenv("PEERS", "").split(",") if p.strip()]

# DESTINOS: "node7,node8"  (a quién generar tráfico)
DESTINOS = [d.strip() for d in os.getenv("DESTINOS", "").split(",") if d.strip()]

# ROUTES: "node8:node5,node7:node3"   (siguiente salto para destino)
ROUTES_ENV = os.getenv("ROUTES", "")
ROUTES = {}
if ROUTES_ENV:
    for part in ROUTES_ENV.split(","):
        if ":" in part:
            dst, nxt = part.split(":", 1)
            ROUTES[dst.strip()] = nxt.strip()

# Validación básica
if not SELF_NAME:
    # Último recurso: deducir del hostname del pod
    SELF_NAME = HOSTNAME.split("-")[0]

# =========================
# Métricas Prometheus
# =========================
# Estado del nodo (1=up)
ESTADO_NODO = Gauge("estado_nodo", "Estado del nodo (1=UP)", ["nodo"])

# NUEVO: Salud del nodo (0-100)
ESTADO_SALUD_NODO = Gauge("estado_salud_nodo", "Estado de salud del nodo (0-100)", ["nodo"])

# Conexiones activas (última comprobación)
CONEXIONES_ACTIVAS = Gauge(
    "conexiones_activas", "Conectividad TCP exitosa en último chequeo (1/0)", ["desde_nodo", "hacia_nodo"]
)

# Latencia conexión (ms) del último chequeo + color semántico
LATENCIA_CONEXION_MS = Gauge(
    "latencia_conexion_ms", "Latencia (ms) del último chequeo TCP", ["desde_nodo", "hacia_nodo", "color"]
)

# Histograma de latencias “de aplicación” (ACK)
LATENCIA_HISTOGRAM = Histogram(
    "latencia_histogram_seconds",
    "Histograma de latencias end-to-end (segundos)",
    buckets=[0.01, 0.05, 0.1, 0.25, 0.5, 1, 2, 5, 10, 20, 30, 60],
    labelnames=["desde_nodo", "hacia_nodo"],
)

# Contadores de tráfico
MSGS_ENVIADOS = Counter("mensajes_enviados_total", "Mensajes enviados", ["desde_nodo", "hacia_nodo"])
MSGS_RECIBIDOS = Counter("mensajes_recibidos_total", "Mensajes recibidos en destino", ["nodo"])
MSGS_FALLIDOS = Counter("mensajes_fallidos_total", "Mensajes fallidos de envío", ["desde_nodo", "hacia_nodo"])

# Gauge de “en vuelo” por conexión
MSGS_EN_CONEXION = Gauge("mensajes_en_conexion", "Mensajes en vuelo por conexión", ["source", "target"])

# =========================
# Utilidades
# =========================
def now_iso():
    return datetime.utcnow().isoformat() + "Z"


def log(event, level="INFO", **data):
    payload = {
        "timestamp": now_iso(),
        "level": level,
        "node": SELF_NAME,
        "pod": HOSTNAME,
        "event": event,
        "data": data,
    }
    print(json.dumps(payload), flush=True)


def parse_json_msg(raw: bytes):
    try:
        return json.loads(raw.decode("utf-8"))
    except Exception:
        return None


def serialize_msg(obj: dict) -> bytes:
    return (json.dumps(obj) + "\n").encode("utf-8")


def color_from_ms(lat_ms: float) -> str:
    if lat_ms < COLOR_YELLOW_MS:
        return "green"
    if lat_ms < COLOR_RED_MS:
        return "yellow"
    return "red"


def connect_and_send(host: str, port: int, payload: dict, timeout: float):
    """Envía JSON y espera un JSON (ACK). Devuelve (ok, dt_seconds, resp_obj|None)."""
    t0 = time.time()
    with closing(socket.socket(socket.AF_INET, socket.SOCK_STREAM)) as s:
        s.settimeout(timeout)
        s.connect((host, port))
        s.sendall(serialize_msg(payload))
        chunks = []
        while True:
            ch = s.recv(4096)
            if not ch:
                break
            chunks.append(ch)
            if b"\n" in ch:
                break
    dt = time.time() - t0
    data = parse_json_msg(b"".join(chunks).split(b"\n")[0]) if chunks else None
    return (bool(data), dt, data)

# =========================
# Lógica de ruteo
# =========================
def next_hop_for(destination: str, last_hop: str | None) -> str | None:
    # Ruta fija
    if destination in ROUTES:
        return ROUTES[destination]
    # Directo si el destino es peer
    if destination in PEERS:
        return destination
    # Peer aleatorio distinto del último salto
    candidates = [p for p in PEERS if p != last_hop]
    if not candidates:
        return None
    return random.choice(candidates)

# =========================
# Servidor TCP
# =========================
def handle_client(conn, addr):
    conn.settimeout(SOCKET_TIMEOUT)
    try:
        raw = b""
        while True:
            chunk = conn.recv(4096)
            if not chunk:
                break
            raw += chunk
            if b"\n" in chunk:
                break
        msg = parse_json_msg(raw.split(b"\n")[0]) if raw else None
        if not msg:
            return

        mid = msg.get("id")
        dst = msg.get("destination")
        route = msg.get("route", [])
        last_hop = msg.get("last_hop")

        # Entrega local
        if dst == SELF_NAME:
            MSGS_RECIBIDOS.labels(nodo=SELF_NAME).inc()
            resp = {"ok": True, "id": mid, "received_by": SELF_NAME, "ts": now_iso()}
            conn.sendall(serialize_msg(resp))
            log("msg_delivered", id=mid, destination=dst, route=route)
            return

        # Reenvío
        nh = next_hop_for(dst, last_hop=last_hop)
        if not nh:
            conn.sendall(serialize_msg({"ok": False, "id": mid, "error": "no_next_hop", "ts": now_iso()}))
            log("forward_failed", id=mid, to=dst)
            return

        fwd = dict(msg)
        fwd["last_hop"] = SELF_NAME
        fwd["route"] = route + [SELF_NAME]

        MSGS_EN_CONEXION.labels(source=SELF_NAME, target=nh).inc()
        try:
            ok, dt, r = connect_and_send(nh, PORT, fwd, SOCKET_TIMEOUT)
            LATENCIA_HISTOGRAM.labels(desde_nodo=SELF_NAME, hacia_nodo=nh).observe(dt)
            lat_ms = dt * 1000.0
            c = color_from_ms(lat_ms)
            LATENCIA_CONEXION_MS.labels(desde_nodo=SELF_NAME, hacia_nodo=nh, color=c).set(lat_ms)
            CONEXIONES_ACTIVAS.labels(desde_nodo=SELF_NAME, hacia_nodo=nh).set(1 if ok else 0)

            if ok and r and r.get("ok"):
                conn.sendall(serialize_msg({"ok": True, "id": mid, "relayed_by": SELF_NAME, "ts": now_iso()}))
                log("msg_relay_ok", id=mid, next_hop=nh, latency_ms=int(lat_ms))
            else:
                conn.sendall(serialize_msg({"ok": False, "id": mid, "error": "relay_failed", "ts": now_iso()}))
                log("msg_relay_failed", id=mid, next_hop=nh)
        finally:
            MSGS_EN_CONEXION.labels(source=SELF_NAME, target=nh).dec()

    except socket.timeout:
        with contextlib.suppress(Exception):
            conn.sendall(serialize_msg({"ok": False, "error": "timeout", "ts": now_iso()}))
    except Exception as e:
        with contextlib.suppress(Exception):
            conn.sendall(serialize_msg({"ok": False, "error": str(e), "ts": now_iso()}))
    finally:
        with contextlib.suppress(Exception):
            conn.close()

def server_loop():
    with closing(socket.socket(socket.AF_INET, socket.SOCK_STREAM)) as s:
        s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        s.bind(("", PORT))
        s.listen(128)
        log("server_started", port=PORT)
        while True:
            conn, addr = s.accept()
            threading.Thread(target=handle_client, args=(conn, addr), daemon=True).start()

# =========================
# Cliente emisor periódico
# =========================
def sender_loop():
    while True:
        try:
            if DESTINOS:
                dst = random.choice(DESTINOS)
                msg_id = str(uuid.uuid4())
                payload = {
                    "id": msg_id,
                    "type": "data",
                    "source": SELF_NAME,
                    "destination": dst,
                    "payload": f"Hola desde {SELF_NAME} a {dst}",
                    "last_hop": SELF_NAME,
                    "route": [SELF_NAME],
                    "status": "IN_PROGRESS",
                }

                nh = next_hop_for(dst, last_hop=None)
                if nh:
                    MSGS_EN_CONEXION.labels(source=SELF_NAME, target=nh).inc()
                    try:
                        ok, dt, _ = connect_and_send(nh, PORT, payload, SOCKET_TIMEOUT)
                        LATENCIA_HISTOGRAM.labels(desde_nodo=SELF_NAME, hacia_nodo=nh).observe(dt)
                        lat_ms = dt * 1000.0
                        c = color_from_ms(lat_ms)
                        LATENCIA_CONEXION_MS.labels(desde_nodo=SELF_NAME, hacia_nodo=nh, color=c).set(lat_ms)
                        CONEXIONES_ACTIVAS.labels(desde_nodo=SELF_NAME, hacia_nodo=nh).set(1 if ok else 0)

                        if ok:
                            MSGS_ENVIADOS.labels(desde_nodo=SELF_NAME, hacia_nodo=nh).inc()
                            log("msg_send", id=msg_id, destination=dst, next_hop=nh, route=[SELF_NAME], latency_ms=int(lat_ms))
                        else:
                            MSGS_FALLIDOS.labels(desde_nodo=SELF_NAME, hacia_nodo=nh).inc()
                            log("msg_send_failed", id=msg_id, destination=dst, next_hop=nh)
                    finally:
                        MSGS_EN_CONEXION.labels(source=SELF_NAME, target=nh).dec()
                else:
                    log("no_next_hop_for_destination", destination=dst)
        except Exception as e:
            log("sender_error", level="ERROR", error=str(e))
        time.sleep(SEND_INTERVAL)

# =========================
# Healthcheck de peers (latencia de conexión)
# =========================
def healthcheck_loop():
    while True:
        ok = 0
        total = 0
        for peer in PEERS:
            total += 1
            try:
                t0 = time.time()
                with closing(socket.socket(socket.AF_INET, socket.SOCK_STREAM)) as s:
                    s.settimeout(SOCKET_TIMEOUT)
                    s.connect((peer, PORT))
                dt = time.time() - t0
                lat_ms = dt * 1000.0
                c = color_from_ms(lat_ms)
                LATENCIA_CONEXION_MS.labels(desde_nodo=SELF_NAME, hacia_nodo=peer, color=c).set(lat_ms)
                CONEXIONES_ACTIVAS.labels(desde_nodo=SELF_NAME, hacia_nodo=peer).set(1)
                ok += 1
            except Exception:
                LATENCIA_CONEXION_MS.labels(desde_nodo=SELF_NAME, hacia_nodo=peer, color="red").set(9999.0)
                CONEXIONES_ACTIVAS.labels(desde_nodo=SELF_NAME, hacia_nodo=peer).set(0)

        # NUEVO: % salud = peers OK / peers totales
        if total > 0:
            ESTADO_SALUD_NODO.labels(nodo=SELF_NAME).set((ok / total) * 100.0)

        time.sleep(5)

# =========================
# Main
# =========================
def main():
    ESTADO_NODO.labels(nodo=SELF_NAME).set(1)
    # NUEVO: inicialización optimista de salud
    ESTADO_SALUD_NODO.labels(nodo=SELF_NAME).set(100)

    log("node_boot", port=PORT, metrics_port=METRICS_PORT, peers=PEERS, destinos=DESTINOS, routes=ROUTES)

    start_http_server(METRICS_PORT)

    threading.Thread(target=server_loop, daemon=True).start()
    threading.Thread(target=sender_loop, daemon=True).start()
    threading.Thread(target=healthcheck_loop, daemon=True).start()

    while True:
        time.sleep(60)

if __name__ == "__main__":
    main()
