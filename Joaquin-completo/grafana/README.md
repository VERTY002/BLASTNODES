# Afegir el grafana-values.yaml i grafana-dashboard.yaml

(es pq al obrir el grafana no hagis d'iniciar sessio)

 helm upgrade monitoring prometheus-community/kube-prometheus-stack   --namespace monitoring   --values grafana-values.yaml

  kubectl apply -f grafana-dashboard.yaml
  
  
  kubectl rollout restart deployment/monitoring-grafana -n monitoring


  
  Per mirar que estigui be la part de deshabilitar el login:
  kubectl get configmap monitoring-grafana -n monitoring -o yaml | sed -n 's/^/    /p' | grep -A20 "grafana.ini"
 
  resultat:
      grafana.ini: |
        [analytics]
        check_for_updates = true
        [auth]
        disable_login_form = true
        disable_signout_menu = true
        [auth.anonymous]
        enabled = true
        org_role = Admin
        [grafana_net]
        url = https://grafana.net
        [log]
        mode = console
        [paths]
        data = /var/lib/grafana/
        logs = /var/log/grafana
        plugins = /var/lib/grafana/plugins
        provisioning = /etc/grafana/provisioning
        [server]
        domain = ''
    kind: ConfigMap

