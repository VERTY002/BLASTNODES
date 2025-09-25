import os
import yaml
import json
from pathlib import Path

# Define nodos y sus conexiones
TOPOLOGY = {
    "server": {
        "physical": ["client-1"],
        "logical": ["client-1", "client-2"]
    },
    "client-1": {
        "physical": ["client-2", "server"],
        "logical": ["server"]
    },
    "client-2": {
        "physical": ["client-1"],
        "logical": ["server"]
    },
    "client-3": {
        "physical": ["client-2"],
        "logical": ["server"]
    }
}

# Generar redes Docker únicas para cada conexión física
def generate_network_name(n1, n2):
    return f"net_{'_'.join(sorted([n1, n2]))}"

# Crear archivo de configuración lógica por nodo
def generate_node_config(node_name, logical_peers):
    config_dir = Path("configs")
    config_dir.mkdir(exist_ok=True)
    config = {
        "node": node_name,
        "logical_connections": logical_peers
    }
    with open(config_dir / f"{node_name}.json", "w") as f:
        json.dump(config, f, indent=2)

# Generar docker-compose.yml
def generate_docker_compose(topology):
    compose = {
        "services": {},
        "networks": {}
    }

    for node, connections in topology.items():
        service = {
            "build": "./node",  # Ruta al Dockerfile
            "container_name": node,
            "networks": [],
            "volumes": [f"./configs/{node}.json:/app/config.json"]
        }

        for peer in connections["physical"]:
            net_name = generate_network_name(node, peer)
            service["networks"].append(net_name)
            compose["networks"][net_name] = {"driver": "bridge"}

        compose["services"][node] = service

        # Config lógica
        generate_node_config(node, connections["logical"])

    # Guardar docker-compose
    with open("docker-compose.yml", "w") as f:
        yaml.dump(compose, f, sort_keys=False)

    print("✅ docker-compose.yml y archivos de configuración generados.")

if __name__ == "__main__":
    generate_docker_compose(TOPOLOGY)
