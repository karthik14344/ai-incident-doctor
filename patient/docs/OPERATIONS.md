# KnowledgeAI operations notes

Short, practical notes for whoever is on call for the document assistant.

## Restarting a single service

Restart one service with `docker compose restart <service>`; the gateway tolerates a restarting dependency and answers with a refusal until it is back.

## Where the logs are

Every service writes one JSON line per request to stdout. Grafana's Loki datasource has them; filter with `| json | level="ERROR"` to see only failures.

## Checking the knowledge base version

The live knowledge-base version is the `kb_version` label on `knowledgeai_build_info` and in `kb/manifest.json` of the deployed commit.

## Slow first answer after a restart

The first chat after Ollama loads a model can take tens of seconds; this is model load time, not a fault. Subsequent answers are fast.

## Uploading documents

Uploads go through the Documents page. Processing runs in the ingestion service; the document status moves from uploaded to processed.

## Reading the operations dashboard

Request rate and in-flight requests show demand; p95 latency and error rate show how well it is being served. Read them together.

## Rate limiting

The gateway limits requests per chat session. A burst from one browser tab is refused by the rate-limit guardrail, which is expected behaviour.
