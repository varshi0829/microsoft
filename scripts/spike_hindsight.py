"""Throwaway Hindsight spike: retain ONE incident narrative, recall it, print the raw response.

Usage: .venv/bin/python scripts/spike_hindsight.py
Env:   HINDSIGHT_BASE_URL (default http://localhost:8888), HINDSIGHT_API_KEY (optional),
       HINDSIGHT_BANK_ID (default recallops-spike)
"""
import os, sys, time, json, datetime

from hindsight_client import Hindsight

BASE_URL = os.getenv("HINDSIGHT_BASE_URL", "http://localhost:8888")
API_KEY = os.getenv("HINDSIGHT_API_KEY") or None
BANK_ID = os.getenv("HINDSIGHT_BANK_ID", "recallops-spike")

NARRATIVE = (
    "Incident INC-101 on payments-api (2026-03-12). Symptoms: latency 4.1s, error rate 16%, "
    "db cpu 90%, connections 50/50. Recent deploy v3.2.0 (25 min before). "
    "Root cause: database connection pool leak after deploy. "
    "Actions: RESTART_SERVICE failed (recovered ~4 min then recurred). "
    "ROLLBACK_DEPLOY succeeded. Resolved in 11 minutes. "
    "Lesson: restart does not help; roll back the deploy."
)
QUERY = "API latency is high and database connections are saturated right after a deployment. What worked before?"


def dump(label, obj):
    print(f"\n=== {label} ===")
    try:
        print(json.dumps(obj.model_dump(mode="json"), indent=2, default=str))
    except Exception:
        print(repr(obj))


def main():
    print(f"Hindsight base_url={BASE_URL} bank={BANK_ID} api_key={'set' if API_KEY else 'none'}")
    client = Hindsight(base_url=BASE_URL, api_key=API_KEY, timeout=120.0, max_attempts=1)
    try:
        print("server version:", client.get_version())
    except Exception as e:
        sys.exit(f"CONFIG ERROR: cannot reach Hindsight at {BASE_URL}: {type(e).__name__}: {e}")

    try:
        bank = client.create_bank(bank_id=BANK_ID, name="RecallOps spike")
        dump("create_bank", bank)
    except Exception as e:
        sys.exit(f"BANK ERROR: {type(e).__name__}: {e}")

    t0 = time.perf_counter()
    try:
        r = client.retain(
            bank_id=BANK_ID,
            content=NARRATIVE,
            context="incident post-mortem",
            timestamp=datetime.datetime(2026, 3, 12, 10, 0, tzinfo=datetime.timezone.utc),
            document_id="INC-101",
            tags=["incident", "payments-api"],
        )
    except Exception as e:
        sys.exit(f"RETAIN ERROR: {type(e).__name__}: {e}")
    retain_s = time.perf_counter() - t0
    dump("retain response", r)
    print(f"retain latency: {retain_s:.2f}s")

    t1 = time.perf_counter()
    try:
        res = client.recall(bank_id=BANK_ID, query=QUERY)
    except Exception as e:
        sys.exit(f"RECALL ERROR: {type(e).__name__}: {e}")
    recall_s = time.perf_counter() - t1
    dump("recall response (raw)", res)
    print(f"recall latency (first call, right after retain): {recall_s:.2f}s")
    print(f"results returned: {len(res.results)}; contains 'INC-101' in text: "
          f"{any('INC-101' in (x.text or '') for x in res.results)}; "
          f"document_ids: {[x.document_id for x in res.results]}")


if __name__ == "__main__":
    main()
