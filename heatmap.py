#pip install flask
from flask import Flask, jsonify
import random
import time
import threading
from datetime import datetime

app = Flask(__name__)

# Estat actual de la xarxa
network_state = {
    "gateway-01": 0, "web-01": 0, "web-02": 0,
    "app-01": 0, "app-02": 0, "app-03": 0,
    "cache-01": 0, "db-05": 0, "db-06": 0, "storage-01": 0
}

# Simulació de canvis en segon pla
def simulate_changes():
    """Funció que corre en segon plan canviant l'estat dels nodes"""
    while True:
        # Cada 3 segons canvia un node a l'atzar
        time.sleep(3)
        
        node = random.choice(list(network_state.keys()))
        # 70% probabilitat de normal, 30% d'error
        new_state = 0 if random.random() < 0.3 else random.randint(1, 3)
        
        network_state[node] = new_state
        print(f"🔄 {datetime.now().strftime('%H:%M:%S')} - {node} -> {new_state}")

@app.route('/api/network-state')
def get_network_state():
    """API que retorna l'estat actual de la xarxa"""
    return jsonify(network_state)

@app.route('/')
def index():
    """Pàgina principal amb la visualització en temps real"""
    return """
<!DOCTYPE html>
<html>
<head>
    <title>Network Heatmap - Temps Real</title>
    <script src="https://unpkg.com/vis-network/standalone/umd/vis-network.min.js"></script>
    <style>
        body { font-family: Arial, sans-serif; margin: 0; padding: 20px; }
        #network { width: 100%; height: 800px; border: 1px solid #ccc; }
        .status { padding: 10px; background: #f5f5f5; margin-bottom: 10px; }
    </style>
</head>
<body>
    <div class="status">
        <h2>🌐 Monitor de Xarxa - Temps Real</h2>
        <div id="lastUpdate">⏰ Última actualització: --</div>
        <div id="nodeCount">📊 Nodes: 10 | Actualitzant cada 2 segons</div>
    </div>
    <div id="network"></div>

    <script>
        // Colors pels nivells de risc
        const riskColors = {
            0: { background: '#00ff00', border: '#00cc00' }, // Verd
            1: { background: '#ffff00', border: '#cccc00' }, // Groc
            2: { background: '#ff9900', border: '#cc7700' }, // Taronja
            3: { background: '#ff0000', border: '#cc0000' }  // Vermell
        };

        const riskLabels = {
            0: 'Normal', 1: 'Risc Mitjà', 2: 'Risc Alt', 3: 'Risc Crític'
        };

        // Configuració dels nodes amb posicions fixes
        const nodes = new vis.DataSet([
            { id: 'gateway-01', label: 'Gateway-01', x: 0, y: 0, fixed: true },
            { id: 'web-01', label: 'Web-01', x: -200, y: 100, fixed: true },
            { id: 'web-02', label: 'Web-02', x: 200, y: 100, fixed: true },
            { id: 'app-01', label: 'App-01', x: -300, y: 200, fixed: true },
            { id: 'app-02', label: 'App-02', x: 0, y: 200, fixed: true },
            { id: 'app-03', label: 'App-03', x: 300, y: 200, fixed: true },
            { id: 'cache-01', label: 'Cache-01', x: -400, y: 300, fixed: true },
            { id: 'db-05', label: 'DB-05', x: -100, y: 300, fixed: true },
            { id: 'db-06', label: 'DB-06', x: 100, y: 300, fixed: true },
            { id: 'storage-01', label: 'Storage-01', x: 0, y: 400, fixed: true }
        ]);

        // Connexions
        const edges = new vis.DataSet([
            { from: 'gateway-01', to: 'web-01' },
            { from: 'gateway-01', to: 'web-02' },
            { from: 'web-01', to: 'app-01' },
            { from: 'web-02', to: 'app-02' },
            { from: 'web-02', to: 'app-03' },
            { from: 'app-01', to: 'cache-01' },
            { from: 'app-02', to: 'db-05' },
            { from: 'app-03', to: 'db-06' },
            { from: 'db-05', to: 'storage-01' },
            { from: 'db-06', to: 'storage-01' }
        ]);

        // Configuració de la xarxa
        const container = document.getElementById('network');
        const data = { nodes: nodes, edges: edges };
        const options = {
            physics: { enabled: false }, // Nodes fixos
            interaction: { dragNodes: false, dragView: true, zoomView: true },
            nodes: { 
                font: { size: 14 },
                shape: 'dot',
                size: 25
            }
        };

        const network = new vis.Network(container, data, options);

        // Funció per actualitzar els colors des de l'API
        async function updateNetworkState() {
            try {
                const response = await fetch('/api/network-state');
                const states = await response.json();
                
                // Actualitza cada node amb el seu estat
                nodes.getIds().forEach(nodeId => {
                    const riskLevel = states[nodeId] || 0;
                    const colorConfig = riskColors[riskLevel];
                    
                    nodes.update({
                        id: nodeId,
                        color: colorConfig,
                        title: `${nodeId}\\nEstat: ${riskLabels[riskLevel]}`
                    });
                });
                
                // Actualitza l'última actualització
                document.getElementById('lastUpdate').textContent = 
                    `⏰ Última actualització: ${new Date().toLocaleTimeString()}`;
                    
            } catch (error) {
                console.error('Error actualitzant:', error);
            }
        }

        // Actualitza cada 2 segons
        setInterval(updateNetworkState, 2000);
        
        // Primera actualització immediata
        updateNetworkState();
    </script>
</body>
</html>
    """

if __name__ == '__main__':
    # Inicia la simulació en segon pla
    thread = threading.Thread(target=simulate_changes, daemon=True)
    thread.start()
    
    print("🚀 Servidor de monitoring en temps real iniciat!")
    print("🌐 Accedeix a: http://localhost:5000")
    print("🔄 Els colors s'actualitzen automàticament cada 2 segons")
    print("⏹️  Atura el servidor amb Ctrl+C")
    
    app.run(debug=True, use_reloader=False)