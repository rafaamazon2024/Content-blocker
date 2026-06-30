"""Admin API — manage blocklist, view logs, request timed unlock."""
import os
from datetime import datetime, timedelta, timezone
from typing import Optional

from fastapi import FastAPI, HTTPException, Security
from fastapi.middleware.cors import CORSMiddleware
from fastapi.security.api_key import APIKeyHeader
from pydantic import BaseModel, field_validator
import db
from dotenv import load_dotenv

load_dotenv()

ADMIN_TOKEN        = os.getenv("ADMIN_TOKEN", "change-me")
UNLOCK_DELAY_HOURS = int(os.getenv("UNLOCK_DELAY_HOURS", "48"))
PH                 = "%s" if os.getenv("DATABASE_URL") else "?"

api_key_header = APIKeyHeader(name="X-Admin-Token", auto_error=True)

app = FastAPI(title="Content Blocker", docs_url=None, redoc_url=None)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.on_event("startup")
def startup():
    db.init_db()


def require_auth(token: str = Security(api_key_header)):
    if token != ADMIN_TOKEN:
        raise HTTPException(status_code=401, detail="Unauthorized")


# ── Health ────────────────────────────────────────────────────────────────────

@app.get("/")
def health():
    return {"status": "ok", "service": "content-blocker"}


# ── Stats ─────────────────────────────────────────────────────────────────────

@app.get("/stats")
def stats(_=Security(require_auth)):
    if os.getenv("DATABASE_URL"):
        interval_sql  = "ts > NOW() - INTERVAL '1 day'"
        blocked_where = "blocked = TRUE"
    else:
        interval_sql  = "ts > datetime('now', '-1 day')"
        blocked_where = "blocked = 1"

    total       = db.fetchone("SELECT COUNT(*) AS n FROM blocklist")
    today_total = db.fetchone(f"SELECT COUNT(*) AS n FROM query_logs WHERE {interval_sql}")
    today_block = db.fetchone(f"SELECT COUNT(*) AS n FROM query_logs WHERE {interval_sql} AND {blocked_where}")

    return {
        "blocklist_size":  total["n"]       if total       else 0,
        "queries_today":   today_total["n"] if today_total else 0,
        "blocked_today":   today_block["n"] if today_block else 0,
    }


# ── Blocklist ─────────────────────────────────────────────────────────────────

@app.get("/blocklist")
def list_blocklist(limit: int = 100, offset: int = 0, _=Security(require_auth)):
    limit  = min(max(limit,  1), 1000)
    offset = max(offset, 0)
    return db.fetchall(
        f"SELECT domain, category, source, created_at FROM blocklist "
        f"ORDER BY created_at DESC LIMIT {PH} OFFSET {PH}",
        (limit, offset),
    )


class DomainIn(BaseModel):
    domain:   str
    category: str = "adult"

    @field_validator("domain")
    @classmethod
    def clean(cls, v: str) -> str:
        return v.lower().strip().strip(".")


@app.post("/blocklist", status_code=201)
def add_domain(body: DomainIn, _=Security(require_auth)):
    try:
        if os.getenv("DATABASE_URL"):
            sql = f"INSERT INTO blocklist (domain, category, source) VALUES ({PH},{PH},'manual') ON CONFLICT (domain) DO NOTHING"
        else:
            sql = f"INSERT OR IGNORE INTO blocklist (domain, category, source) VALUES ({PH},{PH},'manual')"
        db.execute(sql, (body.domain, body.category))
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
    return {"added": body.domain}


@app.delete("/blocklist/{domain}")
def remove_domain(domain: str, _=Security(require_auth)):
    domain = domain.lower().strip(".")
    db.execute(f"DELETE FROM blocklist WHERE domain={PH}", (domain,))
    return {"removed": domain}


# ── Logs ──────────────────────────────────────────────────────────────────────

@app.get("/logs")
def get_logs(limit: int = 100, blocked_only: bool = False, _=Security(require_auth)):
    limit = min(max(limit, 1), 1000)
    if blocked_only:
        where = f"WHERE blocked={'TRUE' if os.getenv('DATABASE_URL') else '1'}"
    else:
        where = ""
    return db.fetchall(
        f"SELECT domain, client_ip, blocked, ts FROM query_logs {where} ORDER BY ts DESC LIMIT {PH}",
        (limit,),
    )


# ── Unlock request (self-blocking delay) ──────────────────────────────────────

class UnlockIn(BaseModel):
    reason: Optional[str] = None


@app.post("/unlock-request", status_code=201)
def request_unlock(body: UnlockIn, _=Security(require_auth)):
    unlock_at = datetime.now(timezone.utc) + timedelta(hours=UNLOCK_DELAY_HOURS)
    db.execute(
        f"INSERT INTO unlock_requests (reason, unlock_at, status) VALUES ({PH},{PH},'pending')",
        (body.reason, unlock_at.isoformat()),
    )
    return {
        "message":   f"Unlock available after {UNLOCK_DELAY_HOURS}h — this delay is intentional.",
        "unlock_at": unlock_at.isoformat(),
    }


@app.get("/unlock-requests")
def list_unlock_requests(_=Security(require_auth)):
    return db.fetchall("SELECT * FROM unlock_requests ORDER BY requested_at DESC LIMIT 20")
