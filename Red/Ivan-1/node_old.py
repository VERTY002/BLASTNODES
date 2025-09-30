import socket
import threading
import time
import os

NODE_NAME = os.getenv("NODE_NAME", "Node")
NODE_PORT = int(os.getenv("NODE_PORT", 9000))
PEER_NODES = os.getenv("PEER_NODES", "")
DELAY = int(os.getenv("DELAY", 5))
NODE_IS_RELAY = os.getenv("NODE_IS_RELAY", "false").lower() == "true"

peer_connections = []

def handle_client(conn, addr):
    """ Maneja conexión entrante (desde peer o cliente relay) """
    print(f"[{NODE_NAME}] Connection from {addr}")
    try:
        while True:
            data = conn.recv(1024)
            if not data:
                break
            message = data.decode()
            print(f"[{NODE_NAME}] Received from {addr}: {message}")

            if NODE_IS_RELAY:
                # Relay: reenvía al servidor
                for peer in peer_connections:
                    try:
                        relay_msg = f"[RELAYED by {NODE_NAME}] {message}"
                        peer.sendall(relay_msg.encode())
                    except:
                        pass
            else:
                # Nodo normal: responde
                response = f"Reply from {NODE_NAME} to {addr[0]}:{addr[1]}"
                conn.sendall(response.encode())
    except Exception as e:
        print(f"[{NODE_NAME}] Error: {e}")
    finally:
        conn.close()

def listen_to_peer(conn):
    """ Escucha lo que envían los peers salientes """
    try:
        while True:
            data = conn.recv(1024)
            if not data:
                break
            print(f"[{NODE_NAME}] Received from peer: {data.decode()}")
    except Exception as e:
        print(f"[{NODE_NAME}] Error receiving from peer: {e}")
    finally:
        conn.close()

def start_server():
    server = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    server.bind(("0.0.0.0", NODE_PORT))
    server.listen()
    print(f"[{NODE_NAME}] Listening on port {NODE_PORT}...")

    while True:
        conn, addr = server.accept()
        threading.Thread(target=handle_client, args=(conn, addr), daemon=True).start()

def connect_to_peers():
    global peer_connections
    peers = PEER_NODES.split(",")
    while True:
        remaining_peers = []
        for peer in peers:
            if not peer:
                continue
            host, port = peer.split(":")
            try:
                s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
                s.connect((host, int(port)))
                peer_connections.append(s)
                print(f"[{NODE_NAME}] Connected to peer {host}:{port}")
                threading.Thread(target=listen_to_peer, args=(s,), daemon=True).start()
            except Exception as e:
                print(f"[{NODE_NAME}] Could not connect to {host}:{port} - {e}")
                remaining_peers.append(peer)
        if not remaining_peers:
            break
        time.sleep(5)
        peers = remaining_peers

def send_heartbeat():
    while True:
        for conn in peer_connections:
            try:
                msg = f"Ping from {NODE_NAME}"
                conn.sendall(msg.encode())
            except Exception as e:
                print(f"[{NODE_NAME}] Failed to send ping: {e}")
        time.sleep(DELAY)

if __name__ == "__main__":
    threading.Thread(target=start_server, daemon=True).start()
    time.sleep(2)
    connect_to_peers()
    send_heartbeat()
