######## Instalaciones Previas ##########
- Docker: https://www.docker.com/products/docker-desktop/
- Minikube: https://minikube.sigs.k8s.io/docs/start/?arch=%2Flinux%2Fx86-64%2Fstable%2Fbinary+download
- kubectl: https://pwittrock.github.io/docs/tasks/tools/install-kubectl/
- helm:  https://helm.sh/docs/intro/install/

######## Iniciamos el Cluster de Kubernetes
- minikube start

######## Creamos namespaces ########

- kubectl create namespace nodes
- kubectl create namespace chaos-mesh

######## Instalamos el chart de helm de prometheus #######

- helm repo add prometheus-community https://prometheus-community.github.io/helm-charts
- helm repo update
- helm install monitoring prometheus-community/kube-prometheus-stack --namespace monitoring --create-namespace


######### Instalamos el chart de helm de chaos-mesh #########

- helm repo add chaos-mesh https://charts.chaos-mesh.org
- helm repo update
- helm install chaos-mesh chaos-mesh/chaos-mesh \
  -n chaos-mesh \
  --set chaosDaemon.runtime=docker \
  --set chaosDaemon.socketPath=/var/run/docker.sock \
  --set dashboard.create=true

######### Damos Permisos y generamos token #########

- kubectl apply -f rbac.yaml (Antes de aplicar este comando, entrar desde la terminal a la carpeta chaos-mesh)

######## Aplicamos el resto de deployments y services #########

- kubectl apply -f .


########## Hacemos Port Forward de grafana y chaos mesh y prometheus para acceder desde nuestro local host ###########
- kubectl port-forward svc/monitoring-grafana 3000:80 -n monitoring
- kubectl port-forward -n chaos-mesh svc/chaos-dashboard 2333:2333
- kubectl port-forward -n monitoring svc/prometheus-operated 9090:9090

########## Para acceder a Grafana #######
helm upgrade monitoring prometheus-community/kube-prometheus-stack \
--namespace monitoring
--values grafana-values.yaml

kubectl apply -f grafana-dashboard.yaml

kubectl rollout restart deployment/monitoring-grafana -n monitoring

1- Vamos a localhost:3000
2- Nos pedira usuario y contraseña, usuario es admin, para obtener la contraseña copiamos lo que obtenemos con el siguiente comando:
- kubectl get secret monitoring-grafana -n monitoring -o jsonpath="{.data.admin-password}" | base64 --decode; echo
3 - Nos dirigimos a Dashboards -> New Dashboard -> import -> Copiamos el contenido del fichero nodegraph.json dentro de la carpeta grafana  -> Load

########## Para acceder a Chaos-mesh #########
1- Vamos a localhost:2333
2- Nos pide name y token, en name cualquiera , en token pegamos lo que nos devuelve el comando:
- kubectl create token chaos-controller-manager -n chaos-mesh
Ahora ya si hacemos new experiment pod failure (que dure un minimo de 1 minuto para que de timepo a visualizarse dependera de vuestro ordenador
veremos como se pone el node rojo, y si entramos en los logs los mensajes se reenviaran por otro camino)














