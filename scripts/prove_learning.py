"""End-to-end acceptance test (no UI): seed -> INC-202 BEFORE learning -> run INC-201 (analyze/approve/execute/retain)
-> INC-202 AFTER learning -> INC-203 distractor. Calls the same functions the API uses.
Usage: [MEMORY_BACKEND=dev LLM_BACKEND=dev-stub] .venv/bin/python scripts/prove_learning.py"""
import sys, subprocess
from pathlib import Path
ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
subprocess.run([sys.executable, str(ROOT / "scripts/seed.py"), "--reset"], check=True, stdout=subprocess.DEVNULL)
from backend import agent, hs, sim

print(f"memory backend: {hs.backend_name()}   reasoner backend: {agent.LLM_BACKEND}")
if hs.backend_name() != "hindsight" or agent.LLM_BACKEND == "dev-stub":
    print("*** DEV-FALLBACK-NOT-HINDSIGHT / DEV-STUB: this run does NOT demonstrate Hindsight or an LLM ***")

def show(tag, iid):
    sim.start(iid)
    out = agent.analyze(iid)
    rec, ev = out["recommendation"], out["memory"]
    print(f"\n[{tag}] {iid}: recommend {rec['recommended_action']}  ({rec['reasoner']})")
    print("  recalled:", [r["id"] for r in ev["records"]], "| warning:", ev["warning"])
    print("  avoid:", [a["action"] for a in rec["actions_to_avoid"]])
    print("  lessons:", rec["historical_lessons"][:4])
    return out

x = show("BEFORE learning", "INC-202")
print("\n--- run INC-201 end to end ---")
sim.start("INC-201")
for step in range(3):
    out = agent.analyze("INC-201")
    act = out["recommendation"]["recommended_action"]
    o = sim.execute("INC-201", act)      # (the API requires explicit approval; this script plays the approving human)
    print(f"  step {step+1}: recommended {act} -> {o['result']} ({o['message']})")
    if o["status"] != "ACTIVE":
        break
print("  retained:", agent.close_and_retain("INC-201")["retained_text"][:200], "...")
y = show("AFTER learning", "INC-202")
z = show("DISTRACTOR", "INC-203")

ok_change = y["recommendation"]["recommended_action"] != x["recommendation"]["recommended_action"]
ok_cites = "INC-201" in [r["id"] for r in y["memory"]["records"]]
ok_b = z["recommendation"]["recommended_action"] == "FIX_SLOW_QUERY"
print(f"\nRESULT  recommendation changed after INC-201: {ok_change} | INC-202 recalled INC-201: {ok_cites} | INC-203 -> FIX_SLOW_QUERY: {ok_b}")
sys.exit(0 if (ok_change and ok_cites and ok_b) else 1)
