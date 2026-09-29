"""Memory adapter. The agent only ever calls retain() and recall().

Backends (chosen explicitly by MEMORY_BACKEND, never silently):
  hindsight (default)  real Hindsight via the official `hindsight_client`.
                       Signatures verified against hindsight-client 0.10.2; runtime behavior
                       (recall ranking, tag filters, retain->recall latency) NOT yet verified
                       because no Hindsight endpoint/credits were available (see scripts/spike_hindsight.py).
  dev                  DEVELOPMENT-ONLY keyword-overlap store. NOT Hindsight. Every memory it
                       returns has source="DEV-FALLBACK-NOT-HINDSIGHT". Never use it for the
                       submitted demo or for any claim about Hindsight.
If the real backend is unreachable, MemoryUnavailable is raised and the caller degrades to
no-memory mode (it does NOT fall back to the dev store).
"""
import json, os, re, datetime
from dataclasses import dataclass, field
from pathlib import Path

BACKEND = os.getenv("MEMORY_BACKEND", "hindsight").lower()
BANK_ID = os.getenv("HINDSIGHT_BANK_ID", "recallops")
BASE_URL = os.getenv("HINDSIGHT_BASE_URL", "http://localhost:8888")
API_KEY = os.getenv("HINDSIGHT_API_KEY") or None
DEV_FILE = Path(__file__).resolve().parent.parent / "data" / "dev_memory.json"


class MemoryUnavailable(Exception):
    pass


@dataclass
class Memory:
    text: str
    document_id: str | None = None   # we retain each incident with document_id = "INC-xxx"
    tags: list[str] = field(default_factory=list)
    source: str = "hindsight"        # "DEV-FALLBACK-NOT-HINDSIGHT" for the dev store


# Real-Hindsight health, updated only by real retain/recall calls in THIS process.
_ops = {"retain_ok": False, "recall_ok": False, "last_error": None}


def status() -> dict:
    """state: dev | unverified | partial | verified | unavailable (never 'healthy' from configuration alone)."""
    if BACKEND != "hindsight":
        return {"state": "dev", "detail": "development fallback, NOT Hindsight"}
    if _ops["last_error"]:
        return {"state": "unavailable", "detail": _ops["last_error"][:140]}
    if _ops["retain_ok"] and _ops["recall_ok"]:
        return {"state": "verified", "detail": "real retain and recall both succeeded in this process"}
    if _ops["retain_ok"] or _ops["recall_ok"]:
        done = "recall" if _ops["recall_ok"] else "retain"
        return {"state": "partial", "detail": f"{done} succeeded; the other operation not yet exercised"}
    return {"state": "unverified", "detail": f"configured ({BASE_URL}); no real retain/recall completed yet"}


def backend_name() -> str:
    return "hindsight" if BACKEND == "hindsight" else "DEV-FALLBACK-NOT-HINDSIGHT"


# ---------------- real Hindsight ----------------
_client = None

def _hs():
    global _client
    if _client is None:
        from hindsight_client import Hindsight
        _client = Hindsight(base_url=BASE_URL, api_key=API_KEY, timeout=60.0, max_attempts=1)
        try:
            _client.create_bank(bank_id=BANK_ID, name="RecallOps")
        except Exception:
            pass  # bank may already exist; a real failure surfaces on retain/recall
    return _client


def _hs_retain(text, incident_id, tags, when):
    try:
        _hs().retain(bank_id=BANK_ID, content=text, document_id=incident_id, tags=tags or None,
                     timestamp=when, context="incident post-mortem")
        _ops.update(retain_ok=True, last_error=None)
    except Exception as e:
        _ops["last_error"] = f"retain: {type(e).__name__}: {e}"
        raise MemoryUnavailable(f"{type(e).__name__}: {e}") from e


def _hs_recall(query, limit):
    try:
        res = _hs().recall(bank_id=BANK_ID, query=query)
        _ops.update(recall_ok=True, last_error=None)
    except Exception as e:
        _ops["last_error"] = f"recall: {type(e).__name__}: {e}"
        raise MemoryUnavailable(f"{type(e).__name__}: {e}") from e
    return [Memory(text=r.text, document_id=r.document_id, tags=list(r.tags or []))
            for r in res.results[:limit]]


# ---------------- DEV-ONLY fallback (NOT Hindsight) ----------------
def _tok(s):
    return set(re.findall(r"[a-z0-9\-\.]+", s.lower()))


def _dev_load():
    return json.loads(DEV_FILE.read_text()) if DEV_FILE.exists() else []


def _dev_retain(text, incident_id, tags, when):
    rows = [r for r in _dev_load() if r["document_id"] != incident_id]  # same id = update
    rows.append({"text": text, "document_id": incident_id, "tags": tags or []})
    DEV_FILE.write_text(json.dumps(rows, indent=1))


def _dev_recall(query, limit):
    q = _tok(query)
    scored = sorted(((len(q & _tok(r["text"])), r) for r in _dev_load()), key=lambda x: -x[0])
    return [Memory(text=r["text"], document_id=r["document_id"], tags=r["tags"],
                   source="DEV-FALLBACK-NOT-HINDSIGHT") for n, r in scored[:limit] if n > 0]


# ---------------- public interface ----------------
def retain(incident_id: str, text: str, tags: list[str] | None = None,
           when: datetime.datetime | None = None) -> None:
    (_hs_retain if BACKEND == "hindsight" else _dev_retain)(text, incident_id, tags, when)


def recall(query: str, limit: int = 8) -> list[Memory]:
    return (_hs_recall if BACKEND == "hindsight" else _dev_recall)(query, limit)
