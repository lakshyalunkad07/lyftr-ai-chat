from __future__ import annotations

import json
import logging
import os
import re
import sqlite3
import time
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import litellm
from fastapi import FastAPI, Header, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field, field_validator
from starlette.responses import JSONResponse


def _database_path(database_url: str) -> str:
    prefix = "sqlite:///"
    if not database_url.startswith(prefix):
        raise ValueError("DATABASE_URL must be a SQLite URL")
    path = database_url[len(prefix):]
    if database_url.startswith("sqlite:////"):
        path = "/" + path.lstrip("/")
    return path


DATABASE_URL = os.getenv("DATABASE_URL", "sqlite:////data/app.db")
DB_PATH = _database_path(DATABASE_URL)
MODEL = os.getenv("LITELLM_MODEL", "gemini/gemini-3.8-flash")
API_KEYS = [key.strip() for key in os.getenv("LLM_API_KEYS", "").split(",") if key.strip()]
ORIGINS = [origin.strip() for origin in os.getenv("ALLOWED_ORIGINS", "http://localhost:3000").split(",") if origin.strip()]
FAILURE_SIMULATION = os.getenv("ENABLE_FAILURE_SIMULATION", "false").lower() == "true"
DEFAULT_SYSTEM_PROMPT = os.getenv("DEFAULT_SYSTEM_PROMPT", "You are a helpful, concise assistant.")

# LiteLLM's local cache is enabled for every provider call. Its cache-hit marker
# drives the exact source and metadata fields returned by the API.
litellm.cache = litellm.Cache(type="local")
litellm.telemetry = False

def connect() -> sqlite3.Connection:
    if DB_PATH != ":memory:":
        Path(DB_PATH).parent.mkdir(parents=True, exist_ok=True)
    connection = sqlite3.connect(DB_PATH, timeout=15)
    connection.row_factory = sqlite3.Row
    return connection


def init_db() -> None:
    with connect() as db:
        db.execute("PRAGMA journal_mode=WAL")
        db.execute("""CREATE TABLE IF NOT EXISTS messages (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            session_id TEXT NOT NULL,
            role TEXT NOT NULL,
            content TEXT NOT NULL,
            metadata TEXT,
            created_at TEXT NOT NULL
        )""")
        db.execute("CREATE INDEX IF NOT EXISTS idx_messages_session_id_id ON messages(session_id, id)")
        db.execute("""CREATE TABLE IF NOT EXISTS sessions (
            session_id TEXT PRIMARY KEY,
            system_prompt TEXT NOT NULL,
            created_at TEXT NOT NULL
        )""")


@asynccontextmanager
async def lifespan(_: FastAPI):
    init_db()
    yield


app = FastAPI(title="Lyftr AI Chat", version="1.0.0", lifespan=lifespan,
              docs_url=None, redoc_url=None, openapi_url=None)
app.add_middleware(
    CORSMiddleware,
    allow_origins=ORIGINS,
    allow_credentials=False,
    allow_methods=["GET", "POST"],
    allow_headers=["Content-Type", "X-Simulate-Failure"],
)


@app.exception_handler(Exception)
async def unexpected_error_handler(_: Request, exc: Exception) -> JSONResponse:
    logging.getLogger("lyftr").exception(
        "Unhandled request error", exc_info=(type(exc), exc, exc.__traceback__)
    )
    return JSONResponse(status_code=500, content={"detail": "internal server error"})


class ChatRequest(BaseModel):
    session_id: str = Field(min_length=1, max_length=128)
    message: str = Field(min_length=1, max_length=4000)
    system_prompt: str | None = None

    @field_validator("session_id", "message", mode="before")
    @classmethod
    def non_blank(cls, value: str) -> str:
        if not isinstance(value, str):
            return value
        value = value.strip()
        if not value:
            raise ValueError("must not be empty")
        return value


def _failure_map(header: str | None) -> dict[str, int]:
    if not FAILURE_SIMULATION or not header:
        return {}
    result: dict[str, int] = {}
    for item in header.split(","):
        match = re.fullmatch(r"\s*(key_\d+|\*)\s*=\s*(429|500|502|503)\s*", item)
        if match:
            result[match.group(1)] = int(match.group(2))
    return result


async def _request_completion(messages: list[dict[str, str]], failures: dict[str, int]) -> tuple[Any, str, int]:
    failed = 0
    for index, key in enumerate(API_KEYS, start=1):
        key_id = f"key_{index}"
        simulated_status = failures.get(key_id, failures.get("*"))
        if simulated_status:
            failed += 1
            continue
        try:
            response = await litellm.acompletion(
                model=MODEL,
                api_key=key,
                messages=messages,
                caching=not bool(failures),
                timeout=float(os.getenv("LLM_TIMEOUT_SECONDS", "35")),
            )
            return response, key_id, failed
        except Exception as exc:
            status = getattr(exc, "status_code", None)
            # Log enough to diagnose provider failures without ever logging the API key
            # or the exception text, which may contain request details.
            logging.getLogger("lyftr").warning(
                "LLM provider request failed for %s (%s, status=%s)",
                key_id,
                type(exc).__name__,
                status,
            )
            if status in (429, 500, 502, 503) or "quota" in str(exc).lower() or status is None:
                failed += 1
                continue
            failed += 1
    raise HTTPException(status_code=503, detail="all providers unavailable")


@app.get("/health")
def health() -> dict[str, Any]:
    try:
        with connect() as db:
            db.execute("SELECT 1").fetchone()
    except Exception:
        raise HTTPException(status_code=503, detail="database unavailable") from None
    if len(API_KEYS) < 2:
        raise HTTPException(status_code=503, detail="at least two LLM API keys must be configured")
    return {"status": "ok", "keys_configured": len(API_KEYS), "cache_enabled": True}


@app.post("/chat")
async def chat(
    request: ChatRequest,
    x_simulate_failure: str | None = Header(default=None),
) -> dict[str, Any]:
    if len(API_KEYS) < 2:
        raise HTTPException(status_code=503, detail="all providers unavailable")

    with connect() as db:
        session = db.execute("SELECT system_prompt FROM sessions WHERE session_id = ?", (request.session_id,)).fetchone()
        system_prompt = request.system_prompt.strip() if request.system_prompt and request.system_prompt.strip() else (
            session["system_prompt"] if session else DEFAULT_SYSTEM_PROMPT
        )
        history = db.execute(
            "SELECT role, content FROM messages WHERE session_id = ? ORDER BY id", (request.session_id,)
        ).fetchall()

    messages = [{"role": "system", "content": system_prompt}]
    messages.extend({"role": item["role"], "content": item["content"]} for item in history)
    messages.append({"role": "user", "content": request.message})
    start = time.perf_counter()
    failures = _failure_map(x_simulate_failure)
    response, key_id, fallback_attempts = await _request_completion(messages, failures)
    hidden_params = getattr(response, "_hidden_params", None) or {}
    cache_hit = (
        hidden_params.get("cache_hit") is True
        if isinstance(hidden_params, dict)
        else getattr(hidden_params, "cache_hit", False) is True
    )
    elapsed = int((time.perf_counter() - start) * 1000)
    choice = response.choices[0]
    reply = (choice.message.content or "").strip()
    if not reply:
        raise HTTPException(status_code=503, detail="all providers unavailable")
    usage = getattr(response, "usage", None)
    input_tokens = int(getattr(usage, "prompt_tokens", 0) or 0)
    output_tokens = int(getattr(usage, "completion_tokens", 0) or 0)
    metadata = {
        "resolution_source": "LLM_CACHE" if cache_hit else "LIVE_INFERENCE",
        "model": getattr(response, "model", None) or MODEL,
        "latency_ms": max(0, elapsed) if cache_hit else max(1, elapsed),
        "input_tokens": input_tokens,
        "output_tokens": output_tokens,
        "key_id": None if cache_hit else key_id,
        "fallback_attempts": 0 if cache_hit else fallback_attempts,
    }

    now = datetime.now(timezone.utc).isoformat()
    with connect() as db:
        db.execute("INSERT INTO sessions(session_id, system_prompt, created_at) VALUES (?, ?, ?) "
                   "ON CONFLICT(session_id) DO UPDATE SET system_prompt = excluded.system_prompt",
                   (request.session_id, system_prompt, now))
        db.execute("INSERT INTO messages(session_id, role, content, created_at) VALUES (?, 'user', ?, ?)",
                   (request.session_id, request.message, now))
        db.execute("INSERT INTO messages(session_id, role, content, metadata, created_at) VALUES (?, 'assistant', ?, ?, ?)",
                   (request.session_id, reply, json.dumps(metadata), now))

    return {"session_id": request.session_id, "reply": reply, "metadata": metadata}


@app.get("/sessions/{session_id}/messages")
def get_messages(session_id: str) -> dict[str, Any]:
    with connect() as db:
        exists = db.execute("SELECT 1 FROM sessions WHERE session_id = ?", (session_id,)).fetchone()
        if not exists:
            raise HTTPException(status_code=404, detail="session not found")
        rows = db.execute("SELECT role, content, metadata FROM messages WHERE session_id = ? ORDER BY id", (session_id,)).fetchall()
    messages = []
    for row in rows:
        entry: dict[str, Any] = {"role": row["role"], "content": row["content"]}
        if row["metadata"]:
            entry["metadata"] = json.loads(row["metadata"])
        messages.append(entry)
    return {"session_id": session_id, "messages": messages}
