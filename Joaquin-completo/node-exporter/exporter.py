from flask import Flask, Response
import requests
import os

#Hecho de manera escalable como hablamos en clase, podrá monitorizar cualquier pod que decidamos añadir aunque no sea app.py
#Solo hayq definir el nombre del contenedor, y definir lista de nodos y conexiones como variables de entorno

app = Flask(__name__)

PROM_URL = os.getenv("PROM_URL", "http://prometheus-operated.monitoring.svc:9090")
NAMESPACE = os.getenv("NAMESPACE", "nodes")


NODES = [n.strip() for n in os.getenv("NODES", "").split(",") if n.strip()]


PEERS = {}
for node in NODES:
    env_var = os.getenv(f"{node.upper()}_PEERS", "")
    if env_var:
        PEERS[node] = [p.strip() for p in env_var.split(",") if p.strip()]
    else:
        PEERS[node] = []


def prom_query(query):
    try:
        resp = requests.get(f"{PROM_URL}/api/v1/query", params={"query": query}).json()
        return resp.get("data", {}).get("result", [])
    except Exception as e:
        print("Error querying Prometheus:", e)
        return []


def get_ready_container_status():
    result = prom_query(f'kube_pod_container_status_ready{{namespace="{NAMESPACE}"}}')
    return {r["metric"]["container"]: int(r["value"][1]) for r in result}


@app.route("/metrics")
def metrics():
    ready = get_ready_container_status()

    lines = []

    for node in NODES:
        status = ready.get(node, 0)
        color = "green" if status == 1 else "red"

        lines.append(
            f'nodegraph_node_info{{id="{node}",title="{node}",subtitle="status",mainstat="{status}",color="{color}"}} 1'
        )

   
    seen_edges = set()
    for src, peers in PEERS.items():
        for peer in peers:
            if peer not in NODES:
                continue

            edge = tuple(sorted([src, peer]))
            if edge in seen_edges:
                continue
            seen_edges.add(edge)

            lines.append(
                f'nodegraph_edge_info{{source="{src}",target="{peer}",id="{src}to{peer}"}} 1'
            )

    return Response("\n".join(lines) + "\n", mimetype="text/plain")


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=9101)
