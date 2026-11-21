"""Demo client: indexes sample_data.json, then runs example searches.

Start the service first:
    uvicorn app.main:app --port 8080
Then:
    python client_demo.py
"""
import json
import urllib.request

BASE = "http://localhost:8080"


def call(method: str, path: str, payload: dict | None = None) -> dict:
    data = json.dumps(payload).encode() if payload is not None else None
    req = urllib.request.Request(
        BASE + path, data=data, method=method,
        headers={"Content-Type": "application/json"},
    )
    with urllib.request.urlopen(req, timeout=30) as resp:
        return json.loads(resp.read())


def main() -> None:
    print("health:", call("GET", "/health"))
    with open("sample_data.json", encoding="utf-8") as fh:
        payload = json.load(fh)
    results = call("POST", "/documents/bulk", payload)
    for row in results:
        print(f"indexed {row['document_id']}: {row['chunks_indexed']} chunk(s)")

    queries = [
        ("refund request within 30 days of purchase", {}),
        ("forgot password, reset link by email", {}),
        ("download invoice as PDF", {"product": "billing"}),
        ("API requests per minute limit", {}),
    ]
    for query, filters in queries:
        out = call("POST", "/search", {"query": query, "top_k": 3, "filters": filters})
        print(f"\nquery: {query!r}  ({out['took_ms']} ms)")
        for hit in out["hits"]:
            print(f"  {hit['score']:.3f}  {hit['document_id']}  {hit['title']}")


if __name__ == "__main__":
    main()
