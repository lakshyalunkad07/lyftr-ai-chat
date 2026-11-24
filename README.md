# Lyftr AI Chat

A full stack multi-turn LLM chat app with LiteLLM, provider key failover, response caching, per-request token metadata, and SQLite session history.

## 1. Live URLs

- Frontend: Not deployed yet
- Backend: Not deployed yet
- Health check: `GET <backend-url>/health`

The application is deployment-ready, but public URLs require the owner's hosting accounts and API keys. Never commit real provider credentials.

## 2. Run locally: with Docker and without

### With Docker

1. Copy `.env.example` to `.env` and set `LLM_API_KEYS` to two valid keys for the provider selected by `LITELLM_MODEL`.
2. Run `make up` from the repository root. The frontend is at <http://localhost:3000>; the API is at <http://localhost:8000>.
3. Run `make down` to stop the services. The named `app_data` volume retains the SQLite database.

Docker Compose sets `ENABLE_FAILURE_SIMULATION=true` for local demonstration. Disable it for environments where you do not want the test hook.

### Without Docker

Backend (Python 3.12+):

```sh
cd backend
python -m venv .venv
# Activate the virtual environment, then:
pip install -r requirements.txt
```

Set `LLM_API_KEYS`, `LITELLM_MODEL`, `DATABASE_URL` (for example `sqlite:///./app.db`), `ALLOWED_ORIGINS=http://localhost:3000`, and `ENABLE_FAILURE_SIMULATION=true`, then run:

```sh
uvicorn app.main:app --reload --port 8000
```

Frontend (Node.js 22+):

```sh
cd frontend
npm install
# Set VITE_API_URL=http://localhost:8000 in the build environment.
npm run dev -- --port 3000
```

## 3. Design decisions: key fallback, caching, SQLite session storage

- **Key fallback:** `LLM_API_KEYS` is an ordered comma-separated pool. Requests try each key in order; provider rate limits, quota failures, and server errors move to the next key. The response exposes only `key_1`, `key_2`, etc., never the secret. Exhaustion returns the contract's JSON 503.
- **Caching:** LiteLLM's in-memory cache is enabled for provider requests. It uses exact request content, including the selected model and full system/history/new-message list. The API reads LiteLLM's cache-hit marker and returns the cached reply and its stored token usage as `LLM_CACHE`, with a null key id and zero fallback attempts. Simulation requests disable caching so the failover hook always demonstrates a real provider call. The local cache is process-local, so keep the backend at one instance and one Uvicorn worker; this matches the assignment's no-Redis constraint. See [LiteLLM's cache documentation](https://docs.litellm.ai/docs/proxy/caching).
- **Sessions:** SQLite stores user and assistant messages, assistant metadata, timestamps, and a separate session row for the session-specific system prompt. A successful turn writes both messages together. Failed calls do not create or append to history. The history route returns oldest-first messages without system prompts.
- **Privacy and deployment:** provider keys stay in environment variables. The backend listens on port 8000 and the Nginx-served React app on port 3000. In production, set `VITE_API_URL` to the public backend URL at frontend build time, and set `ALLOWED_ORIGINS` to the exact public frontend origin.

## 4. Verification: how to see failover, cache hits and per-message token usage

- Open the frontend and send a message. Each assistant response shows `LIVE_INFERENCE` or `LLM_CACHE`, model, latency, input tokens, and output tokens for that response.
- Send the same first message in a fresh page/session to see a cache hit. New page loads create new session ids; cached tokens reflect the request that populated the cache.
- For failover, send `X-Simulate-Failure: key_1=429` to `POST /chat` while simulation is enabled. The response should report `key_id: "key_2"` and `fallback_attempts: 1`. With `*=429`, the API returns `503 {"detail":"all providers unavailable"}` and stores no message.
- Session history: `GET /sessions/{session_id}/messages`. Health: `GET /health`.
- Backend tests: from `backend`, install the test-only dependencies with `pip install -r requirements-dev.txt`, then run `python -m pytest -q -p no:cacheprovider tests/test_api.py`.

Example chat request:

```sh
curl -X POST http://localhost:8000/chat \
  -H 'Content-Type: application/json' \
  -H 'X-Simulate-Failure: key_1=429' \
  -d '{"session_id":"demo-session","message":"What is the capital of France?"}'
```

## 5. Setup Used: your editor and AI tools

- Editor: Codex workspace
- AI tools: OpenAI Codex
- Runtime: React + Vite, FastAPI + LiteLLM, SQLite, Docker Compose

## 6. Bonus features (if any): what you added beyond the requirements and why

- Optional session system prompt, persisted for the session.
- Health indicator and quick-start prompt suggestions in the chat UI.
- Backend tests for health, validation, unknown sessions, caching, history, simulated failover, and failed-request history safety.

## Deployment notes

The following Render setup matches the included Dockerfile and SQLite volume. A persistent disk is required for session history; Render currently only attaches disks to paid services. See [Render's disk documentation](https://render.com/docs/disks).

1. Push the repository to GitHub and connect it to Render.
2. Create a Render **Web Service** from this repository. Set **Root Directory** to `backend` and choose the Docker runtime. Set the health check path to `/health`.
3. Add a persistent disk mounted at `/data`. Set these service environment variables:
   - `LLM_API_KEYS`: two real keys separated by a comma, stored as a secret.
   - `DATABASE_URL`: `sqlite:////data/app.db`
   - `LITELLM_MODEL`: `gemini/gemini-3.8-flash` (or a LiteLLM model compatible with both keys).
   - `ENABLE_FAILURE_SIMULATION`: `true` (required by the assignment demo).
   - `ALLOWED_ORIGINS`: set this after creating the frontend, to its exact `https://...` origin.
   - `LLM_TIMEOUT_SECONDS`: `35`
   Render provides `PORT`; the Docker command now honors it. Keep this backend as one instance and one worker for the in-memory LiteLLM cache and SQLite volume.
4. Deploy the backend and wait for `https://<backend-name>.onrender.com/health` to return `status: ok`. It will stay unhealthy until both API keys are configured.
5. Create a Render **Static Site** from the same repository. Set **Root Directory** to `frontend`, **Build Command** to `npm ci && npm run build`, and **Publish Directory** to `dist`. Add `VITE_API_URL=https://<backend-name>.onrender.com` as a build environment variable, then deploy.
6. Copy the frontend's exact `https://...onrender.com` origin into the backend's `ALLOWED_ORIGINS` and redeploy the backend.
7. Open the public frontend, send a prompt, repeat the same first prompt in a new page to check caching, and call `/chat` with `X-Simulate-Failure: key_1=429` to check failover. Record the requested demo video after those checks pass.

The repository's live URLs and demo video are not published yet; deployment requires your GitHub, Render, and model-provider accounts.
