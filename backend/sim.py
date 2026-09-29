"""Simulator: hidden root cause + mock investigation tools + state-dependent action outcomes.
The agent never sees `root_cause`. Outcomes depend ONLY on (root_cause, action), never on what the agent recommended."""
import copy, json
from pathlib import Path

DATA = Path(__file__).resolve().parent.parent / "data"
ACTIONS = ["RESTART_SERVICE", "ROLLBACK_DEPLOY", "INCREASE_POOL_SIZE", "FIX_SLOW_QUERY", "CLEAR_CACHE", "ESCALATE"]

# everything not listed is FAILED
OUTCOME = {
    "R1_POOL_LEAK_AFTER_DEPLOY": {"ROLLBACK_DEPLOY": "SUCCESS", "INCREASE_POOL_SIZE": "PARTIAL"},
    "R2_TRAFFIC_SURGE": {"INCREASE_POOL_SIZE": "SUCCESS"},
    "R3_SLOW_QUERY": {"FIX_SLOW_QUERY": "SUCCESS"},
}
_STATES: dict[str, dict] = {}


def scenarios():
    return json.loads((DATA / "scenarios.json").read_text())


def start(iid):
    s = copy.deepcopy(scenarios()[iid])
    s.update(id=iid, status="ACTIVE", actions_taken=[])
    _STATES[iid] = s
    return s


def get(iid):
    return _STATES.get(iid) or start(iid)


def public(iid):
    s = get(iid)
    hidden = {"root_cause"}
    return {k: v for k, v in s.items() if k not in hidden}


# ---- the three mock investigation tools (deterministic; read current state) ----
def get_recent_deploy(iid):
    return get(iid)["deploy"]

def get_metric(iid, name):
    return get(iid)[name]  # latency_ms | error_rate | db_cpu | rps_vs_baseline

def get_connection_count(iid):
    s = get(iid)
    return {"used": s["conn_used"], "pool_max": s["pool_max"]}


def _metrics(s):
    return {"latency_ms": s["latency_ms"], "error_rate": s["error_rate"], "db_cpu": s["db_cpu"],
            "conn_used": s["conn_used"], "pool_max": s["pool_max"]}


def execute(iid, action):
    s = get(iid)
    assert action in ACTIONS, f"action {action} not allowlisted"
    assert s["status"] == "ACTIVE", "incident already closed"
    before = _metrics(s)
    if action == "ESCALATE":
        s["status"] = "ESCALATED"
        result, msg = "ESCALATED", "Escalated to SRE lead; no automated change made."
    else:
        result = OUTCOME[s["root_cause"]].get(action, "FAILED")
        if result == "SUCCESS":
            if action == "INCREASE_POOL_SIZE":
                s["pool_max"] *= 2
            s.update(latency_ms=1100, error_rate=1.4, db_cpu=45, conn_used=int(s["pool_max"] * 0.4), status="RESOLVED")
            msg = "Metrics returned to normal."
        elif result == "PARTIAL":  # pool doubled, leak refills it
            s["pool_max"] *= 2
            s.update(latency_ms=2600, error_rate=7.0, db_cpu=70, conn_used=s["pool_max"])
            msg = "Brief relief, then the leaking connections refilled the larger pool."
        else:
            msg = "No meaningful change." if action != "RESTART_SERVICE" else "Recovered ~2 min, then symptoms returned."
    s["actions_taken"].append({"action": action, "result": result})
    return {"action": action, "result": result, "message": msg, "before": before, "after": _metrics(s), "status": s["status"]}
