#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Network Node Module — versión mejorada con logs JSON
----------------------------------------------------
- Cada nodo imprime logs estructurados en formato JSON.
- Incluye origen, destino, ruta seguida, fallos de reenvío y rutas actualizadas.
- Compatible con Docker logs o Docker Desktop.
"""

import os
import json
import time
import socket
import uuid
import threading
from datetime import datetime
from dataclasses import dataclass
from typing import Dict, List, Optional


# ==================== CONFIGURACIÓN ====================

HOST = "0.0.0.0"
PORT = int(os.getenv("PORT", "5000"))
SOCKET_TIMEOUT = 1.0
MESSAGE_INTERVAL = 5

PEERS_ENV = os.getenv("PEERS", "")
DESTINOS_ENV = os.getenv("DESTINOS", "")
ROUTES_ENV = os.getenv("ROUTES", "")


# ==================== MODELOS ====================

@dataclass
class Peer:
    name: str
    port: int


@dataclass
class Route:
    destination: str
    next_hop: Peer


# ==================== PARSERS ====================

def parse_peers(env_str: str) -> List[Peer]:
    peers = []
    for entry in env_str.split(","):
        if ":" in entry:
            name, port = entry.split(":")
            peers.append(Peer(name=name.strip(), port=int(port)))
    return peers


def parse_routes(env_str: str) -> Dict[str, Route]:
    routes = {}
    for entry in env_str.split(","):
        if ":" in entry:
            dest, next_name, next_port = entry.split(":")
            routes[dest.strip()] = Route(destination=dest.strip(),
                                         next_hop=Peer(name=next_name.strip(), port=int(next_port)))
    return routes


def parse_destinations(env_str: str) -> List[str]:
    return [d.strip() for d in env_str.split(",") if d.strip()]


# ==================== LOG JSON ====================

def log_json(level: str, event: str, message: str, msg_obj: Optional[dict] = None, extra: Optional[dict] = None):
    """Imprime logs en formato JSON estructurado."""
    entry = {
        "timestamp": datetime.utcnow().isoformat() + "Z",
        "level": level,
        "node": socket.gethostname(),
        "event": event,
        "message": message,
    }
    if msg_obj:
        entry["message_data"] = msg_obj
    if extra:
        entry["extra"] = extra
    print(json.dumps(entry, ensure_ascii=False), flush=True)


# ==================== NODO ====================

class Node:
    def __init__(self, host: str, port: int, peers: List[Peer], routes: Dict[str, Route], destinations: List[str]):
        self.host = host
        self.port = port
        self.peers = peers
        self.routes = routes
        self.destinations = destinations
        self.hostname = socket.gethostname()

    # ----------- SERVIDOR -----------

    def start_server(self):
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            s.bind((self.host, self.port))
            s.listen()
            log_json("INFO", "server_start", f"Servidor escuchando en {self.host}:{self.port}")
            while True:
                conn, _ = s.accept()
                threading.Thread(target=self._handle_connection, args=(conn,), daemon=True).start()

    def _handle_connection(self, conn: socket.socket):
        with conn:
            try:
                data = conn.recv(4096).decode()
                if not data:
                    return
                msg = json.loads(data)

                destination = msg["destination"]
                route = msg.get("route", [])
                route.append(self.hostname)
                msg["route"] = route

                if destination == self.hostname:
                    msg["status"] = "DELIVERED"
                    log_json("INFO", "message_received", f"Mensaje entregado a {self.hostname}", msg)
                else:
                    log_json("INFO", "message_forward", f"Reenviando mensaje hacia {destination}", msg)
                    self.forward_message(msg, exclude_host=msg.get("last_hop"))

            except Exception as e:
                log_json("ERROR", "message_processing_error", f"Error procesando mensaje: {e}")

    # ----------- CLIENTE -----------

    def start_client(self):
        while True:
            if not self.destinations:
                time.sleep(1)
                continue

            for dest in self.destinations:
                msg = {
                    "id": str(uuid.uuid4()),
                    "type": "data",
                    "source": self.hostname,
                    "destination": dest,
                    "payload": f"Hola desde {self.hostname} a {dest}",
                    "last_hop": self.hostname,
                    "route": [self.hostname],
                    "status": "IN_PROGRESS"
                }
                log_json("INFO", "message_send", f"Enviando mensaje a {dest}", msg)
                self.forward_message(msg)
            time.sleep(MESSAGE_INTERVAL)

    # ----------- REENVÍO -----------

    def forward_message(self, msg: dict, exclude_host: Optional[str] = None):
        dest = msg["destination"]
        msg["last_hop"] = self.hostname

        # 1️⃣ Intentar directo
        for peer in self.peers:
            if dest == peer.name:
                if self._send_to_peer(peer, msg, "direct_send"):
                    return

        # 2️⃣ Por tabla
        if dest in self.routes:
            next_hop = self.routes[dest].next_hop
            if next_hop.name != exclude_host and self._send_to_peer(next_hop, msg, "route_forward"):
                return

        # 3️⃣ Alternativa
        self._handle_reroute(msg, exclude_host, dest)

    def _send_to_peer(self, peer: Peer, msg: dict, event: str) -> bool:
        try:
            with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
                sock.settimeout(SOCKET_TIMEOUT)
                sock.connect((peer.name, peer.port))
                sock.sendall(json.dumps(msg).encode())
            log_json("INFO", event, f"Mensaje enviado a {peer.name}:{peer.port}", msg)
            return True
        except Exception as e:
            log_json("WARNING", "send_failed", f"No se pudo enviar a {peer.name}:{peer.port} - {e}", msg)
            return False

    def _handle_reroute(self, msg: dict, exclude_host: Optional[str], dest: str):
        for peer in self.peers:
            if peer.name == exclude_host:
                continue
            if self._send_to_peer(peer, msg, "reroute_success"):
                self.routes[dest] = Route(destination=dest, next_hop=peer)
                log_json("INFO", "routing_update", f"Ruta hacia {dest} actualizada vía {peer.name}", msg)
                return
        msg["status"] = "FAILED"
        log_json("ERROR", "no_route_available", f"No fue posible reenviar mensaje hacia {dest}", msg)


# ==================== MAIN ====================

def main():
    peers = parse_peers(PEERS_ENV)
    routes = parse_routes(ROUTES_ENV)
    destinations = parse_destinations(DESTINOS_ENV)
    node = Node(HOST, PORT, peers, routes, destinations)
    threading.Thread(target=node.start_server, daemon=True).start()
    threading.Thread(target=node.start_client, daemon=True).start()
    while True:
        time.sleep(1)


if __name__ == "__main__":
    main()

