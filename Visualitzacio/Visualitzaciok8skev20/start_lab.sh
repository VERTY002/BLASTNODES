#!/usr/bin/env bash
set -Eeuo pipefail

# ==========================================
# 🚀 BLASTNODES - START LAB (1 namespace)
# + Build local imagen (minikube image build)
# + Port-forward persistente a Grafana/Prometheus
# + Chaos Mesh (helm) + dashboard en localhost:2333
# ==========================================

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" &>/dev/null && pwd)"
BASE_DIR="${BASE_DIR:-$SCRIPT_DIR}"

NS="blast"
CHAOS_NS="chaos-testing"

PROM_PORT_LOCAL="${PROM_PORT_LOCAL:-9090}"
GRAFANA_PORT_LOCAL="${GRAFANA_PORT_LOCAL:-3000}"
CHAOS_DASH_LOCAL="${CHAOS_DASH_LOCAL:-2333}"

DEPLOYMENTS_YAML="$BASE_DIR/deployments.yaml"
SERVICES_YAML="$BASE_DIR/services.yaml"

IMAGE_NAME="${IMAGE_NAME:-kevf20/tcp-node-metrics:latest}"

# Si usas hostPath en tus manifests (Prom/Grafana):
LOCAL_DIR="${LOCAL_DIR:-/home/kevf20/BLASTNODES}"
MINIKUBE_MOUNT_PATH="${MINIKUBE_MOUNT_PATH:-/home/kevf20/BLASTNODES}"

PF_PIDS=""

ts() { date +"%Y-%m-%d %H:%M:%S"; }
log(){ printf "[%s] %s\n" "$(ts)" "$*"; }
have(){ command -v "$1" >/dev/null 2>&1; }
require(){ have "$1" || { echo "❌ Falta: $1"; exit 1; }; }

# ---------- util puertos ----------
port_in_use() {
  if have ss; then ss -ltn | awk '{print $4}' | grep -q ":$1$"
  else netstat -ltn | awk '{print $4}' | grep -q ":$1$"; fi
}
kill_if_running_on_port() {
  local p; p=$(lsof -ti tcp:"$1" 2>/dev/null || true)
  [[ -n "${p:-}" ]] && { log "🔪 Cerrando pid(s) $p en :$1"; kill $p 2>/dev/null || true; }
}

# ---------- apply helpers ----------
ensure_ns(){ kubectl get ns "$1" &>/dev/null || { log "📦 Creando ns $1"; kubectl create ns "$1" >/dev/null; }; }
apply_if_exists() {
  local file=$1 ns=${2:-}
  if [[ -f "$file" ]]; then
    log "📄 Aplicando $file en ${ns:-cluster}"
    [[ -n "$ns" ]] && kubectl apply -f "$file" -n "$ns" >/dev/null || kubectl apply -f "$file" >/dev/null
  else
    log "⚠️  Falta $file; me lo salto."
  fi
}
rollout_wait() {
  local ns=$1 selector=$2 kind=${3:-deployment}
  local names; names=$(kubectl -n "$ns" get "$kind" -l "$selector" -o jsonpath='{range .items[*]}{.metadata.name}{"\n"}{end}' 2>/dev/null || true)
  [[ -z "$names" ]] && { log "⚠️  No hay $kind con selector '$selector' en $ns"; return 0; }
  while read -r name; do
    [[ -z "$name" ]] && continue
    log "⏳ Esperando $kind/$name en $ns..."
    kubectl -n "$ns" rollout status "$kind/$name" --timeout=180s || true
  done <<< "$names"
}

# ---------- imagen en minikube ----------
image_present_in_minikube() {
  minikube image ls 2>/dev/null | grep -qE "^${IMAGE_NAME}\$" || minikube image ls 2>/dev/null | grep -q "$IMAGE_NAME"
}
ensure_node_image() {
  if image_present_in_minikube; then
    log "✅ Imagen ya presente en Minikube: $IMAGE_NAME"
    return
  fi
  log "⬇️  Intentando 'minikube image load' de $IMAGE_NAME (si existe localmente)…"
  if minikube image load "$IMAGE_NAME" >/dev/null 2>&1; then
    log "✅ Imagen cargada en Minikube (load)"
    return
  fi
  log "🛠️  Construyendo imagen en Minikube desde Dockerfile"
  [[ -f "$BASE_DIR/Dockerfile" && -f "$BASE_DIR/app.py" ]] || { log "❌ Falta Dockerfile o app.py en $BASE_DIR"; exit 1; }
  minikube image build -t "$IMAGE_NAME" -f "$BASE_DIR/Dockerfile" "$BASE_DIR" >/dev/null
  image_present_in_minikube || { log "❌ La imagen no aparece tras la build"; exit 1; }
  log "✅ Imagen construida y disponible: $IMAGE_NAME"
}

# ---------- port-forward robusto (servicios) ----------
pf() {
  local ns=$1 svc=$2 lport=$3 rport=${4:-$lport}
  local logf="/tmp/pf_${ns}_${svc}_${lport}.log"

  kill_if_running_on_port "$lport"
  : > "$logf"

  kubectl -n "$ns" port-forward "svc/$svc" "$lport:$rport" >"$logf" 2>&1 &
  local pid=$!
  PF_PIDS="$PF_PIDS $pid"
  log "🔌 Port-forward $ns/$svc 127.0.0.1:$lport → $rport (pid $pid)"

  local ok=0
  for _ in {1..30}; do
    kill -0 "$pid" 2>/dev/null || break
    if grep -qE "Forwarding from 127\.0\.0\.1:$lport|Handling connection" "$logf"; then ok=1; break; fi
    sleep 0.3
  done
  if [[ "$ok" -ne 1 ]]; then
    log "❌ Falló el port-forward a $svc:$rport → localhost:$lport"
    tail -n 30 "$logf" | sed 's/^/[pf-log] /'
    return 1
  fi

  # Health-check suave
  if have curl; then
    local probe_url="http://127.0.0.1:$lport"
    case "$svc" in
      grafana)    probe_url="http://127.0.0.1:$lport/login" ;;
      prometheus) probe_url="http://127.0.0.1:$lport/-/ready" ;;
      chaos-dashboard) probe_url="http://127.0.0.1:$lport" ;;
    esac
    for _ in {1..10}; do
      if curl -sI --max-time 2 "$probe_url" >/dev/null; then
        log "✅ $svc responde en $probe_url"
        break
      fi
      sleep 0.5
    done
  fi
  return 0
}

cleanup() {
  log "🧹 Cerrando túneles..."
  for pid in $PF_PIDS; do kill "$pid" 2>/dev/null || true; done
}
trap cleanup EXIT INT TERM

# ---------- pre-flight ----------
require kubectl; require lsof; require minikube
have ss || have netstat || { echo "❌ Falta ss o netstat"; exit 1; }
log "🧭 Contexto actual: $(kubectl config current-context 2>/dev/null || echo 'desconocido')"
log "📂 BASE_DIR = $BASE_DIR"

# Minikube + mount (si usas hostPath)
if ! minikube status 2>/dev/null | grep -q "host: Running"; then
  log "🚀 Iniciando Minikube…"
  minikube start --driver=docker >/dev/null
fi
if ! pgrep -f "minikube mount $LOCAL_DIR:$MINIKUBE_MOUNT_PATH" >/dev/null 2>&1; then
  log "📂 Montando carpeta local en Minikube…"
  nohup minikube mount "$LOCAL_DIR:$MINIKUBE_MOUNT_PATH" >/dev/null 2>&1 &
  sleep 2
else
  log "✅ Carpeta local ya montada en Minikube."
fi

# Namespaces
ensure_ns "$NS"
ensure_ns "$CHAOS_NS"

# Imagen (evita ImagePullBackOff)
ensure_node_image

# Despliegue de la app (nodos + prom + grafana)
log "🚀 Desplegando TODO en ns=$NS (Prometheus, Grafana y nodos)…"
apply_if_exists "$DEPLOYMENTS_YAML" "$NS"
apply_if_exists "$SERVICES_YAML"    "$NS"

# Re-crear pods nodeX (para coger :latest)
kubectl -n "$NS" rollout restart deploy/node{1..10} >/dev/null 2>&1 || true

# Espera despliegues
rollout_wait "$NS" "app in (prometheus,grafana,node1,node2,node3,node4,node5,node6,node7,node8,node9,node10)" deployment

# ---------- Chaos Mesh (helm) ----------
log "🧩 Instalando/actualizando Chaos Mesh en $CHAOS_NS (runtime=containerd)…"
if ! have helm; then
  log "📦 Helm no encontrado. Intentando instalar (snap primero, luego apt)…"
  if have snap; then sudo snap install helm --classic >/dev/null 2>&1 || true; fi
  if ! have helm; then sudo apt-get update -y >/dev/null 2>&1 || true; sudo apt-get install -y helm >/dev/null 2>&1 || true; fi
  have helm || { log "❌ No pude instalar helm automáticamente. Instálalo y reintenta."; exit 1; }
fi

helm repo add chaos-mesh https://charts.chaos-mesh.org >/dev/null 2>&1 || true
helm repo update >/dev/null 2>&1 || true

# Nota: Minikube (driver docker) usa containerd dentro del nodo ⇒ runtime containerd
helm upgrade --install chaos-mesh chaos-mesh/chaos-mesh \
  --namespace "$CHAOS_NS" --create-namespace \
  --set dashboard.create=true \
  --set dashboard.securityMode=false \
  --set chaosDaemon.runtime=containerd \
  --set chaosDaemon.socketPath=/var/run/containerd/containerd.sock >/dev/null
  
# ---------- Añadir ServiceAccount admin para dashboard ----------
if [[ -f "$BASE_DIR/chaos-dashboard-admin.yaml" ]]; then
  log "🔑 Aplicando ServiceAccount admin para Chaos Dashboard..."
  kubectl apply -f "$BASE_DIR/chaos-dashboard-admin.yaml" >/dev/null
  kubectl -n "$CHAOS_NS" patch deploy chaos-dashboard \
    --type=json \
    -p='[{"op":"replace","path":"/spec/template/spec/serviceAccountName","value":"chaos-dashboard-admin"}]' >/dev/null || true
else
  log "⚠️  No se encontró chaos-dashboard-admin.yaml, se usará cuenta por defecto."
fi


# Esperar componentes clave
log "⏳ Esperando Chaos Mesh (controller, dashboard, daemon) en $CHAOS_NS…"
kubectl -n "$CHAOS_NS" rollout status deploy/chaos-controller-manager --timeout=180s || true
kubectl -n "$CHAOS_NS" rollout status deploy/chaos-dashboard          --timeout=180s || true
# DaemonSet: no hay rollout status, comprobamos que haya al menos 1 listo
kubectl -n "$CHAOS_NS" get ds/chaos-daemon >/dev/null 2>&1 || true

# ---------- TÚNELES SIEMPRE (con verificación) ----------
log "🌐 Creando túneles locales…"
pf "$NS"       "grafana"         "$GRAFANA_PORT_LOCAL" 3000 || true
pf "$NS"       "prometheus"      "$PROM_PORT_LOCAL"    9090 || true
pf "$CHAOS_NS" "chaos-dashboard" "$CHAOS_DASH_LOCAL"   2333 || true

log "📈 Grafana    → http://localhost:${GRAFANA_PORT_LOCAL}   (admin / admin)"
log "📊 Prometheus → http://localhost:${PROM_PORT_LOCAL}"
log "🧪 ChaosMesh  → http://localhost:${CHAOS_DASH_LOCAL}"

# Mostrar estado rápido
kubectl -n "$NS" get pods -o wide | sed 's/^/[blast] /' || true
kubectl -n "$CHAOS_NS" get pods -o wide | sed 's/^/[chaos] /' || true

# Mantenemos vivos los túneles; Ctrl+C para salir
if [[ -z "${PF_PIDS// /}" ]]; then
  log "❌ No hay túneles activos. Revisa services/pods y puertos locales."
  exit 1
fi
log "⏳ Dejo los túneles abiertos. Pulsa Ctrl+C para cerrar."
wait

