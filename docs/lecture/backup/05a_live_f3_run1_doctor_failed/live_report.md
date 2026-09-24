# Incident inc_efd0fe81ca

**Alert:** ServiceDown - retrieval is not answering Prometheus scrapes
**Started:** 2026-09-24T10:18:06.923Z  
**Running commit:** 73e80cf  
**Evidence arm:** logs_commits_incidents  
**Reasoned by:** None:None

## Diagnosis failed

every provider failed

- glm:glm-4.6: ProviderError: RateLimitError: Error code: 429 - {'error': {'code': '1113', 'message': 'Insufficient balance or no resource package. Please recharge.'}}
- ollama:llama3.2: BudgetExceeded: call budget of 6 exhausted
