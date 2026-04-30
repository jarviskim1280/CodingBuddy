# CodingBuddy ⚡

AI-powered side project generator. Describe what you want to build — Claude agents plan the architecture, write the code, open PRs, review each other's work, and merge.

## Quick start

```bash
cd /Users/nick/Projects/CodingBuddy

# 1. Install dependencies
uv sync

# 2. Configure environment
cp .env.example .env
# → edit .env: add ANTHROPIC_API_KEY (required) and GITHUB_TOKEN (optional)

# 3. Spin up your first project
buddy new "build a todo app with React and FastAPI"

# 4. Watch it happen in the dashboard
buddy dashboard          # → http://localhost:8080
```

## Commands

| Command | Description |
|---|---|
| `buddy new "description"` | Generate a new project |
| `buddy dashboard` | Start the web dashboard |
| `buddy list` | List all projects |
| `buddy status <id>` | Show project status |

## How it works

```
buddy new "build X"
     │
     ▼
Orchestrator Agent (Claude)
  • Analyzes description
  • Picks tech stack (React + FastAPI + SQLite by default)
  • Breaks into tasks: backend / frontend / tests
  • Creates GitHub repo
     │
     ▼ (parallel)
┌─────────────┐  ┌─────────────────┐  ┌─────────────┐
│Backend Agent │  │ Frontend Agent  │  │ Test Agent  │
│  (Claude)   │  │   (Claude)      │  │  (Claude)   │
│ writes API  │  │ writes React UI │  │ writes tests│
│ opens PR    │  │ opens PR        │  │ opens PR    │
└──────┬──────┘  └────────┬────────┘  └──────┬──────┘
       │                  │                  │
       └──────────────────┴──────────────────┘
                          │
                          ▼
              Reviewer Agent (Claude)
                • Reviews each PR diff
                • Leaves structured comments
                • Worker addresses comments
                • Loop repeats (max 3 rounds)
                • Approves & merges
```

## Tech stack (for CodingBuddy itself)

- **Python** + `uv` for package management
- **Anthropic SDK** — `claude-sonnet-4-6` for all agents
- **SQLite + SQLAlchemy** — state database
- **FastAPI** — dashboard API + WebSocket stream
- **React + Vite + Tailwind** — dashboard UI
- **PyGithub / httpx** — GitHub API
- **GitPython** — local git operations
- **Typer + Rich** — CLI

## Without a GitHub token

Set only `ANTHROPIC_API_KEY` and omit `GITHUB_TOKEN`. CodingBuddy will use local bare git repos in `/tmp/codingbuddy_repos` to simulate the full PR/review flow — no GitHub account needed.

## Dashboard

The dashboard shows:
- All projects with status
- Task list per project (pending → in_progress → review → done)
- Active agent status with live heartbeat
- Real-time log streaming via WebSocket

Build the UI (optional — API works without it):

```bash
cd dashboard/ui
npm install
npm run build
```

Then `buddy dashboard` serves it at `http://localhost:8080`.

## Run the demo

```bash
python examples/run_todo_app.py
```

## Project structure

```
CodingBuddy/
├── buddy/
│   ├── cli.py              # Typer CLI
│   ├── config.py           # Settings (env vars)
│   ├── orchestrator.py     # Plans projects with Claude
│   ├── runner.py           # Spawns and coordinates agents
│   ├── github_client.py    # GitHub API (real + mock)
│   ├── db/
│   │   ├── models.py       # SQLAlchemy models
│   │   └── ops.py          # CRUD helpers
│   └── agents/
│       ├── base.py         # Claude tool-loop base class
│       ├── backend.py      # FastAPI code writer
│       ├── frontend.py     # React code writer
│       ├── tester.py       # Test writer
│       └── reviewer.py     # PR reviewer + merge
├── dashboard/
│   ├── api/                # FastAPI dashboard
│   └── ui/                 # React + Vite + Tailwind
├── examples/
│   └── run_todo_app.py     # End-to-end demo
└── pyproject.toml
```

## Environment variables

| Variable | Required | Description |
|---|---|---|
| `ANTHROPIC_API_KEY` | Yes | Anthropic API key |
| `GITHUB_TOKEN` | No | GitHub PAT (omit for local mock mode) |
| `GITHUB_USERNAME` | No | GitHub username (for repo ownership) |
| `GITHUB_ORG` | No | Create repos under an org |
| `DATABASE_URL` | No | SQLite URL (default: `./codingbuddy.db`) |
| `REPO_WORKSPACE` | No | Where to clone repos (default: `/tmp/codingbuddy_repos`) |
| `DASHBOARD_PORT` | No | Dashboard port (default: `8080`) |
| `CLAUDE_MODEL` | No | Model override (default: `claude-sonnet-4-6`) |
| `MAX_REVIEW_ROUNDS` | No | Review iterations before auto-approve (default: `3`) |
