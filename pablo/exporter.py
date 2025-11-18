from flask import Flask, Response
import requests
import os
import sys

app = Flask(__name__)

# ==================== CONFIGURACIÓN ====================
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

# ==================== FUNCIONES DE PROMETHEUS ====================
def prom_query(query):
    try:
        # Timeout de 5s para seguridad
        resp = requests.get(f"{PROM_URL}/api/v1/query", params={"query": query}, timeout=5.0)
        resp.raise_for_status()
        data = resp.json().get("data", {}).get("result", [])
        return data
    except Exception as e:
        print(f"ERROR: prom_query falló: {e}", file=sys.stderr)
        return []

def get_ready_status():
    """
    Consulta quién está vivo (Ready=1).
    
    """
    results = prom_query(f'kube_pod_container_status_ready{{namespace="{NAMESPACE}"}}')
    status_map = {}
    
    for r in results:
        pod_name = r["metric"].get("pod", "")
        container = r["metric"].get("container", "")
        val = int(r["value"][1])
        
        for node in NODES:
            # Matching estricto: Exacto o con guion
            if container == node or pod_name == node or pod_name.startswith(f"{node}-"):
                current = status_map.get(node, 0)
                if val > current:
                    status_map[node] = val
                    
    return status_map

# ==================== LÓGICA DE CPU ====================

def get_cpu_values(window):
    """
    Obtiene la tasa de CPU en la ventana especificada.
    Usa la query simple que sabemos que funciona.
    """
    query = f'rate(container_cpu_usage_seconds_total{{namespace="{NAMESPACE}"}}[{window}])'
    results = prom_query(query)
    cpu_map = {}
    
    for r in results:
        pod_name = r["metric"].get("pod", "")
        val = float(r["value"][1])
        
        for node in NODES:
            # Mismo matching estricto que ha arreglado el Node 4
            if pod_name == node or pod_name.startswith(f"{node}-"):
                current = cpu_map.get(node, 0.0)
                if val > current:
                    cpu_map[node] = val
                    
    return cpu_map

# ==================== ENDPOINT ====================

@app.route("/metrics")
def metrics():
    # 1. Obtener estados (Rojo/Verde básico)
    ready = get_ready_status()
    
    # 2. Obtener CPU (Ventanas AJUSTADAS)
    # Baseline de 10 minutos: Referencia muy estable
    baselines = get_cpu_values(window="10m")
    # Current de 30 segundos: Detección rápida para la demo
    currents = get_cpu_values(window="30s")

    lines = []

    # 3. Procesar Nodos (Umbrales AJUSTADOS)
    THRESHOLD_SEVERE = 60.0   # Naranja si varía más del 60%
    THRESHOLD_MODERATE = 30.0 # Amarillo si varía más del 30%

    for node in NODES:
        own_status = ready.get(node, 0)
        base = baselines.get(node, 0.00001)
        curr = currents.get(node, 0.0)
        
        if base < 0.00001: base = 0.00001

        color = "green"
        dev = 0.0
        
        if own_status == 0:
            color = "red"
        else:
            dev = ((curr - base) / base) * 100.0
            
            # Valor absoluto para detectar subidas Y bajadas
            if abs(dev) > THRESHOLD_SEVERE:
                color = "orange"
            elif abs(dev) > THRESHOLD_MODERATE:
                color = "yellow"

        # Formato Grafana
        lines.append(
            f'nodegraph_node_info{{id="{node}",title="{node}",subtitle="{dev:.1f}% dev",mainstat="{curr:.4f} cores",color="{color}"}} 1'
        )

    # 4. Procesar Aristas (Conexiones)
    seen = set()
    for src, targets in PEERS.items():
        for dst in targets:
            if dst not in NODES: continue
            edge = tuple(sorted([src, dst]))
            if edge in seen: continue
            seen.add(edge)
            lines.append(f'nodegraph_edge_info{{source="{src}",target="{dst}",id="{src}to{dst}"}} 1')

    return Response("\n".join(lines) + "\n", mimetype="text/plain")

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=9101)