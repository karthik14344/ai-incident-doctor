# KnowledgeAI operations notes

Short, practical notes for whoever is on call for the document assistant.

## Restarting a single service

Restart one service with `docker compose restart <service>`; the gateway tolerates a restarting dependency and answers with a refusal until it is back.
