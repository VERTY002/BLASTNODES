import os
import json
import time
import socket
import uuid
import threading
from datetime import datetime, UTC
from dataclasses import dataclass
from typing import Dict, List, Optional


# ==================== CONFIGURACIÓN ====================

HOST = "0.0.0.0"
PORT = int(os.getenv("PORT", "5000"))
SOCKET_TIMEOUT = 60.0

MESSAGE_INTERVAL = 0.05
PAYLOAD_SIZE = 1024*50

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
        "timestamp": datetime.now(UTC).isoformat(),
        "level": level,
        "event": event,
        "node": socket.gethostname(),
        "message": message,
    }
    if msg_obj:
        entry["data"] = msg_obj
    if extra:
        entry["extra"] = extra
    print(json.dumps(entry, ensure_ascii=False), flush=True)




"""def burn_cpu():
    
    Simula una tarea de CPU "pesada" (ej. desencriptar, procesar).
    Esto es para que la app tenga una carga de CPU base medible.
    # Iteramos 2,000,000 de veces. 

    for _ in range(500000):
        _ = 1 + 1 # Una operación tonta para gastar CPU
"""

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
            log_json("INFO", "server_started", f"Server started at {self.host}:{self.port}")
            while True:
                conn, _ = s.accept()
                threading.Thread(target=self._handle_connection, args=(conn,), daemon=True).start()

    def _handle_connection(self, conn: socket.socket):
        with conn:
            try:
                data = conn.recv(1024*1024).decode()
                if not data:
                    return
                msg = json.loads(data)

               # burn_cpu()

                destination = msg["destination"]
                route = msg.get("route", [])
                route.append(self.hostname)
                msg["route"] = route

                if destination == self.hostname:
                    msg["status"] = "DELIVERED"
                    log_json("INFO", "message_delivered", f"Message delivered to {self.hostname} from {msg.get('source')}", msg)
                else:
                    log_json("INFO", "message_forwarded", f"Message forwarded from {self.hostname} to {destination}", msg)
                    self.forward_message(msg, exclude_host=msg.get("last_hop"))

            except Exception as e:
                log_json("ERROR", "message_processing_error", f"Unable to process received message: {e}")

    # ----------- CLIENTE -----------

    def start_client(self):
        log_json("INFO", "client_started", f"Client started at {self.host}:{self.port}")
        while True:
            if not self.destinations:
                time.sleep(1)
                continue

            for dest in self.destinations:
                heavy_payload = 'x' * PAYLOAD_SIZE
                msg = {
                    "id": str(uuid.uuid4()),
                    "type": "data",
                    "source": self.hostname,
                    "destination": dest,
                    "payload": heavy_payload,
                    "status": "IN_PROGRESS",
                    "route": [self.hostname]
                }
                log_json("MSG", "message_sent", f"Message sent from {self.hostname} to {dest}", msg)
                self.forward_message(msg)
            time.sleep(MESSAGE_INTERVAL)

    # ----------- REENVÍO -----------

    def forward_message(self, msg: dict, exclude_host: Optional[str] = None):
        dest = msg["destination"]
        msg["last_hop"] = self.hostname

        msg_to_send = msg.copy()
        msg_to_send.pop("last_hop", None)

        # 1️. Intentar directo
        for peer in self.peers:
            if dest == peer.name:
                if self._send_to_peer(peer, msg_to_send, "message_forwarded", f"Message forwarded from {self.hostname} to {dest}"):
                    return

        # 2️. Por tabla
        if dest in self.routes:
            next_hop = self.routes[dest].next_hop
            if next_hop.name != exclude_host and self._send_to_peer(next_hop, msg_to_send, "message_rerouted", f"Message rerouted via {next_hop.name}"):
                return

        # 3️. Alternativa
        self._handle_reroute(msg_to_send, exclude_host, dest, next_hop.name)

    def _send_to_peer(self, peer: Peer, msg: dict, event: str, log_message: str) -> bool:
        try:
            msg_to_send = msg.copy()
            msg_to_send.pop("last_hop", None)

            with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
                sock.settimeout(SOCKET_TIMEOUT)
                sock.connect((peer.name, peer.port))
                sock.sendall(json.dumps(msg).encode())
            log_json("INFO", event, log_message, msg_to_send)
            return True
        except Exception as e:
            log_json("WARNING", "send_failed", f"Unable to send the message from {self.hostname} to {peer.name}:{peer.port}", msg_to_send)
            return False

    def _handle_reroute(self, msg: dict, exclude_host: Optional[str], dest: str, prev_failed):
        msg_to_send = msg.copy()
        msg_to_send.pop("last_hop", None)

        for peer in self.peers:
            if peer.name == exclude_host:
                continue
            if peer.name == prev_failed:
                continue
            if self._send_to_peer(peer, msg, "route_updated", f"Route from {self.hostname} to {dest} updated via {peer.name}"):
                self.routes[dest] = Route(destination=dest, next_hop=peer)
                return
        msg["status"] = "FAILED"
        log_json("ERROR", "no_route_available", f"No route available from {self.hostname} to {dest}", msg_to_send)


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
