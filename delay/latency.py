from flask import Flask, Response
import requests
import os

app = Flask(__name__)

# --- CONFIGURACIÓN ---
PROM_URL = os.getenv("PROM_URL", "http://prometheus-operated.monitoring.svc:9090")
NAMESPACE = os.getenv("NAMESPACE", "nodes")

# Ventanas de tiempo
TRAFFIC_WINDOW = os.getenv("TRAFFIC_WINDOW", "30s")
LATENCY_WINDOW = os.getenv("LATENCY_WINDOW", "1m")

# Umbrales de Tráfico (Bytes)
EDGE_LOW_THRESHOLD = float(os.getenv("EDGE_LOW_THRESHOLD", "1"))
EDGE_MED_THRESHOLD = float(os.getenv("EDGE_MED_THRESHOLD", "100"))

# --- UMBRALES DE LATENCIA ---
LATENCY_WARN = float(os.getenv("LATENCY_WARN", "1.0"))
LATENCY_CRIT = float(os.getenv("LATENCY_CRIT", "4.0"))

NODES = [n.strip() for n in os.getenv("NODES", "").split(",") if n.strip()]
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
    result = prom_query(
        f'kube_pod_container_status_ready{{namespace="{NAMESPACE}",container!~"sidecar.*"}}'
    )
    status = {}
    for r in result:
        metric = r.get("metric", {})
        container = metric.get("pod") or metric.get("container")
        if not container:
            continue
        try:
            value = int(float(r["value"][1]))
            status[container] = value
        except:
            continue

    node_status = {}
    for raw_name, val in status.items():
        for n in NODES:
            if raw_name.startswith(n):
                node_status[n] = val
    return node_status


def get_node_latency():
    query = f'histogram_quantile(0.9, rate(prober_probe_duration_seconds_bucket{{namespace="{NAMESPACE}"}}[{LATENCY_WINDOW}]))'
    result = prom_query(query)
    latency_map = {}

    for r in result:
        metric = r.get("metric", {})
        container_name = metric.get("container")
        if not container_name:
            continue
        try:
            val = float(r["value"][1])
            latency_map[container_name] = val
        except:
            continue

    final_latencies = {}
    for raw_name, val in latency_map.items():
        for n in NODES:
            if raw_name.startswith(n):
                final_latencies[n] = val
    return final_latencies


def get_edge_traffic_bps():
    query = f'rate(app_edge_bytes_total[{TRAFFIC_WINDOW}])'
    result = prom_query(query)
    edge_traffic = {}
    for r in result:
        metric = r.get("metric", {})
        src = metric.get("src")
        dst = metric.get("dst")
        if not src or not dst: continue
        try:
            value = float(r["value"][1])
        except:
            value = 0.0
        edge_traffic[(src, dst)] = value
    return edge_traffic


@app.route("/metrics")
def metrics():
    ready = get_ready_container_status()
    latencies = get_node_latency()
    traf = get_edge_traffic_bps()

    out = []

    # ================================
    # 🎯 NODOS
    # ================================
    for node in NODES:
        status = ready.get(node, 0)
        lat = latencies.get(node, 0.0)
        
        # CAMBIO 1: 3 decimales
        lat_str = f"{lat:.3f}" 

        # CAMBIO 2: Lógica de color (Crit -> Orange)
        if status == 0:
            color = "red"  # Nodo caído siempre rojo
        else:
            if lat > LATENCY_CRIT:   # > 4.0s
                color = "orange"     # <--- AHORA ES NARANJA
            elif lat > LATENCY_WARN: # > 1.0s
                color = "yellow"
            else:
                color = "green"

        out.append(
            f'nodegraph_node_info{{id="{node}",title="{node}",subtitle="running",'
            f'mainstat="{status}",secondarystat="{lat_str}",color="{color}"}} 1'
        )

    # ================================
    # 🎯 EDGES
    # ================================
    seen = set()
    for src in NODES:
        for dst in PEERS[src]:
            if dst not in NODES: continue
            key = tuple(sorted([src, dst]))
            if key in seen: continue
            seen.add(key)

            b1 = traf.get((src, dst), 0.0)
            b2 = traf.get((dst, src), 0.0)
            total = b1 + b2

            if total == 0: color= "gray"
            elif total < EDGE_LOW_THRESHOLD: color = "green"
            elif total < EDGE_MED_THRESHOLD: color = "yellow"
            else: color = "red"

            out.append(
                f'nodegraph_edge_info{{source="{src}",target="{dst}",id="{src}_to_{dst}",'
                f'mainstat="{total:.2f}",subtitle="B/s",color="{color}"}} 1'
            )

    return Response("\n".join(out) + "\n", mimetype="text/plain")


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=9101)
