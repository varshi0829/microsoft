"""Retain the 10 historical incidents. --reset clears live outcomes (and the DEV store if MEMORY_BACKEND=dev).
Usage: [MEMORY_BACKEND=dev] .venv/bin/python scripts/seed.py [--reset]"""
import sys, json, time
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from backend import agent, hs

print("memory backend:", hs.backend_name())
if hs.backend_name() != "hindsight":
    print("*** DEV-FALLBACK-NOT-HINDSIGHT: development only, this is NOT Hindsight ***")
if "--reset" in sys.argv:
    agent.LIVE.unlink(missing_ok=True)
    if hs.backend_name() != "hindsight":
        hs.DEV_FILE.unlink(missing_ok=True)
    else:
        print("note: cannot delete from Hindsight; set a fresh HINDSIGHT_BANK_ID for a clean run")
for r in json.loads((agent.DATA / "history.json").read_text()):
    t = time.perf_counter()
    hs.retain(r["id"], agent.narrative(r), tags=["incident", r["service"]])
    print(f"retained {r['id']} ({time.perf_counter()-t:.2f}s)")
