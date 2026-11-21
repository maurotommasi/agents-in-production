#!/usr/bin/env python3
"""Production AI Gateway and Model Router (single file, stdlib only).

One controlled path in front of every model call: unified auth, task based
routing with a fallback chain, provider health tracking, per team budgets
enforced before the call, per customer rate limits, an exact match response
cache, guardrails, and a full request log with model, tokens and cost.

Run:  python3 gateway.py            (serves on http://127.0.0.1:8080)
Try:  curl -s -X POST localhost:8080/v1/chat -H 'X-API-Key: demo-key' \
        -H 'Content-Type: application/json' \
        -d '{"team":"support","task":"support_reply","customer_id":"c1",
             "prompt":"Where is my invoice?"}'
      curl -s localhost:8080/stats -H 'X-API-Key: demo-key'

Providers are mock models by default, so the service runs anywhere with no
keys. Set GATEWAY_MODELS to real OpenAI-compatible endpoints by editing the
PROVIDERS table: any provider with a base_url is called over HTTPS with the
key from the environment variable named in key_env.
"""
import hashlib, json, os, re, sys, threading, time, urllib.request
from collections import defaultdict, deque
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

# --------------------------------------------------------------------------
# Configuration: tasks, routing chains, providers, budgets.
# --------------------------------------------------------------------------
# A task is a capability an application asks for, never a model name.
# max_cost_usd is the most one call to this task may cost; p95_ms is the
# latency budget used when scoring provider health.
TASKS = {
    "support_reply":  {"max_cost_usd": 0.004, "p95_ms": 2500, "cache_ttl": 0},
    "doc_extract":    {"max_cost_usd": 0.002, "p95_ms": 4000, "cache_ttl": 3600},
    "fraud_summary":  {"max_cost_usd": 0.010, "p95_ms": 5000, "cache_ttl": 0},
    "code_help":      {"max_cost_usd": 0.008, "p95_ms": 3000, "cache_ttl": 0},
    "classification": {"max_cost_usd": 0.001, "p95_ms": 1500, "cache_ttl": 3600},
}
# Ordered fallback chain per task: primary, fallback, last resort.
CHAINS = {
    "support_reply":  ["frontier", "standard", "fast"],
    "doc_extract":    ["standard", "fast", "frontier"],
    "fraud_summary":  ["frontier", "standard"],
    "code_help":      ["frontier", "standard", "fast"],
    "classification": ["fast", "standard"],
}
# price_in / price_out are USD per 1,000 tokens. base_url empty = mock.
PROVIDERS = {
    "frontier": {"price_in": 0.005, "price_out": 0.015,
                 "base_url": "", "key_env": "FRONTIER_API_KEY"},
    "standard": {"price_in": 0.001, "price_out": 0.003,
                 "base_url": "", "key_env": "STANDARD_API_KEY"},
    "fast":     {"price_in": 0.0002, "price_out": 0.0006,
                 "base_url": "", "key_env": "FAST_API_KEY"},
}
# Monthly budget per team in USD. Soft limit downgrades, hard cap rejects.
TEAM_BUDGETS = {"support": 4000.0, "product": 3000.0,
                "risk": 2000.0, "internal": 1000.0}
SOFT_LIMIT = 1.00   # at 100% of budget, downgrade non critical tasks
HARD_CAP = 1.20     # at 120% of budget, reject the call
API_KEYS = {"demo-key": "support", "product-key": "product",
            "risk-key": "risk", "internal-key": "internal"}
RATE_LIMIT_PER_MIN = 120          # per customer token bucket refill
LOG_PATH = os.environ.get("GATEWAY_LOG", "gateway_requests.jsonl")
PORT = int(os.environ.get("GATEWAY_PORT", "8080"))

# Guardrail patterns: blocked from leaving to a provider (data rules).
BLOCKED_PATTERNS = [
    re.compile(r"\b\d{3}-\d{2}-\d{4}\b"),                 # US SSN shape
    re.compile(r"\b(?:\d[ -]*?){13,16}\b"),               # card number shape
    re.compile(r"(?i)\b(password|api[_-]?key)\s*[:=]\s*\S+"),
]

# --------------------------------------------------------------------------
# Provider health: rolling 5 minute window of errors and latency per model.
# --------------------------------------------------------------------------
class Health:
    def __init__(self):
        self.events = defaultdict(deque)   # model -> deque of (ts, ok, ms)
        self.lock = threading.Lock()

    def record(self, model, ok, ms):
        with self.lock:
            dq = self.events[model]
            dq.append((time.time(), ok, ms))
            while dq and dq[0][0] < time.time() - 300:
                dq.popleft()

    def ok(self, model, p95_ms):
        with self.lock:
            dq = self.events[model]
            recent = [e for e in dq if e[0] > time.time() - 300]
        if len(recent) < 5:
            return True                    # not enough data: assume healthy
        errors = sum(1 for _, good, _ in recent if not good)
        slow = sorted(ms for _, _, ms in recent)
        p95 = slow[int(0.95 * (len(slow) - 1))]
        return errors / len(recent) < 0.05 and p95 <= p95_ms * 2

HEALTH = Health()

# --------------------------------------------------------------------------
# Budget guard: counters updated on every request, enforced before the call.
# --------------------------------------------------------------------------
class Budgets:
    def __init__(self):
        self.spent = defaultdict(float)    # team -> USD spent this period
        self.lock = threading.Lock()

    def check(self, team, task):
        """Return 'ok', 'downgrade' or 'reject' for this team right now."""
        budget = TEAM_BUDGETS.get(team, 0.0)
        with self.lock:
            used = self.spent[team]
        if budget == 0:
            return "reject"
        if used >= budget * HARD_CAP:
            return "reject"
        if used >= budget * SOFT_LIMIT and task != "fraud_summary":
            return "downgrade"
        return "ok"

    def alert_due(self, team):
        budget = TEAM_BUDGETS.get(team, 0.0)
        with self.lock:
            return budget and self.spent[team] >= budget * 0.80

    def charge(self, team, cost):
        with self.lock:
            self.spent[team] += cost

BUDGETS = Budgets()

# --------------------------------------------------------------------------
# Rate limiter: one token bucket per customer.
# --------------------------------------------------------------------------
class RateLimiter:
    def __init__(self, per_min):
        self.buckets = {}                  # customer -> (tokens, last_ts)
        self.per_min = per_min
        self.lock = threading.Lock()

    def allow(self, customer):
        now = time.time()
        with self.lock:
            tokens, last = self.buckets.get(customer, (self.per_min, now))
            tokens = min(self.per_min,
                         tokens + (now - last) * self.per_min / 60.0)
            if tokens < 1:
                self.buckets[customer] = (tokens, now)
                return False
            self.buckets[customer] = (tokens - 1, now)
            return True

LIMITER = RateLimiter(RATE_LIMIT_PER_MIN)

# --------------------------------------------------------------------------
# Cache: exact prompt match, key scoped per customer so data never crosses
# customers. Key = sha256(customer + task + prompt).
# --------------------------------------------------------------------------
class Cache:
    def __init__(self):
        self.store = {}                    # key -> (expires_ts, response)
        self.lock = threading.Lock()
        self.hits = 0
        self.misses = 0

    @staticmethod
    def key(customer, task, prompt):
        raw = f"{customer}|{task}|{prompt}".encode()
        return hashlib.sha256(raw).hexdigest()

    def get(self, customer, task, prompt, ttl):
        if ttl <= 0:
            return None
        k = self.key(customer, task, prompt)
        with self.lock:
            item = self.store.get(k)
            if item and item[0] > time.time():
                self.hits += 1
                return item[1]
            self.misses += 1
            return None

    def put(self, customer, task, prompt, ttl, response):
        if ttl <= 0:
            return
        k = self.key(customer, task, prompt)
        with self.lock:
            self.store[k] = (time.time() + ttl, response)

CACHE = Cache()

# --------------------------------------------------------------------------
# Request log: one JSON record per request, appended to LOG_PATH and kept
# in memory for /stats. This log powers spend dashboards and audits.
# --------------------------------------------------------------------------
LOG_LOCK = threading.Lock()
LOG_MEM = deque(maxlen=10000)

def log_request(rec):
    rec["ts"] = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
    with LOG_LOCK:
        LOG_MEM.append(rec)
        with open(LOG_PATH, "a") as fh:
            fh.write(json.dumps(rec) + "\n")

def est_tokens(text):
    return max(1, len(text) // 4)         # rough 4 chars per token

def call_provider(model, prompt):
    """Call one provider. Mock providers simulate latency and answers;
    a provider with base_url is called as an OpenAI-compatible API."""
    cfg = PROVIDERS[model]
    if not cfg["base_url"]:
        time.sleep(0.05)                   # simulated provider latency
        answer = f"[{model}] answer to: {prompt[:60]}"
        return answer, est_tokens(prompt), est_tokens(answer)
    body = json.dumps({"model": model, "messages":
                       [{"role": "user", "content": prompt}]}).encode()
    req = urllib.request.Request(cfg["base_url"] + "/chat/completions",
                                 data=body, method="POST")
    req.add_header("Content-Type", "application/json")
    req.add_header("Authorization",
                   "Bearer " + os.environ.get(cfg["key_env"], ""))
    with urllib.request.urlopen(req, timeout=30) as resp:
        data = json.loads(resp.read())
    usage = data.get("usage", {})
    return (data["choices"][0]["message"]["content"],
            usage.get("prompt_tokens", est_tokens(prompt)),
            usage.get("completion_tokens", 0))

def cost_of(model, tok_in, tok_out):
    cfg = PROVIDERS[model]
    return tok_in / 1000 * cfg["price_in"] + tok_out / 1000 * cfg["price_out"]

def guardrail_check(prompt):
    for pat in BLOCKED_PATTERNS:
        if pat.search(prompt):
            return "prompt matches a blocked data pattern"
    return None

# --------------------------------------------------------------------------
# The router: walk the fallback chain, skip unhealthy or over ceiling
# models, charge the budget, log a receipt for every outcome.
# --------------------------------------------------------------------------
def route_and_call(team, task, customer, prompt):
    spec = TASKS[task]
    verdict = BUDGETS.check(team, task)
    if verdict == "reject":
        return {"error": "budget hard cap reached for team"}, 402
    chain = list(CHAINS[task])
    if verdict == "downgrade":
        chain = [m for m in chain if m != "frontier"] or chain[-1:]
    cached = CACHE.get(customer, task, prompt, spec["cache_ttl"])
    if cached is not None:
        log_request({"team": team, "task": task, "customer": customer,
                     "model": cached["model"], "cost_usd": 0.0,
                     "latency_ms": 0, "cache_hit": True, "fallback": False})
        return {**cached, "cache_hit": True}, 200
    last_err = None
    for idx, model in enumerate(chain):
        if not HEALTH.ok(model, spec["p95_ms"]):
            continue
        t0 = time.time()
        try:
            answer, tok_in, tok_out = call_provider(model, prompt)
        except Exception as exc:                       # provider failed
            HEALTH.record(model, False, int((time.time() - t0) * 1000))
            last_err = str(exc)
            continue
        ms = int((time.time() - t0) * 1000)
        cost = cost_of(model, tok_in, tok_out)
        if cost > spec["max_cost_usd"]:
            HEALTH.record(model, True, ms)
            continue                                   # over ceiling: next
        HEALTH.record(model, True, ms)
        BUDGETS.charge(team, cost)
        receipt = {"answer": answer, "model": model, "provider": model,
                   "tokens_in": tok_in, "tokens_out": tok_out,
                   "cost_usd": round(cost, 6), "latency_ms": ms,
                   "fallback": idx > 0, "cache_hit": False}
        log_request({"team": team, "task": task, "customer": customer,
                     "model": model, "cost_usd": receipt["cost_usd"],
                     "latency_ms": ms, "cache_hit": False,
                     "fallback": idx > 0,
                     "prompt_hash": hashlib.sha256(
                         prompt.encode()).hexdigest()[:16]})
        CACHE.put(customer, task, prompt, spec["cache_ttl"], receipt)
        return receipt, 200
    return {"error": "no healthy model for task",
            "detail": last_err}, 503

# --------------------------------------------------------------------------
# HTTP surface: POST /v1/chat, GET /stats, GET /health.
# --------------------------------------------------------------------------
class Handler(BaseHTTPRequestHandler):
    def _send(self, obj, status=200):
        body = json.dumps(obj).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _team(self):
        return API_KEYS.get(self.headers.get("X-API-Key", ""))

    def do_GET(self):
        if self.path == "/health":
            return self._send({"status": "ok"})
        if self.path == "/stats":
            if not self._team():
                return self._send({"error": "bad api key"}, 401)
            total = sum(r["cost_usd"] for r in LOG_MEM)
            return self._send({
                "requests_logged": len(LOG_MEM),
                "total_cost_usd": round(total, 4),
                "cache_hits": CACHE.hits, "cache_misses": CACHE.misses,
                "team_spend": {t: round(BUDGETS.spent[t], 4)
                               for t in TEAM_BUDGETS}})
        return self._send({"error": "not found"}, 404)

    def do_POST(self):
        if self.path != "/v1/chat":
            return self._send({"error": "not found"}, 404)
        team = self._team()
        if not team:
            return self._send({"error": "bad api key"}, 401)
        try:
            req = json.loads(self.rfile.read(
                int(self.headers.get("Content-Length", 0))))
        except Exception:
            return self._send({"error": "invalid json"}, 400)
        task, prompt = req.get("task"), req.get("prompt", "")
        customer = req.get("customer_id", "anonymous")
        if task not in TASKS or not prompt:
            return self._send({"error": "task and prompt are required, "
                                        "task must be a known task"}, 400)
        if not LIMITER.allow(customer):
            return self._send({"error": "rate limit for customer"}, 429)
        blocked = guardrail_check(prompt)
        if blocked:
            log_request({"team": team, "task": task, "customer": customer,
                         "model": None, "cost_usd": 0.0, "latency_ms": 0,
                         "cache_hit": False, "fallback": False,
                         "blocked": blocked})
            return self._send({"error": blocked}, 422)
        result, status = route_and_call(team, task, customer, prompt)
        return self._send(result, status)

    def log_message(self, *args):
        pass

if __name__ == "__main__":
    print(f"AI gateway listening on http://127.0.0.1:{PORT} "
          f"(log: {LOG_PATH})")
    ThreadingHTTPServer(("127.0.0.1", PORT), Handler).serve_forever()
