from flask import Flask, Response
import requests
import os

app = Flask(__name__)

PROM_URL = os.getenv("PROM_URL", "http://prometheus-operated.monitoring.svc:9090")
NAMESPACE = os.getenv("NAMESPACE", "nodes")
TRAFFIC_WINDOW = os.getenv("TRAFFIC_WINDOW", "30s")

EDGE_LOW_THRESHOLD = float(os.getenv("EDGE_LOW_THRESHOLD", "1"))
EDGE_MED_THRESHOLD = float(os.getenv("EDGE_MED_THRESHOLD", "100"))

# Lista de nodos lógicos que queremos mostrar
NODES = [n.strip() for n in os.getenv("NODES", "").split(",") if n.strip()]

# Diccionario de peers por nodo (edges declarados)
PEERS = {}
for node in NODES:
    env_var = os.getenv(f"{node.upper()}_PEERS", "")
    if env_var:
        PEERS[node] = [p.strip() for p in env_var.split(",") if p.strip()]
    else:
        PEERS[node] = []


def prom_query(query: str):
    try:
        resp = requests.get(
            f"{PROM_URL}/api/v1/query",
            params={"query": query},
            timeout=5,
        )
        data = resp.json()
        return data.get("data", {}).get("result", [])
    except Exception as e:
        print("Error querying Prometheus:", e, flush=True)
        return []


def get_ready_container_status():
    """Devuelve {nombre_pod: ready} (0/1)."""
    result = prom_query(
    f'kube_pod_container_status_ready{{namespace="{NAMESPACE}",container!~"sidecar.*"}}'
)


    status = {}
    for r in result:
        metric = r.get("metric", {})
        container = metric.get("pod") or metric.get("container")
        if not container:
            continue
        value = int(float(r["value"][1]))
        status[container] = value

    # Mapeamos pod → nodo lógico (por ahora asumimos que pod name empieza por nodeX)
    node_status = {}
    for pod_name, val in status.items():
        for n in NODES:
            if pod_name.startswith(n):
                node_status[n] = val

    return node_status


def get_edge_traffic_bps():
    """Devuelve dict: (src, dst) → bps."""
    query = f'rate(app_edge_bytes_total[{TRAFFIC_WINDOW}])'
    result = prom_query(query)

    edge_traffic = {}

    for r in result:
        metric = r.get("metric", {})
        src = metric.get("src")
        dst = metric.get("dst")

        if not src or not dst:
            continue

        try:
            value = float(r["value"][1])
        except:
            value = 0.0

        edge_traffic[(src, dst)] = value

    return edge_traffic


@app.route("/metrics")
def metrics():
    # Estado de nodos (0 o 1)
    ready = get_ready_container_status()

    # Trafico unidireccional
    traf = get_edge_traffic_bps()

    out = []

    # ================================
    # 🎯 NODOS
    # ================================
    for node in NODES:
        status = ready.get(node, 0)
        color = "green" if status == 1 else "red"

        out.append(
            f'nodegraph_node_info{{id="{node}",title="{node}",subtitle="running",'
            f'mainstat="{status}",color="{color}"}} 1'
        )

   
    seen = set()

    for src in NODES:
        for dst in PEERS[src]:
            if dst not in NODES:
                continue

            key = tuple(sorted([src, dst]))
            if key in seen:
                continue
            seen.add(key)

            # bps(src→dst)
            b1 = traf.get((src, dst), 0.0)

            # bps(dst→src)
            b2 = traf.get((dst, src), 0.0)

            total = b1 + b2

            # Color según tráfico total
            if total == 0:
                color= "gray"
            elif total < EDGE_LOW_THRESHOLD:
                color = "green"
            elif total < EDGE_MED_THRESHOLD:
                color = "yellow"
                pass
            else:
                color = "red"

            out.append(
                f'nodegraph_edge_info{{source="{src}",target="{dst}",id="{src}_to_{dst}",'
                f'mainstat="{total:.2f}",subtitle="B/s",color="{color}"}} 1'
            )

    return Response("\n".join(out) + "\n", mimetype="text/plain")


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=9101)
