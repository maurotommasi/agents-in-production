# How To: AI Observability and Cost Tracking for LLM Applications

Complete runnable Python, standard library only, no installation needed. Python 3.10 or newer.

## Run
```
python3 run_demo.py
python3 observability.py
```

## Files
- `observability.py` defines the telemetry event, the price table, cost calculation, the collector, aggregation by model, feature and user, error rate, p95 latency and budget alert checks.
- `run_demo.py` loads eight sample events and prints total cost, aggregates and budget alerts.

## Design notes
One event per LLM call is the core rule. Price every event at write time from a versioned price table, aggregate from events, and alert on budget use at 80 percent and 100 percent. Cached calls cost zero in this model and are recorded so cache savings stay visible.
