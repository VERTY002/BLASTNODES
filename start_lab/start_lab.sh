#!/bin/bash

set -e

# === CONFIG ===
CHAOS_NS="chaos-testing"
DASHBOARD_PORT=2333
PROM_NS="monitoring"
PROM_PORT=9090

# === HELPERS ===
install_if_missing() {
  local cmd="$1"
  local pkg="$2"
  if ! command -v "$cmd" >/dev/null 2>&1; then
    echo "📦 Installing $pkg..."
    sudo apt-get update -y >/dev/null 2>&1
    sudo apt-get install -y "$pkg" >/dev/null 2>&1
  else
    echo "✅ $pkg already installed."
  fi
}

wait_for_pods() {
  local namespaces=("$@")
  local spinner="/|\\-/|\\-"
  local i=0

  echo ""
  echo "🕐 Waiting for all pods in namespaces: ${namespaces[*]} ..."
  echo "(This may take several minutes depending on your system and internet connection.)"
  echo ""

  while true; do
    local all_ready=true
    local total_sum=0
    local ready_sum=0

    for ns in "${namespaces[@]}"; do
      total=$(kubectl -n "$ns" get pods --no-headers 2>/dev/null | wc -l || true)
      ready=$(kubectl -n "$ns" get pods --no-headers 2>/dev/null | grep -c "Running" || true)
      total_sum=$((total_sum + total))
      ready_sum=$((ready_sum + ready))
      if [ "$total" -eq 0 ] || [ "$ready" -lt "$total" ]; then
        all_ready=false
      fi
    done

    if [ "$all_ready" = true ]; then
      echo -ne "\r✅ All pods are ready! ($ready_sum/$total_sum)                     \n"
      break
    fi

    i=$(( (i+1) %8 ))
    printf "\r${spinner:$i:1} Pods ready: $ready_sum/$total_sum"
    sleep 3
  done
}

# === HEADER ===
echo "=========================================="
echo "🚀 BlastNodes Lab Environment Initializer"
echo "=========================================="
echo ""

# === INSTALL DEPENDENCIES ===
install_if_missing curl curl
install_if_missing wget wget
install_if_missing git git

if ! command -v docker >/dev/null 2>&1; then
  echo "🐳 Installing Docker..."
  sudo apt-get remove -y docker docker-engine docker.io containerd runc >/dev/null 2>&1 || true
  sudo apt-get install -y ca-certificates curl gnupg lsb-release >/dev/null 2>&1
  sudo install -m 0755 -d /etc/apt/keyrings
  curl -fsSL https://download.docker.com/linux/ubuntu/gpg | sudo gpg --dearmor -o /etc/apt/keyrings/docker.gpg
  echo \
    "deb [arch=$(dpkg --print-architecture) signed-by=/etc/apt/keyrings/docker.gpg] \
    https://download.docker.com/linux/ubuntu $(lsb_release -cs) stable" | \
    sudo tee /etc/apt/sources.list.d/docker.list >/dev/null
  sudo apt-get update -y >/dev/null
  sudo apt-get install -y docker-ce docker-ce-cli containerd.io docker-buildx-plugin docker-compose-plugin >/dev/null
  sudo systemctl enable docker
  sudo systemctl start docker
else
  echo "✅ Docker already installed."
fi

if ! command -v kubectl >/dev/null 2>&1; then
  echo "📥 Installing kubectl..."
  curl -LO "https://dl.k8s.io/release/$(curl -L -s https://dl.k8s.io/release/stable.txt)/bin/linux/amd64/kubectl"
  sudo install -o root -g root -m 0755 kubectl /usr/local/bin/kubectl
  rm kubectl
else
  echo "✅ kubectl already installed."
fi

if ! command -v minikube >/dev/null 2>&1; then
  echo "📦 Installing Minikube..."
  curl -Lo minikube https://storage.googleapis.com/minikube/releases/latest/minikube-linux-amd64
  sudo install minikube /usr/local/bin/
  rm minikube
else
  echo "✅ Minikube already installed."
fi

if ! command -v helm >/dev/null 2>&1; then
  echo "📥 Installing Helm..."
  curl https://raw.githubusercontent.com/helm/helm/main/scripts/get-helm-3 | bash
else
  echo "✅ Helm already installed."
fi

# === START CLUSTER ===
echo ""
echo "🚀 Starting Minikube cluster..."
minikube start --cpus=3 --memory=6144 --driver=docker

# === CHAOS MESH ===
echo ""
echo "🌪️ Creating Chaos Mesh namespace..."
kubectl create ns $CHAOS_NS --dry-run=client -o yaml | kubectl apply -f -

echo "📥 Adding Chaos Mesh Helm repo..."
helm repo add chaos-mesh https://charts.chaos-mesh.org >/dev/null 2>&1 || true
helm repo update >/dev/null 2>&1

echo "⚙️ Installing Chaos Mesh..."
helm upgrade --install chaos-mesh chaos-mesh/chaos-mesh -n $CHAOS_NS \
  --set dashboard.securityMode=false >/dev/null 2>&1 || true

# === PROMETHEUS ===
echo ""
echo "📈 Installing Prometheus for monitoring..."
kubectl create ns $PROM_NS --dry-run=client -o yaml | kubectl apply -f - >/dev/null 2>&1

helm repo add prometheus-community https://prometheus-community.github.io/helm-charts >/dev/null 2>&1 || true
helm repo update >/dev/null 2>&1

helm upgrade --install prometheus prometheus-community/prometheus -n $PROM_NS \
  --set dashboard.securityMode=false >/dev/null 2>&1 || true


# === APPLY DEPLOYMENTS ===
echo ""
echo "📦 Applying Kubernetes deployments..."
kubectl apply -f deployments.yaml

echo "🔧 Applying Kubernetes services..."
kubectl apply -f services.yaml
kubectl apply -f deployments_monitor.yaml


# === WAIT BOTH ===
wait_for_pods "$CHAOS_NS" "$PROM_NS"

# === DASHBOARD SERVICEACCOUNT ===
echo ""
echo "🧑‍💻 Creating ServiceAccount for Chaos Mesh dashboard..."
kubectl apply -f chaos-dashboard-admin.yaml >/dev/null 2>&1

# === GET TOKEN ===
echo ""
echo "🔑 Retrieving dashboard access token..."
TOKEN=$(kubectl -n $CHAOS_NS create token chaos-dashboard-admin 2>/dev/null || echo "TokenError")
if [[ "$TOKEN" != "TokenError" ]]; then
  echo "✅ Token generated successfully!"
  echo "🔓 Your access token:"
  echo ""
  echo "$TOKEN"
  echo ""
else
  echo "⚠️ Could not retrieve token automatically. Try manually:"
  echo "kubectl -n $CHAOS_NS create token chaos-dashboard-admin"
fi

# === OPEN DASHBOARDS ===
echo ""
echo "🌐 Opening Chaos Mesh Dashboard..."
POD_NAME=$(kubectl -n $CHAOS_NS get pod -l app.kubernetes.io/component=chaos-dashboard -o jsonpath="{.items[0].metadata.name}")
kubectl -n $CHAOS_NS port-forward "$POD_NAME" $DASHBOARD_PORT:2333 >/dev/null 2>&1 &
sleep 5
xdg-open "http://localhost:$DASHBOARD_PORT" >/dev/null 2>&1 || echo "👉 Open manually: http://localhost:$DASHBOARD_PORT"

echo ""
echo "🌐 Opening Prometheus Dashboard..."
minikube service prometheus -n monitoring 


# === STATUS ===
echo ""
echo "📊 Showing current cluster status:"
kubectl get pods -A
echo ""
echo "🎉 Lab environment is ready with Chaos Mesh and Prometheus running!"
