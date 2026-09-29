# RecallOps — outcome-aware incident-response memory

RecallOps is an incident-response agent prototype that remembers **what was tried, what worked and what failed** in past incidents, and uses that history to recommend the next remediation.

> **Status at submission**
>
> | | Status |
> |---|---|
> | Application (agent, simulator, approval gate, one-page UI) | **IMPLEMENTED** |
> | Real Hindsight (local slim server): `retain`, `recall`, document-ID recovery, immediate retain→recall | **LIVE-VERIFIED** |
> | Groq `openai/gpt-oss-120b` as the agent's reasoning backend | **LIVE-VERIFIED** |
> | Two-incident learning loop on real Hindsight + real Groq (see [Real validation](#real-validation)) | **LIVE-VERIFIED**, one historical incident and one live loop |
> | Hindsight Cloud | **Not used for the validation.** Its `retain` endpoint returned `402 Insufficient credits`, so the working validation used a local Hindsight server. |
> | Full 10-incident seed on real Hindsight | **Not completed**, blocked by Groq rate limits |
> | No-memory baseline / statistical evaluation | **Not run** |
>
> The development backends (`MEMORY_BACKEND=dev`, `LLM_BACKEND=dev-stub`) are a keyword store that is **NOT Hindsight** and a deterministic stub that is **NOT an LLM**. They exist for rehearsal only, and anything run on them proves nothing about Hindsight or a model.

## The problem

Production incidents recur, but the knowledge of *which fix worked, and which fix failed*, lives in old tickets and in people's heads. A responder facing a SEV-1 often re-tries fixes that already failed last time.

## The core loop

```text
incident → investigation → memory recall → reasoning → recommendation
        → human approval → simulated action → outcome
        → memory retention → future recommendation
```

The differentiator is **outcome-aware memory**: the memory stores each incident together with every action tried and its result (SUCCESS / PARTIAL / FAILED), including failed remediation attempts. A later, similar incident is then advised with "restart failed here before; rollback fixed it" rather than a generic checklist.

Demo story (one incident family: API latency / database connection pool / deployment regression):

1. **Incident A (INC-201)** is ambiguous. Same-service history points to a pool increase, other services' history points to rollback. The first recommendation is a pool increase, which only partially helps. After re-analysis, rollback resolves it. The outcome is retained.
2. **Incident A′ (INC-202)** recurs. Recall now includes INC-201, its partial pool-increase result is surfaced, and rollback is recommended first.
3. **Incident B (INC-203)** has a recent deploy but normal connections and very high DB CPU. The recommendation is a query fix, not a rollback, so memory does not blindly pattern-match.

## Architecture

```text
Browser (one static page)
   │
FastAPI  backend/main.py
   ├─ sim.py    hidden root cause + 3 mock investigation tools + state-dependent outcomes
   ├─ agent.py  investigate → recall → evidence → one reasoner call → validation
   ├─ hs.py     memory adapter: retain(incident_id, text, tags) / recall(query)
   └─ data/     history.json, scenarios.json, live_incidents.json (runtime), audit.jsonl (runtime)
        │                    │
   Groq LLM             Hindsight (persistent memory; validated on a local slim server)
```

- **Hindsight (persistent memory layer).** Each closed incident is retained as a natural-language narrative (incident ID, service, symptoms, deploy, root cause, actions in order with results, lesson) using `document_id = incident ID`. Recall returns memories for a natural-language query built from the current incident and investigation. `backend/hs.py` is the only file that talks to Hindsight, through the official `hindsight_client`. Retain, recall and document-ID recovery were verified against a real local Hindsight server (client 0.10.2). Hindsight splits each narrative into atomic facts, and every recalled fact carries `document_id = INC-xxx`.
- **Groq (reasoning LLM).** One structured-JSON call per analysis (default `openai/gpt-oss-120b`, OpenAI-compatible endpoint). The model receives the current incident, the investigation results, the recalled past incidents with their action outcomes, and what has already been tried in this incident. It must return one action from the allowlist. No confidence percentages are produced or shown. The UI shows **evidence strength** derived from counts instead.
- **How recalled outcomes reach the reasoner (implementation detail to be aware of).** Hindsight decides *which* past incident IDs come back. The structured action outcomes for those IDs are read from local ground-truth files (`data/history.json`, `data/live_incidents.json`) by ID. If recall does not return the incident ID (via `document_id` or in the text), that incident is not counted. In the real validation, recall returned the ID through `document_id`.
- **Human approval and allowlist.** Actions are an enum: `RESTART_SERVICE`, `ROLLBACK_DEPLOY`, `INCREASE_POOL_SIZE`, `FIX_SLOW_QUERY`, `CLEAR_CACHE`, `ESCALATE`. The model's action is validated against it (and rejected if it repeats an action that already failed in this incident). Nothing executes until the human clicks Approve, and the server rejects approval of any action other than the one recommended. Every action is **simulated**. Nothing touches real infrastructure and there is no shell execution.
- **State-dependent simulator (`backend/sim.py`).** Each scenario has a hidden root cause, and the outcome depends only on (root cause, action):

  | Action | R1 pool leak after deploy | R2 traffic surge | R3 slow query |
  |---|---|---|---|
  | ROLLBACK_DEPLOY | SUCCESS | FAILED | FAILED |
  | INCREASE_POOL_SIZE | PARTIAL (leak refills the pool) | SUCCESS | FAILED |
  | FIX_SLOW_QUERY | FAILED | FAILED | SUCCESS |
  | RESTART_SERVICE / CLEAR_CACHE | FAILED | FAILED | FAILED |

  The agent never sees the root cause. It only sees the three mock tools (`get_recent_deploy`, `get_metric`, `get_connection_count`). R2 exists in the matrix and the history but has no live demo scenario.

## Setup

```bash
uv venv .venv && uv pip install --python .venv/bin/python -r requirements.txt   # hindsight-client, fastapi, uvicorn
```

### Real configuration (local Hindsight + Groq: the validated setup)

The app reads environment variables only. It does **not** read `.env` by itself, so load it into the shell (`.env` is gitignored):

```bash
cp .env.example .env      # fill in values
set -a; source .env; set +a
```

| Variable | Meaning |
|---|---|
| `HINDSIGHT_BASE_URL` | `http://127.0.0.1:8888` for local (or a Hindsight Cloud URL) |
| `HINDSIGHT_API_KEY` | empty for local; the key for Cloud |
| `HINDSIGHT_BANK_ID` | memory bank; use a **fresh** bank per run (a bank cannot be reset) |
| `LLM_PROVIDER` | `groq` (or `openai`) |
| `LLM_API_KEY` | key for that provider |
| `LLM_MODEL` | optional, default `openai/gpt-oss-120b` on Groq |

**Local Hindsight server** (slim install, no torch; Groq does Hindsight's fact extraction). After `uv pip install 'hindsight-api-slim[embedded-db,local-onnx]'` into the venv:

```bash
HINDSIGHT_API_LLM_PROVIDER=groq HINDSIGHT_API_LLM_API_KEY="$LLM_API_KEY" \
HINDSIGHT_API_LLM_GROQ_SERVICE_TIER=on_demand \
HINDSIGHT_API_EMBEDDINGS_PROVIDER=onnx \
HINDSIGHT_API_EMBEDDINGS_ONNX_MODEL_ID=sentence-transformers/all-MiniLM-L6-v2 \
HINDSIGHT_API_EMBEDDINGS_ONNX_POOLING=mean \
HINDSIGHT_API_EMBEDDINGS_ONNX_QUERY_PREFIX= HINDSIGHT_API_EMBEDDINGS_ONNX_PASSAGE_PREFIX= \
HINDSIGHT_API_RERANKER_PROVIDER=rrf \
.venv/bin/hindsight-api --host 127.0.0.1 --port 8888
```

`service_tier=on_demand` was needed because Hindsight's default (`auto`) is rejected by this Groq org. On the Groq on-demand tier `openai/gpt-oss-120b` allows 8,000 tokens per minute, and each Hindsight retain uses roughly 4–6k, so **retains and analyses must be spaced about a minute apart** (the validated run waited 65 seconds between steps).

Then, in another shell (with `HINDSIGHT_BASE_URL`, `HINDSIGHT_BANK_ID` and the LLM variables set):

```bash
.venv/bin/python scripts/spike_hindsight.py    # one retain -> recall, prints the raw response and latency
.venv/bin/uvicorn backend.main:app --port 8000 # open http://localhost:8000
```

`scripts/seed.py` (10 incidents) and `scripts/prove_learning.py` also work against real backends, but at the Groq rate limit above the 10-incident seed takes many minutes and **was not completed**. The demo does not need it.

The page banner shows Hindsight as **VERIFIED** only after a real retain *and* a real recall have both succeeded in that server process. Otherwise it shows CONFIGURED/UNVERIFIED, PARTIALLY VERIFIED or UNAVAILABLE. If Hindsight is unreachable, the agent degrades to no-memory mode with a warning.

### Development rehearsal (NOT Hindsight, NOT an LLM)

```bash
export MEMORY_BACKEND=dev LLM_BACKEND=dev-stub
.venv/bin/python scripts/seed.py --reset
.venv/bin/python scripts/prove_learning.py       # acceptance test on the dev backends
.venv/bin/uvicorn backend.main:app --port 8000   # open http://localhost:8000
```

- `MEMORY_BACKEND=dev` is a **local keyword-overlap store** (`data/dev_memory.json`). It is **not Hindsight**: it has no extraction, no entity/graph/temporal retrieval and no relevance ranking (it returns every stored incident with any word overlap). It is only for developing the UI and flow when Hindsight is unavailable. It is never selected automatically.
- `LLM_BACKEND=dev-stub` is a **deterministic weighted vote** over recalled outcomes written for reproducible rehearsals. It is **not an LLM and not AI reasoning**. Its weights were chosen so the demo story is reproducible, so its behavior says nothing about how a real model would reason. With a real model, the first recommendation on INC-201 may differ from the scripted story.
- The UI shows red banners ("DEV FALLBACK — NOT HINDSIGHT", "DEV-STUB-NOT-LLM") whenever either is active. **Do not present a recording made with these banners as a Hindsight or LLM demo.**

`scripts/seed.py --reset` on the dev store clears it. On real Hindsight it cannot delete memories, so set a new `HINDSIGHT_BANK_ID` for a clean take. Approving incident A′ during a rehearsal retains INC-202 and would change the next take.

## 90-second demo flow

Practice on the dev rehearsal backends if you like, but present it on real Hindsight + Groq, and point at the banners first. With Groq's rate limit, pause about a minute between steps that call the model or retain memory.

1. Open `http://localhost:8000`, show the banners, and click **Incident A · INC-201** (it analyzes automatically).
2. Walk down the page: investigation evidence (connections 50/50, deploy 28 min ago), recalled memory (worked before / failed before), and the recommendation with its avoid list.
3. Click **Approve**. The outcome is PARTIAL: latency improves briefly, but connections are back at 100/100.
4. Click **Re-analyze**, then **Approve** the new recommendation. The outcome is SUCCESS, the incident closes, and the "Memory updated" panel shows the retention.
5. Click **Incident A′ · INC-202**. Show the "Learned earlier: INC-201" banner and the changed first recommendation, with the earlier partial fix in the avoid list.
6. Click **Incident B · INC-203**. The recommendation is a query fix, not a rollback.

## Real validation

Run on **real local Hindsight (slim server) + real Groq `openai/gpt-oss-120b`**. No dev fallback and no stub. Bank: `recallops-real-demo` (fresh). The run drove the app's HTTP API with explicit approvals through the approval gate. A throwaway script did the driving and is not in the repo. The browser UI was not used for this run.

```text
historical INC-113 (checkout-api: CLEAR_CACHE failed, INCREASE_POOL_SIZE succeeded), retained in Hindsight
  → INC-201: recall returns INC-113; Groq recommends INCREASE_POOL_SIZE
  → approved → simulator: PARTIAL
  → re-analysis: Groq recommends ROLLBACK_DEPLOY → approved → simulator: SUCCESS
  → INC-201 outcome retained in real Hindsight
  → INC-202: recall returns INC-201 and INC-113
  → Groq recommends ROLLBACK_DEPLOY first, citing INC-201 and noting INCREASE_POOL_SIZE gave only partial relief
    (INCREASE_POOL_SIZE and CLEAR_CACHE appear in the avoid list)
```

What this shows: retain, recall, document-ID recovery and an immediately recallable new outcome work on real Hindsight, and the reasoner received INC-201's outcome and changed its recommendation accordingly. The run took about six minutes because of the roughly 65-second pauses needed to stay under Groq's rate limit.

What this does **not** show: it is a demonstration of the mechanism, not statistical reliability. It used **one historical incident and one live learning loop**. **No no-memory baseline was run**, so there is no evidence of a causal benefit over an agent without memory. No latency, accuracy or confidence figures are claimed.

## What is and is not verified

| Item | Status |
|---|---|
| Simulator with hidden state and state-dependent outcomes | IMPLEMENTED (local tests) |
| Approval gate (no execution before approval; approval must name the recommended action) | IMPLEMENTED (local API tests; used in the real run) |
| Allowlist validation, escalate-on-failure | IMPLEMENTED (local tests) |
| One-page UI | IMPLEMENTED (headless Chrome, **dev backends only**; not run against real backends) |
| Real Hindsight retain / recall / document-ID recovery / immediate recall (local slim server) | LIVE-VERIFIED |
| Groq `openai/gpt-oss-120b` as the agent backend | LIVE-VERIFIED |
| Two-incident learning loop, real Hindsight + real Groq | LIVE-VERIFIED (one historical incident, one loop) |
| Hindsight Cloud retain | NOT USED: `402 Insufficient credits` |
| 10-incident seed on real Hindsight | NOT COMPLETED (Groq rate limit) |
| INC-203 distractor and the full A → A′ → B story on real backends | NOT LIVE-VERIFIED |
| No-memory baseline, benchmarks, reliability | NOT RUN |

## Limitations

- The real validation is small: one historical incident, one learning loop, no baseline.
- Groq's on-demand limit (8,000 tokens per minute) forces roughly one-minute gaps between retains and analyses, so a live demo has pauses, and the 10-incident seed was not completed.
- Hindsight Cloud was not used, because its retain endpoint required paid credits. The validated setup is a local slim Hindsight server whose data and model cache live in `/tmp`.
- Historical data is **10 synthetic incidents** and the demo scenarios were authored for this story. Only INC-113 was actually retained in the real validation.
- All remediation is **simulated**, and only one incident family is supported.
- Recalled outcomes reach the reasoner through local ground-truth files joined by incident ID (see Architecture). Hindsight decides which incidents come back.
- "Outcome-aware persistent memory" describes what is implemented: outcomes are retained and can change later recommendations. Nothing aggregates outcomes, and no Hindsight reflection or consolidation feature is used.
- Nothing is authenticated. "Approval" is an API call. The page's "Hero story shortcut" button approves automatically and exists only to reproduce the flow quickly.
- Retaining the same incident ID more than once may create duplicates on real Hindsight (a repeat of identical content returned instantly in one test, but this was not investigated).
- The dev backends must never be presented as Hindsight or an LLM. The UI labels them in red when active.

## Layout

```text
backend/  main.py hs.py agent.py sim.py static/index.html
data/     history.json scenarios.json
scripts/  spike_hindsight.py seed.py prove_learning.py
```
