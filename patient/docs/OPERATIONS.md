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

## Rolling back

Every deploy is tagged with its git SHA. The deploy script rolls back automatically when the smoke test fails; to roll back by hand, redeploy the previous SHA.

## Ollama model list

The Settings page lists the models Ollama has installed. Only llama3.2 is used for chat by default; the Model Comparison page can benchmark the others.

## Backups

The SQLite database lives in the appdata volume and the vector index in chroma-data. Snapshot both volumes together so documents and vectors stay consistent.

## Guardrail refusals

A refusal is not an outage. Check the guardrails field in the chat response to see which guardrail refused and why.
