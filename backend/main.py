import os
from pathlib import Path
from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse
from pydantic import BaseModel
from . import agent, hs, sim

app = FastAPI(title="RecallOps")
STATIC = Path(__file__).resolve().parent / "static"


class Req(BaseModel):
    incident_id: str
    decision: str | None = None   # approve | reject
    action: str | None = None     # must equal the action the agent recommended (checked below)


_pending: dict[str, str] = {}     # incident_id -> action the agent recommended and validated


def _check(iid):
    if iid not in sim.scenarios():
        raise HTTPException(404, "unknown incident")


@app.get("/")
def index():
    return FileResponse(STATIC / "index.html")


@app.get("/api/info")
def info():
    return {"memory_backend": hs.backend_name(), "memory_status": hs.status(), "reasoner": "DEV-STUB-NOT-LLM" if agent.LLM_BACKEND == "dev-stub" else "llm",
            "scenarios": {k: {"label": v["label"], "service": v["service"]} for k, v in sim.scenarios().items()},
            "actions": sim.ACTIONS}


@app.post("/api/start")
def start(r: Req):
    _check(r.incident_id)
    _pending.pop(r.incident_id, None)
    sim.start(r.incident_id)
    return sim.public(r.incident_id)


@app.post("/api/analyze")
def analyze(r: Req):
    _check(r.incident_id)
    if sim.get(r.incident_id)["status"] != "ACTIVE":
        raise HTTPException(409, "incident is closed")
    out = agent.analyze(r.incident_id)
    _pending[r.incident_id] = out["recommendation"]["recommended_action"]
    return out


@app.post("/api/decide")
def decide(r: Req):
    _check(r.incident_id)
    iid, rec = r.incident_id, _pending.get(r.incident_id)
    if rec is None:
        raise HTTPException(409, "no recommendation awaiting a decision; analyze first")
    if r.decision == "reject":
        _pending.pop(iid)
        agent._audit({"event": "decision", "incident": iid, "decision": "rejected", "recommended": rec})
        return {"decision": "rejected"}
    if r.decision != "approve":
        raise HTTPException(400, "decision must be approve or reject")
    if r.action != rec:   # explicit approval of THIS action is required
        raise HTTPException(400, f"approval must name the recommended action ({rec})")
    _pending.pop(iid)
    outcome = sim.execute(iid, rec)          # the ONLY place actions run (simulated, allowlisted)
    agent._audit({"event": "decision", "incident": iid, "decision": "approved", "executed": rec, "result": outcome["result"]})
    closed = outcome["status"] != "ACTIVE" or len(sim.get(iid)["actions_taken"]) >= 3
    retained = agent.close_and_retain(iid) if closed else None
    return {"decision": "approved", "outcome": outcome, "closed": closed, "retained": retained,
            "actions_taken": sim.get(iid)["actions_taken"]}
