# KnowledgeAI operations notes

Short, practical notes for whoever is on call for the document assistant.

## Restarting a single service

Restart one service with `docker compose restart <service>`; the gateway tolerates a restarting dependency and answers with a refusal until it is back.

## Where the logs are

Every service writes one JSON line per request to stdout. Grafana's Loki datasource has them; filter with `| json | level="ERROR"` to see only failures.

## Checking the knowledge base version

The live knowledge-base version is the `kb_version` label on `knowledgeai_build_info` and in `kb/manifest.json` of the deployed commit.
