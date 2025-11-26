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
LOG_FILE = "/var/log/app.log"

def write_log(line: str):
    with open(LOG_FILE, "a", encoding="utf-8") as f:
        f.write(line + "\n")

HOST = "0.0.0.0"
PORT = int(os.getenv("PORT", "5000"))
SOCKET_TIMEOUT = 60.0
MESSAGE_INTERVAL = 5
SELF_NAME = os.getenv("SELF_NAME","")
PEERS_ENV = os.getenv("PEERS", "")
DESTINOS_ENV = os.getenv("DESTINOS", "")
ROUTES_ENV = os.getenv("ROUTES", "")
PAYLOAD_SIZE = 3000 


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
    entry = {
        "timestamp": datetime.now(UTC).isoformat(),
        "level": level,
        "event": event,
        "node": SELF_NAME,
        "message": message,
    }
    if msg_obj:
        entry["data"] = msg_obj
    if extra:
        entry["extra"] = extra

    line = json.dumps(entry, ensure_ascii=False)
    print(line, flush=True)
    write_log(line)



# ==================== NODO ====================

class Node:
    def __init__(self, host: str, port: int, peers: List[Peer], routes: Dict[str, Route], destinations: List[str]):
        self.host = host
        self.port = port
        self.peers = peers
        self.routes = routes
        self.destinations = destinations
        self.hostname = SELF_NAME

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
                    log_json("INFO", "message_delivered", f"Message delivered to {self.hostname} from {msg.get('source')}",
                            {
                                "id": msg["id"],
                                "payload": msg["payload"]["text"],   # <-- SOLO
                                "route": msg["route"]
                            })
                else:
                    log_json("INFO", "message_forwarded", f"Message forwarded from {self.hostname} to {destination}",
                             {
                                "id": msg["id"],
                                "payload": msg["payload"]["text"],   # <-- SOLO
                                "route": msg["route"]
                            })
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
                msg = {
                    "id": str(uuid.uuid4()),
                    "type": "data",
                    "source": self.hostname,
                    "destination": dest,
                    "payload": {
                        "text": f"Hola desde {self.hostname} a {dest}",
                        "blob": "B" * 3000 
                    },
                    "status": "IN_PROGRESS",
                    "route": [self.hostname]
                }

                log_json("MSG", "message_sent",
                        f"Message sent from {self.hostname} to {dest}",
                        msg)

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

            # --- medir tamaño del mensaje enviado ---
            raw = json.dumps(msg).encode("utf-8")
            size = len(raw)

            with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
                sock.settimeout(SOCKET_TIMEOUT)
                sock.connect((peer.name, peer.port))
                sock.sendall(raw)

            # --- LOG REAL DEL EDGE (ESTE ES EL IMPORTANTE) ---
            log_json(
                "INFO",
                "edge",
                f"Edge {self.hostname} → {peer.name}",
                {
                    "src": self.hostname,
                    "dst": peer.name,
                    "bytes": size
                }
            )

            # Log clásico para debug
            log_json("INFO", event, log_message, msg_to_send)

            return True

        except Exception as e:
            log_json(
                "WARNING",
                "send_failed",
                f"Unable to send from {self.hostname} to {peer.name}:{peer.port}",
                msg_to_send
            )
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

    # ----------- AUTO-HEALING (INTELIGENTE) -----------

    def heal_routes_loop(self):
        while True:
            time.sleep(30)
            try:
                original_routes = parse_routes(ROUTES_ENV)
                for dest, original_route in original_routes.items():
                    current_route = self.routes.get(dest)

                    if current_route and current_route.next_hop.name != original_route.next_hop.name:
                        target_peer = original_route.next_hop
                        
                        # USAR LOG_JSON EN LUGAR DE PRINT
                        log_json("DEBUG", "healing_check", f" Probando ruta original hacia {dest} vía {target_peer.name}...")

                        if self._check_connectivity(target_peer):
                            log_json("INFO", "route_healed", f"{target_peer.name} ha revivido. Restaurando ruta.")
                            self.routes[dest] = original_route
            
            except Exception as e:
                log_json("ERROR", "healing_error", f"Error en auto-healing: {e}")

    def _check_connectivity(self, peer: Peer) -> bool:
        """Intenta abrir un socket al peer. Si conecta, devuelve True."""
        try:
            with socket.create_connection((peer.name, peer.port), timeout=2):
                return True
        except OSError:
            return False


# ==================== MAIN ====================

def main():
    peers = parse_peers(PEERS_ENV)
    routes = parse_routes(ROUTES_ENV)
    destinations = parse_destinations(DESTINOS_ENV)
    node = Node(HOST, PORT, peers, routes, destinations)
    
    # Iniciar hilos del servidor y cliente
    threading.Thread(target=node.start_server, daemon=True).start()
    threading.Thread(target=node.start_client, daemon=True).start()
    
    # Iniciar hilo de auto-reparación de rutas
    threading.Thread(target=node.heal_routes_loop, daemon=True).start()

    while True:
        time.sleep(1)


if __name__ == "__main__":
    main()
