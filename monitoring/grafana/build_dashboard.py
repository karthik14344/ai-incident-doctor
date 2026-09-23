"""Generate grafana/dashboards/knowledgeai.json.

The dashboard is written as code so a change to it is a readable diff:
    python monitoring/grafana/build_dashboard.py
"""

import json
import os

PROM = {"type": "prometheus", "uid": "prometheus"}
LOKI = {"type": "loki", "uid": "loki"}


def ts(panel_id, title, targets, unit="short", x=0, y=0, w=12, h=8, description=""):
    return {
        "id": panel_id, "type": "timeseries", "title": title, "description": description,
        "datasource": PROM, "gridPos": {"x": x, "y": y, "w": w, "h": h},
        "fieldConfig": {"defaults": {"unit": unit, "custom": {"lineWidth": 2, "fillOpacity": 8}},
                        "overrides": []},
        "options": {"legend": {"displayMode": "list", "placement": "bottom"},
                    "tooltip": {"mode": "multi"}},
        "targets": [{"refId": chr(65 + i), "expr": expr, "legendFormat": legend, "datasource": PROM}
                    for i, (expr, legend) in enumerate(targets)],
    }


panels = [
    ts(1, "Request rate", [
        ('sum by (service) (rate(knowledgeai_http_requests_total{endpoint!="/metrics"}[1m]))', "{{service}}"),
    ], "reqps", 0, 0, description="Requests per second served by each service."),
    ts(2, "Error rate", [
        ('sum by (service) (rate(knowledgeai_http_requests_total{status=~"5.."}[1m])) '
         '/ sum by (service) (rate(knowledgeai_http_requests_total{endpoint!="/metrics"}[1m]))', "5xx {{service}}"),
        ('sum(rate(knowledgeai_chat_answers_total{outcome="error"}[1m])) '
         '/ sum(rate(knowledgeai_chat_answers_total[1m]))', "chat errors"),
    ], "percentunit", 12, 0, description="Share of 5xx responses, and of chat answers that ended in an error."),
    ts(3, "p95 latency", [
        ('histogram_quantile(0.95, sum by (le, service, endpoint) '
         '(rate(knowledgeai_http_request_duration_seconds_bucket{endpoint=~"/api/chat|/api/retrieval/search|/retrieve|/generate"}[2m])))',
         "{{service}} {{endpoint}}"),
    ], "s", 0, 8),
    ts(4, "In-flight requests", [
        ("sum by (service) (knowledgeai_http_requests_in_flight)", "{{service}}"),
    ], "short", 12, 8),
    ts(5, "Memory per service", [
        ("knowledgeai_process_resident_memory_bytes", "RSS {{service}}"),
        ('container_memory_working_set_bytes{container_label_com_docker_compose_service=~"gateway|ingestion|retrieval|llm"}',
         "container {{container_label_com_docker_compose_service}}"),
    ], "bytes", 0, 16),
    ts(6, "Embedding fallback counter", [
        ("knowledgeai_embedding_fallback_total", "total {{service}}"),
        ("increase(knowledgeai_embedding_fallback_total[1m])", "per minute {{service}}"),
    ], "short", 12, 16, description="Expected to stay flat. Any rise means answers were retrieved with fallback vectors."),
    ts(7, "Downstream call failures", [
        ("sum by (service, target, reason) (rate(knowledgeai_downstream_failures_total[1m]))",
         "{{service}} -> {{target}} ({{reason}})"),
    ], "reqps", 0, 24),
    ts(8, "Ollama call p95 and failures", [
        ("histogram_quantile(0.95, sum by (le, operation) (rate(knowledgeai_ollama_request_duration_seconds_bucket[2m])))",
         "p95 {{operation}}"),
        ("sum by (operation, reason) (rate(knowledgeai_ollama_failures_total[1m]))", "failures {{operation}} {{reason}}"),
    ], "s", 12, 24),
    ts(9, "Retrieval: chunks per query and zero-chunk rate", [
        ("rate(knowledgeai_retrieved_chunks_sum[2m]) / rate(knowledgeai_retrieved_chunks_count[2m])", "avg chunks"),
        ("rate(knowledgeai_zero_chunk_retrievals_total[2m]) / rate(knowledgeai_retrieved_chunks_count[2m])",
         "zero-chunk share"),
    ], "short", 0, 32),
    ts(10, "Chat outcomes", [
        ("sum by (outcome) (rate(knowledgeai_chat_answers_total[1m]))", "{{outcome}}"),
    ], "reqps", 12, 32),
    {
        "id": 11, "type": "logs", "title": "Error log lines", "datasource": LOKI,
        "gridPos": {"x": 0, "y": 40, "w": 24, "h": 10},
        "options": {"showTime": True, "wrapLogMessage": True, "sortOrder": "Descending"},
        "targets": [{"refId": "A", "datasource": LOKI,
                     "expr": '{compose_service=~"gateway|ingestion|retrieval|llm"} |= "\\"level\\": \\"ERROR\\""'}],
    },
]

dashboard = {
    "uid": "knowledgeai-ops",
    "title": "KnowledgeAI - operations",
    "tags": ["knowledgeai"],
    "timezone": "browser",
    "schemaVersion": 39,
    "refresh": "10s",
    "time": {"from": "now-30m", "to": "now"},
    "annotations": {"list": [
        {"name": "Deploys", "datasource": {"type": "grafana", "uid": "-- Grafana --"}, "enable": True,
         "iconColor": "rgba(0, 211, 255, 1)",
         "target": {"type": "tags", "tags": ["deploy"], "limit": 100, "matchAny": False}},
        {"name": "Fault injection", "datasource": {"type": "grafana", "uid": "-- Grafana --"}, "enable": True,
         "iconColor": "rgba(255, 96, 96, 1)",
         "target": {"type": "tags", "tags": ["fault"], "limit": 100, "matchAny": False}},
    ]},
    "panels": panels,
}

out = os.path.join(os.path.dirname(os.path.abspath(__file__)), "dashboards", "knowledgeai.json")
with open(out, "w", encoding="utf-8", newline="\n") as fh:
    json.dump(dashboard, fh, indent=2)
print(f"wrote {out} ({len(panels)} panels)")
