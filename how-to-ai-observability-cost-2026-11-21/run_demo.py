"""CLI demo: load sample events, show cost, aggregates and alerts."""
import json
from observability import SAMPLE_EVENTS, Collector, check_budgets

def main():
    collector = Collector()
    for event in SAMPLE_EVENTS:
        collector.record(event)
    print(f"Events recorded: {len(collector.events)}")
    print(f"Total cost USD: {collector.total_cost():.4f}")
    print(f"Error rate: {collector.error_rate():.2%}")
    print(f"p95 latency ms: {collector.p95_latency_ms()}")
    print()
    print("By model:")
    print(json.dumps(collector.aggregate("model"), indent=2))
    print("By feature:")
    print(json.dumps(collector.aggregate("feature"), indent=2))
    print("Budget alerts (monthly limits in USD):")
    budgets = {"receipt_extract": 0.01, "support_chat": 0.05, "doc_summary": 0.02}
    for alert in check_budgets(collector, budgets):
        print(f"  {alert['feature']}: spent ${alert['spent_usd']:.4f} of ${alert['budget_usd']} "
              f"({alert['percent']} percent) level={alert['level']}")

if __name__ == "__main__":
    main()
