#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Network Node Module
-------------------
Este módulo implementa un nodo TCP capaz de enviar, recibir y reenviar mensajes JSON
a otros nodos dentro de una topología definida mediante variables de entorno.

Características:
- Comunicación P2P mediante TCP.
- Reenvío de mensajes usando tabla de enrutamiento dinámica.
- Logs en formato JSON estructurado.
- Reintentos y control de errores.
"""

import os
import json
import time
import socket
import threading
from dataclasses import dataclass
from datetime import datetime
from typing import Dict, List, Optional


# ==================== CONFIGURACIÓN GLOBAL ====================

HOST = "0.0.0.0"
PORT = int(os.getenv("PORT", "5000"))
SOCKET_TIMEOUT = 1.0  # segundos
MESSAGE_INTERVAL = 5  # intervalo entre envíos de mensajes

# Variables de entorno: PEERS, DESTINOS, ROUTES
# Ejemplos:
#   PEERS="nodoA:5001,nodoB:5002"
#   DESTINOS="nodoB,nodoC"
#   ROUTES="nodoC:nodoB:5002"

PEERS_ENV = os.getenv("PEERS", "")
DESTINOS_ENV = os.getenv("DESTINOS", "")
ROUTES_ENV = os.getenv("ROUTES", "")


# ==================== MODELOS DE DATOS ====================

@dataclass
class Peer:
    """Representa un nodo vecino conocido."""
    name: str
    port: int


@dataclass
class Route:
    """Representa una entrada de la tabla de enrutamiento."""
    destination: str
    next_hop: Peer


# ==================== UTILIDADES ====================

def parse_peers(env_str: str) -> List[Peer]:
    """Convierte la variable PEERS en una lista de Peer."""
    peers = []
    for entry in env_str.split(","):
        if ":" in entry:
            name, port = entry.split(":")
            peers.append(Peer(name=name.strip(), port=int(port)))
    return peers


def parse_routes(env_str: str) -> Dict[str, Route]:
    """Convierte la variable ROUTES en un diccionario de rutas."""
    routes = {}
    for entry in env_str.split(","):
        if ":" in entry:
            dest, next_name, next_port = entry.split(":")
            routes[dest.strip()] = Route(
                destination=dest.strip(),
                next_hop=Peer(name=next_name.strip(), port=int(next_port))
            )
    return routes


def parse_destinations(env_str: str) -> List[str]:
    """Convierte la variable DESTINOS en una lista de strings."""
    return [d.strip() for d in env_str.split(",") if d.strip()]


# ==================== LOGGING ESTRUCTURADO ====================

def log_json(level: str, event: str, message: str, msg_obj: Optional[dict] = None, extra: Optional[dict] = None):
    """Imprime logs estructurados en formato JSON para fácil ingesta por ELK, Datadog, etc."""
    log_entry = {
        "timestamp": datetime.utcnow().isoformat() + "Z",
        "level": level,
        "node": socket.gethostname(),
        "event": event,
        "message": message,
    }

    if msg_obj:
        log_entry["data"] = msg_obj
    if extra:
        log_entry["extra"] = extra

    print(json.dumps(log_entry, ensure_ascii=False), flush=True)


# ==================== FUNCIONALIDAD DE RED ====================

class Node:
    """Nodo TCP que puede enviar y reenviar mensajes entre pares."""

    def __init__(self, host: str, port: int, peers: List[Peer], routes: Dict[str, Route], destinations: List[str]):
        self.host = host
        self.port = port
        self.peers = peers
        self.routes = routes
        self.destinations = destinations
        self.hostname = socket.gethostname()

    # ----------- SERVIDOR -----------

    def start_server(self):
        """Inicia el servidor TCP que escucha conexiones entrantes."""
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as server_socket:
            server_socket.bind((self.host, self.port))
            server_socket.listen()
            log_json("INFO", "server_start", f"Servidor escuchando en {self.host}:{self.port}")

            while True:
                conn, _ = server_socket.accept()
                threading.Thread(target=self._handle_connection, args=(conn,), daemon=True).start()

    def _handle_connection(self, conn: socket.socket):
        """Procesa cada conexión TCP entrante."""
        with conn:
            try:
                data = conn.recv(4096).decode()
                if not data:
                    return

                msg = json.loads(data)
                destination = msg.get("destination")
                payload = msg.get("payload")
                last_hop = msg.get("last_hop")

                if destination == self.hostname:
                    log_json("INFO", "message_received", f"Mensaje recibido de {last_hop}: {payload}", msg)
                else:
                    log_json("INFO", "message_forward", f"Reenviando mensaje hacia {destination}", msg)
                    self.forward_message(msg, exclude_host=last_hop)

            except json.JSONDecodeError:
                log_json("ERROR", "invalid_json", "El mensaje recibido no es un JSON válido")
            except Exception as e:
                log_json("ERROR", "message_processing_error", f"Error procesando mensaje: {e}")

    # ----------- CLIENTE -----------

    def start_client(self):
        """Inicia el proceso que genera tráfico hacia los destinos configurados."""
        while True:
            if not self.destinations:
                time.sleep(1)
                continue

            for dest in self.destinations:
                message = {
                    "type": "data",
                    "source": self.hostname,
                    "destination": dest,
                    "payload": f"Hola desde {self.hostname} a {dest}",
                    "last_hop": self.hostname,
                }
                log_json("INFO", "message_send", f"Enviando mensaje a {dest}", message)
                self.forward_message(message)

            time.sleep(MESSAGE_INTERVAL)

    # ----------- REENVÍO DE MENSAJES -----------

    def forward_message(self, msg: dict, exclude_host: Optional[str] = None):
        """Intenta enviar el mensaje hacia su destino directo o según la tabla de rutas."""
        dest = msg["destination"]
        msg["last_hop"] = self.hostname

        # 1️⃣ Intentar envío directo
        for peer in self.peers:
            if dest == peer.name:
                if self._send_to_peer(peer, msg, "direct_send"):
                    return

        # 2️⃣ Intentar vía tabla de rutas
        if dest in self.routes:
            next_hop = self.routes[dest].next_hop
            if next_hop.name != exclude_host and self._send_to_peer(next_hop, msg, "route_forward"):
                return

        # 3️⃣ Intentar reenviar por otros vecinos (fallback)
        self._handle_reroute(msg, exclude_host, dest)

    def _send_to_peer(self, peer: Peer, msg: dict, event: str) -> bool:
        """Intenta enviar un mensaje a un vecino."""
        try:
            with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
                sock.settimeout(SOCKET_TIMEOUT)
                sock.connect((peer.name, peer.port))
                sock.sendall(json.dumps(msg).encode())

            log_json("INFO", event, f"Mensaje enviado a {peer.name}:{peer.port}", msg)
            return True
        except Exception as e:
            log_json("WARNING", "send_failed", f"Fallo al enviar a {peer.name}:{peer.port} - {e}")
            return False

    def _handle_reroute(self, msg: dict, exclude_host: Optional[str], dest: str):
        """Intentar reenvío por vecinos alternativos si la ruta falla."""
        for peer in self.peers:
            if peer.name == exclude_host:
                continue

            if self._send_to_peer(peer, msg, "reroute_success"):
                # Actualizar la tabla de enrutamiento dinámica
                self.routes[dest] = Route(destination=dest, next_hop=peer)
                log_json("INFO", "routing_update", f"Ruta hacia {dest} actualizada vía {peer.name}")
                return

        log_json("WARNING", "no_route_available", f"No fue posible reenviar mensaje hacia {dest}")


# ==================== EJECUCIÓN PRINCIPAL ====================

def main():
    peers = parse_peers(PEERS_ENV)
    routes = parse_routes(ROUTES_ENV)
    destinations = parse_destinations(DESTINOS_ENV)

    node = Node(host=HOST, port=PORT, peers=peers, routes=routes, destinations=destinations)

    threading.Thread(target=node.start_server, daemon=True).start()
    threading.Thread(target=node.start_client, daemon=True).start()

    # Mantener el hilo principal activo
    while True:
        time.sleep(1)


if __name__ == "__main__":
    main()
