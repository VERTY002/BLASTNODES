#!/bin/bash

set -e

# === CONFIG ===
CHAOS_NS="chaos-testing"
DASHBOARD_PORT=2333

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

# === REFRESH PODS (namespace 'default') ===
if [ "$1" == "--fresh" ]; then
  echo "🧹 Haciendo refresh de los pods en el namespace 'default'..."
  kubectl get pods -n default

  # Reinicia los pods en el namespace 'default'
  kubectl delete pods --all -n default

  # Verifica que los pods se reinicien
  echo "⏳ Esperando que los pods se reinicien..."
  kubectl get pods -n default -w
fi

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

# === APPLY DEPLOYMENTS ===
echo ""
echo "📦 Applying Kubernetes deployments..."
kubectl apply -f deployments.yaml

echo "🔧 Applying Kubernetes services..."
kubectl apply -f services.yaml

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

echo ""
echo "🌀 Loading Chaos Mesh pods... (this may take a few minutes)"
spinner="/|\\-/|\\-"
i=0
while true; do
  total=$(kubectl -n $CHAOS_NS get pods --no-headers 2>/dev/null | wc -l || true)
  ready=$(kubectl -n $CHAOS_NS get pods --no-headers 2>/dev/null | grep -c "Running" || true)
  if [ "$total" -gt 0 ] && [ "$ready" -eq "$total" ]; then
    echo -ne "\r✅ All pods are ready! ($ready/$total)                     \n"
    break
  fi
  i=$(( (i+1) %8 ))
  printf "\r${spinner:$i:1} Loading... Pods ready: $ready/$total"
  sleep 3
done

# === DASHBOARD SERVICEACCOUNT ===
echo ""
echo "🧑‍💻 Creating ServiceAccount for Chaos Mesh dashboard..."
kubectl apply -f chaos-dashboard-admin.yaml >/dev/null 2>&1

# === WAIT FOR DASHBOARD ===
echo ""
echo "⏳ Waiting for Chaos Mesh dashboard pod to initialize..."
while ! kubectl -n $CHAOS_NS get pods -l app.kubernetes.io/component=chaos-dashboard 2>/dev/null | grep -q "Running"; do
  printf "\r⏳ Loading dashboard..."
  sleep 2
done
echo -e "\r✅ Dashboard pod is running!                         "

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

# === OPEN DASHBOARD ===
echo ""
echo "🌐 Opening Chaos Mesh Dashboard..."
POD_NAME=$(kubectl -n $CHAOS_NS get pod -l app.kubernetes.io/component=chaos-dashboard -o jsonpath="{.items[0].metadata.name}")
kubectl -n $CHAOS_NS port-forward "$POD_NAME" $DASHBOARD_PORT:2333 >/dev/null 2>&1 &
sleep 5
xdg-open "http://localhost:$DASHBOARD_PORT" >/dev/null 2>&1 || echo "👉 Open manually: http://localhost:$DASHBOARD_PORT"

# === STATUS ===
echo ""
echo "📊 Showing current cluster status:"
kubectl get pods -A
echo ""
echo "🎉 Lab environment is ready and Chaos Mesh dashboard is running!"

# Túneles para acceder a Prometheus y Grafana
echo "⏳ Creando túneles para Prometheus y Grafana..."

# Abre el túnel de Prometheus y obtiene la URL
minikube service prometheus
# Abre el túnel de Grafana y obtiene la URL
minikube service grafana


