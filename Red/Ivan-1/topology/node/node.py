import json
import time
import sys

try:
    with open("config.json") as f:
        config = json.load(f)
except FileNotFoundError:
    print("ERROR: No se encuentra 'config.json'")
    sys.exit(1)
except json.JSONDecodeError:
    print("ERROR: 'config.json' contiene un JSON inválido")
    sys.exit(1)

node_name = config.get("node", "undefined")
logical_peers = config.get("logical_connections", [])

print(f"Nodo [{node_name}] iniciado.")
print(f"Conexiones lógicas: {logical_peers}")

try:
    while True:
        for peer in logical_peers:
            print(f"[{node_name}] → mensaje lógico a {peer}")
        time.sleep(5)
except KeyboardInterrupt:
    print(f"Nodo [{node_name}] detenido.")
