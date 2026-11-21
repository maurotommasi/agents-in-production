# Production AI Gateway and Model Router

Single file service (`gateway.py`, Python standard library only, no
dependencies to install) that puts one controlled path in front of every
model call: unified auth, task based routing with a fallback chain,
provider health tracking, per team budgets enforced before the call, per
customer rate limits, an exact match response cache, guardrails, and a
full request log with model, tokens and cost per request.

Companion code for the guide "How to Design a Production AI Gateway and
Model Router" by Eng. Mauro Tommasi.

## Run it

```bash
python3 gateway.py                 # serves on http://127.0.0.1:8080
GATEWAY_PORT=9000 python3 gateway.py
```

## Try it

```bash
curl -s -X POST localhost:8080/v1/chat -H 'X-API-Key: demo-key' \
  -H 'Content-Type: application/json' \
  -d '{"team":"support","task":"support_reply","customer_id":"c1",
       "prompt":"Where is my invoice?"}'

curl -s localhost:8080/stats -H 'X-API-Key: demo-key'
curl -s localhost:8080/health
```

Every response carries a receipt: model used, tokens, cost in USD,
latency, whether a fallback was used, and whether it was a cache hit.
Every request is appended as one JSON line to `gateway_requests.jsonl`
(override with the `GATEWAY_LOG` environment variable).

## Demo keys

`demo-key` (team support), `product-key`, `risk-key`, `internal-key`.
Replace `API_KEYS` and `TEAM_BUDGETS` with your own store in real use.

## Using real providers

Providers run as deterministic mocks by default, so the gateway works
with no keys. To call a real OpenAI-compatible endpoint, set `base_url`
in the `PROVIDERS` table and export the key named in `key_env`, for
example `FRONTIER_API_KEY`.

## Design notes

- Applications ask for a task (`support_reply`, `doc_extract`, ...),
  never a model. The routing table maps tasks to model chains.
- Budgets are enforced before the call: alert at 80 percent, downgrade
  at 100 percent, hard reject at 120 percent of the team budget.
- Cache keys are scoped per customer, so cached answers never cross
  customers.
- The gateway is stateless per request and safe to run in several
  replicas behind a load balancer; move budgets, cache and health to a
  shared store (for example Redis) when you scale past one process.
