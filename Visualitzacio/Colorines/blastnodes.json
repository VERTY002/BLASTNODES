{
  "__inputs": [
    {
      "name": "DS_PROMETHEUS",
      "label": "Prometheus",
      "description": "",
      "type": "datasource",
      "pluginId": "prometheus",
      "pluginName": "Prometheus"
    }
  ],
  "__elements": {},
  "__requires": [
    {
      "type": "grafana",
      "id": "grafana",
      "name": "Grafana",
      "version": "10.3.4"
    },
    {
      "type": "panel",
      "id": "nodeGraph",
      "name": "Node Graph",
      "version": ""
    },
    {
      "type": "datasource",
      "id": "prometheus",
      "name": "Prometheus",
      "version": "1.0.0"
    }
  ],
  "annotations": {
    "list": [
      {
        "builtIn": 1,
        "datasource": {
          "type": "grafana",
          "uid": "-- Grafana --"
        },
        "enable": true,
        "hide": true,
        "iconColor": "rgba(0, 211, 255, 1)",
        "name": "Annotations & Alerts",
        "type": "dashboard"
      }
    ]
  },
  "editable": true,
  "fiscalYearStartMonth": 0,
  "graphTooltip": 0,
  "id": null,
  "links": [],
  "liveNow": false,
  "panels": [
    {
      "datasource": {
        "type": "prometheus",
        "uid": "${DS_PROMETHEUS}"
      },
      "gridPos": {
        "h": 22,
        "w": 24,
        "x": 0,
        "y": 0
      },
      "id": 1,
      "options": {
        "edges": {
          "mainStatUnit": "short",
          "secondaryStatUnit": "ms"
        },
        "nodes": {
          "arcs": [
            {
              "color": "#56A64B",
              "field": "arc__success"
            },
            {
              "color": "#C4162A",
              "field": "arc__fail"
            }
          ],
          "mainStatUnit": "percentunit",
          "secondaryStatUnit": "none"
        }
      },
      "targets": [
        {
          "datasource": {
            "type": "prometheus",
            "uid": "${DS_PROMETHEUS}"
          },
          "editorMode": "code",
          "exemplar": false,
          "expr": "label_replace(label_replace(\n  estado_salud_nodo / 100\n  , \"id\", \"$0\", \"nodo\", \".*\")\n    , \"title\", \"$0\", \"nodo\", \".*\")",
          "format": "table",
          "instant": true,
          "legendFormat": "__auto",
          "range": false,
          "refId": "A"
        },
        {
          "datasource": {
            "type": "prometheus",
            "uid": "${DS_PROMETHEUS}"
          },
          "editorMode": "code",
          "exemplar": false,
          "expr": "label_join(\nlabel_replace(label_replace(\n  conexiones_activas\n ,\"source\",\"$0\",\"desde_nodo\",\".*\")\n,\"target\",\"$0\",\"hacia_nodo\",\".*\")\n,\"id\",\"_\",\"desde_nodo\",\"hacia_nodo\")",
          "format": "table",
          "hide": false,
          "instant": true,
          "legendFormat": "__auto",
          "range": false,
          "refId": "B"
        },
        {
          "datasource": {
            "type": "prometheus",
            "uid": "${DS_PROMETHEUS}"
          },
          "editorMode": "code",
          "exemplar": false,
          "expr": "label_join(\nlabel_replace(label_replace(\n  latencia_conexion_ms\n ,\"source\",\"$0\",\"desde_nodo\",\".*\")\n,\"target\",\"$0\",\"hacia_nodo\",\".*\")\n,\"id\",\"_\",\"desde_nodo\",\"hacia_nodo\")",
          "format": "table",
          "hide": false,
          "instant": false,
          "legendFormat": "__auto",
          "range": true,
          "refId": "C"
        }
      ],
      "transformations": [
        {
          "id": "filterFieldsByName",
          "options": {
            "include": {
              "names": [
                "id",
                "title",
                "Value #A",
                "source",
                "target",
                "Value #B",
                "Value #C"
              ]
            }
          }
        },
        {
          "id": "calculateField",
          "options": {
            "alias": "mainstat",
            "mode": "unary",
            "reduce": {
              "reducer": "sum"
            },
            "unary": {
              "fieldName": "Value #A",
              "operator": "abs"
            }
          }
        },
        {
          "id": "calculateField",
          "options": {
            "alias": "arc__success",
            "binary": {
              "left": "Value #A",
              "operator": "/",
              "right": "1"
            },
            "mode": "binary",
            "reduce": {
              "reducer": "sum"
            },
            "unary": {
              "fieldName": "Value #A",
              "operator": "abs"
            }
          }
        },
        {
          "id": "calculateField",
          "options": {
            "alias": "arc__fail",
            "binary": {
              "left": "1",
              "operator": "-",
              "right": "arc__success"
            },
            "mode": "binary",
            "reduce": {
              "reducer": "sum"
            },
            "unary": {
              "fieldName": "Value #A",
              "operator": "abs"
            }
          }
        }
      ],
      "transparent": true,
      "type": "nodeGraph"
    }
  ],
  "refresh": "5s",
  "schemaVersion": 39,
  "tags": [],
  "templating": {
    "list": []
  },
  "time": {
    "from": "now-15m",
    "to": "now"
  },
  "timeRangeUpdatedDuringEditOrView": false,
  "timepicker": {},
  "timezone": "",
  "title": "Xarxa de Nodes - Visualització",
  "uid": "blastnodes-v2",
  "version": 1,
  "weekStart": ""
}
