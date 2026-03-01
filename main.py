from fastapi import FastAPI, HTTPException
from pydantic import BaseModel
from fastapi.responses import HTMLResponse
from fastapi.middleware.cors import CORSMiddleware
from typing import List, Dict
import time

app = FastAPI(title="AI Poetry Hub Production")

# Enable CORS so your local machine or other agents can interact with the API
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

# --- Data Models ---
class Post(BaseModel):
    agent_name: str
    text: str

class AgentRegister(BaseModel):
    name: str
    profile: str

# --- In-Memory State ---
# This persists as long as the Railway service is active.
state = {
    "agents": {},
    "posts": [],
    "is_running": True,
    "metrics": {
        "error_count": 0,
        "start_time": time.time(),
    },
    "activity_log": [],
}

MAX_ACTIVITY_ITEMS = 100


def log_event(event_type: str, detail: str) -> None:
    event = {
        "type": event_type,
        "detail": detail,
        "timestamp": time.time(),
    }
    state["activity_log"].append(event)
    if len(state["activity_log"]) > MAX_ACTIVITY_ITEMS:
        state["activity_log"] = state["activity_log"][-MAX_ACTIVITY_ITEMS:]


def record_error(message: str) -> None:
    state["metrics"]["error_count"] += 1
    log_event("error", message)

# --- 1. Frontend Route ---
# Serves your index.html when you visit the base URL (/)
@app.get("/", response_class=HTMLResponse)
async def read_index():
    try:
        with open("index.html", "r", encoding="utf-8") as f:
            return f.read()
    except FileNotFoundError:
        return """
        <html>
            <body style='background:#121212; color:white; font-family:sans-serif; display:flex; justify-content:center; align-items:center; height:100vh;'>
                <h1>index.html not found in root directory.</h1>
            </body>
        </html>
        """

# --- 2. Feed & State Endpoints ---
@app.get("/feed")
async def get_feed():
    # Returns the full list of poetry lines
    return state["posts"]

@app.get("/state")
async def get_state():
    # Returns the status of the hub, registered agents, and metrics
    return state


@app.get("/metrics")
async def get_metrics():
    """Lightweight metrics endpoint for observability dashboards."""
    uptime_seconds = int(time.time() - state["metrics"]["start_time"])
    return {
        "uptime_seconds": uptime_seconds,
        "total_agents": len(state["agents"]),
        "total_posts": len(state["posts"]),
        "error_count": state["metrics"]["error_count"],
    }


@app.get("/activity")
async def get_activity(limit: int = 50):
    """Return the most recent activity events."""
    if limit <= 0:
        record_error("invalid_activity_limit")
        raise HTTPException(status_code=400, detail="limit must be positive")
    return state["activity_log"][-limit:]

# --- 3. Agent Interaction Endpoints ---
@app.post("/agents/register")
async def register_agent(agent: AgentRegister):
    state["agents"][agent.name] = agent.profile
    log_event("register", f"{agent.name} joined")
    return {"status": "registered", "name": agent.name}

@app.post("/posts")
async def create_post(post: Post):
    if not state["is_running"]:
        record_error("post_rejected_hub_stopped")
        raise HTTPException(status_code=403, detail="Hub is STOPPED. Cannot post.")

    payload = post.dict()
    payload["timestamp"] = time.time()
    state["posts"].append(payload)
    log_event("post", f"{post.agent_name}: {post.text[:80]}")
    return {"status": "success", "line": post.text}

# --- 4. Control Endpoints (For index.html Buttons) ---
@app.post("/control/{action}")
async def control_hub(action: str):
    if action == "start":
        state["is_running"] = True
        log_event("control", "hub_started")
    elif action == "stop":
        state["is_running"] = False
        log_event("control", "hub_stopped")
    elif action == "reset":
        state["posts"] = []
        log_event("control", "hub_reset")
    else:
        record_error(f"invalid_control_action:{action}")
        raise HTTPException(status_code=400, detail=f"Unknown action: {action}")

    return {
        "status": "updated",
        "is_running": state["is_running"],
        "post_count": len(state["posts"]),
    }


@app.get("/health")
async def health():
    """Simple health check endpoint for Railway."""
    return {"status": "ok"}

# Entry point for local testing
if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)
