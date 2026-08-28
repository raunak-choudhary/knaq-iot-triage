# Knaq IoT Alert Triage and Resolution System

A production-grade, full-stack web application that ingests raw IoT device messages, validates and stores them, and gives building managers a complete workflow to acknowledge, assign, investigate, and resolve equipment alerts with a full audit trail.

Built as a take-home engineering assessment. The system covers two critical gaps in a facility management platform: raw device data had no structured storage or query layer, and when alerts fired, there was no way for a team to triage or track them.

## Table of Contents

- [Live Demo](#live-demo)
- [The Problem This Solves](#the-problem-this-solves)
- [System Architecture](#system-architecture)
- [Key Features](#key-features)
- [Tech Stack](#tech-stack)
- [Repository Structure](#repository-structure)
- [Prerequisites](#prerequisites)
- [Installation and Setup](#installation-and-setup)
- [Running the Application](#running-the-application)
- [Environment Files](#environment-files)
- [Seeded Users and Tokens](#seeded-users-and-tokens)
- [API Endpoints](#api-endpoints)
- [Running Tests](#running-tests)
- [Render Deployment](#render-deployment)
- [Docker Setup (Optional)](#docker-setup-optional)
- [Keyboard Shortcuts](#keyboard-shortcuts)
- [Design Decisions](#design-decisions)
- [Assumptions](#assumptions)
- [About the Author](#about-the-author)

---

## Live Demo

- Frontend: https://knaq-iot-triage-web.onrender.com
- Backend health: https://knaq-iot-triage-api.onrender.com/health
- Backend docs: https://knaq-iot-triage-api.onrender.com/docs

The live demo runs on Render using the same SQLite-backed startup flow as local development. Free Render services can spin down after inactivity, so the first request may take about a minute to wake up.

---

## The Problem This Solves

IoT equipment across buildings (elevators, escalators, HVAC compressors) pushes raw sensor readings and threshold alerts to the cloud. Without a structured system:

- There is no answer to "what is currently alerting on this device?" or "show me all critical alerts for this company in the last 24 hours."
- When an alert fires, it sits unacknowledged in a database with no owner, no timeline, and no record of what was done about it.

This system closes both gaps. It ingests and validates all device messages, exposes a queryable API scoped by company, and provides a web interface where operations teams can run a full triage workflow from first alert to final resolution.

---

## System Architecture

```
IoT Devices
    |
    v
sensor_messages.json   devices.json
    |                       |
    +----------+------------+
               |
               v
     FastAPI Backend (port 8000)
         |
         +-- Ingest Pipeline
         |     parse -> validate -> deduplicate -> flag anomalies -> store
         |
         +-- REST API
         |     GET  /alerts          (paginated, filtered, company-scoped)
         |     GET  /alerts/:id      (full alert with timeline)
         |     GET  /alerts/stats    (analytics: MTTR, volumes, anomaly count)
         |     POST /alerts/:id/acknowledge
         |     POST /alerts/:id/assign
         |     POST /alerts/:id/resolve
         |     POST /alerts/:id/notes
         |     POST /alerts/:id/dismiss
         |     POST /alerts/:id/reopen
         |     POST /alerts/bulk/acknowledge
         |     POST /alerts/bulk/assign
         |     GET  /devices         (company-scoped)
         |     GET  /devices/:id/readings  (timezone-aware)
         |     GET  /users           (company-scoped)
         |
         +-- SQLite (dev) / PostgreSQL-compatible schema
               |
               v
     Next.js Frontend (port 3000)
         Alert Queue + Alert Detail + Analytics Dashboard
```

**Multi-tenancy:** Every API request carries a bearer token that resolves to a user with a company. All queries are scoped to that company at the database level using in-query joins. Cross-company data is never exposed.

---

## Key Features

- **Ingest pipeline** that reads 816 raw sensor messages, distinguishes readings from alerts and recoveries, validates each message against device thresholds, detects and flags duplicates, and runs statistical anomaly detection on readings that are within range but unusual versus recent device history.
- **Full triage workflow** with server-enforced status transitions: new, acknowledged, resolved, dismissed, with optional reopen. Every mutation appends a timestamped, attributed timeline entry.
- **Multi-tenant REST API** with company-scoped bearer token authentication, timezone-aware device readings, paginated alert lists, and a stats endpoint for the analytics dashboard.
- **Alert Queue** with summary bar (clickable status counts), severity and device filters, full-text search, sortable columns, bulk selection with keyboard shortcut (press `A` to acknowledge selected alerts).
- **Alert Detail** with contextual action buttons, metric card showing triggered reading versus threshold, assignment section with avatar display, and a chronological timeline with icon-coded entries.
- **Resolve Dialog** with Formik and Yup inline validation covering resolution type, root cause, action taken, preventive measures, and time spent.
- **Assign Dialog** with company-scoped user list, current assignee highlighted, and optional assignment note.
- **Analytics Dashboard** with four ECharts charts: alerts by status (donut), alerts by severity (bar), alert volume over the last 7 days (line), and resolution time versus SLA targets (bar with reference line). Five metric cards include MTTR, open alert count, resolved this week versus last week, dismissal rate, and anomaly reading count.
- **Dark and light theme** with persistent localStorage preference and full Knaq brand color palette.
- **Responsive layout** at 375px, 768px, and 1280px breakpoints.
- **Docker support** via a provided `docker-compose.yml`.

---

## Tech Stack

### Backend

| Technology | Version | Purpose |
|---|---|---|
| Python | 3.11 or 3.12 | Runtime |
| FastAPI | 0.115.6 | Web framework with automatic OpenAPI docs |
| SQLAlchemy | 2.0.36 | ORM with dialect-neutral schema (SQLite dev, PostgreSQL prod) |
| Alembic | 1.14.0 | Database migrations |
| Pydantic v2 | 2.10.4 | Request and response validation |
| pydantic-settings | 2.7.0 | Type-safe environment variable loading |
| structlog | 24.4.0 | Structured JSON request logging |
| python-dateutil | 2.9.0 | Robust datetime parsing for timezone-aware query params |
| zoneinfo | stdlib | IANA timezone conversion (no third-party dependency) |
| uvicorn | 0.34.0 | ASGI server |
| tzdata | 2024.2 | IANA timezone database (required on Windows, harmless on macOS/Linux) |

### Frontend

| Technology | Version | Purpose |
|---|---|---|
| Next.js | 16.2 (App Router) | React framework with SSR |
| TypeScript | 5 (strict mode) | Type safety, no `any` |
| MUI | v9 | Component library and theming |
| Redux Toolkit | 2.12 | State management |
| RTK Query | (part of Redux Toolkit) | Server state, caching, cache invalidation |
| Formik | 2.4.9 | Form state management |
| Yup | 1.7.1 | Schema validation |
| ECharts + echarts-for-react | latest | Analytics charts |
| dayjs | 1.11.21 | Relative time formatting |

### Testing

| Tool | Purpose |
|---|---|
| pytest + httpx | Backend unit and integration tests (120 tests) |
| pytest-cov | Coverage reporting |
| Jest + React Testing Library | Frontend unit and integration tests (103 tests) |
| MSW v2 | API mocking for frontend integration tests |

---

## Repository Structure

```
knaq-iot-triage/
  api/                              Backend service (FastAPI)
    app/
      main.py                       App factory and lifespan startup
      config.py                     Environment variable loading
      database.py                   SQLAlchemy engine, session, WAL mode
      exceptions.py                 Custom HTTP exception classes
      middleware/                   Request ID injection and structured logging
      models/                       SQLAlchemy ORM models (one file per table)
      schemas/                      Pydantic request and response models
      repositories/                 Data access layer (DB queries only)
      services/                     Business logic layer
        ingest_service.py           Full ingest pipeline and anomaly detection
        alert_service.py            Triage mutations and transition enforcement
        auth_service.py             Token-to-user resolution
      routers/                      Thin HTTP handlers (alerts, devices, users)
      dependencies/                 FastAPI dependency injection (auth)
      utils/timezone.py             Epoch ms and IANA timezone conversion
    alembic/                        Database migrations
    scripts/seed_users.py           Idempotent user seeding
    tests/
      unit/                         Isolated logic tests (mocked dependencies)
      integration/                  Full HTTP cycle tests with in-memory SQLite
      factories/                    Test data builders
    requirements.txt
    requirements-dev.txt

  web/                              Frontend service (Next.js)
    src/
      app/                          Next.js App Router pages
        alerts/page.tsx             Alert Queue
        alerts/[id]/page.tsx        Alert Detail
        analytics/page.tsx          Analytics Dashboard
      features/alerts/              Feature-based module
        api/alertsApi.ts            RTK Query endpoints and cache tags
        components/                 Feature components (AlertTable, ResolveDialog, etc.)
        slices/filtersSlice.ts      Client-side filter and sort state
        types/index.ts              TypeScript interfaces
      components/                   Shared atomic UI components
      constants/                    Severity colors, status labels, routes
      utils/                        Formatters, error helpers
      lib/                          Redux store, MUI theme, auth token injection

  data/
    devices.json                    10 IoT devices across 3 companies
    sensor_messages.json            816 raw sensor messages (3-day window)

  docker-compose.yml                One-command local bring-up (see Docker section)
  README.md                         This file
  DESIGN_DECISIONS.md               Design decisions and trade-offs
```

---

## Prerequisites

Before you start, make sure you have the following installed:

- **Python 3.11 or 3.12** (check with `python3 --version`)
- **Node.js 18 or higher** (check with `node --version`)
- **git** (check with `git --version`)

---

## Installation and Setup

### Step 1 — Clone the Repository

```bash
git clone https://github.com/raunak-choudhary/knaq-iot-triage.git
cd knaq-iot-triage
```

### Step 2 — Backend Setup

Open a terminal and run the following commands from the project root.

**macOS and Linux:**

```bash
cd api
python3.12 -m venv .venv          # or python3.11 if 3.12 is not available
source .venv/bin/activate
pip install -r requirements.txt -r requirements-dev.txt
cp .env.local.example .env
```

**Windows (PowerShell):**

```powershell
cd api
py -3.12 -m venv .venv            # or py -3.11
.venv\Scripts\Activate.ps1
pip install -r requirements.txt -r requirements-dev.txt
pip install tzdata                 # required on Windows for IANA timezone support
copy .env.local.example .env
```

The local `.env` file points CORS at the frontend dev server on port 3000. No changes are needed for local development.

### Step 3 — Frontend Setup

Open a second terminal from the project root.

```bash
cd web
npm install
```

**macOS and Linux:**

```bash
cp .env.local.example .env.local
```

**Windows:**

```powershell
copy .env.local.example .env.local
```

The default `.env.local` points the frontend at `http://localhost:8000` and authenticates as Alice Chen (Brookfield Properties). No changes are needed to get started.

---

## Running the Application

You need two terminal windows running at the same time.

### Terminal 1 — Backend

```bash
cd api
source .venv/bin/activate          # Windows: .venv\Scripts\Activate.ps1
uvicorn app.main:app --port 8000
```

On startup, the backend automatically:
1. Runs Alembic migrations
2. Seeds 6 users across 3 companies
3. Ingests all 816 sensor messages (idempotent, safe to restart)
4. Runs anomaly detection on all readings

You should see log lines for `migrations_complete`, `seed_users_complete`, and `ingest_complete`.

- **Swagger UI (all endpoints):** http://localhost:8000/docs
- **Health check:** http://localhost:8000/health

### Terminal 2 — Frontend

```bash
cd web
npm run dev
```

- **Web application:** http://localhost:3000

The application auto-redirects to the Alert Queue. You should see Brookfield Properties alerts loaded immediately from your local API.

---

## Environment Files

Deployment and local development use separate example files so URLs do not get mixed accidentally.

| File | Use for | Key values |
|---|---|---|
| `api/.env.example` | Hosted backend | `CORS_ORIGINS=https://knaq-iot-triage-web.onrender.com` |
| `api/.env.local.example` | Local backend | `CORS_ORIGINS=http://localhost:3000` |
| `web/.env.example` | Hosted frontend | `NEXT_PUBLIC_API_URL=https://knaq-iot-triage-api.onrender.com` |
| `web/.env.local.example` | Local frontend | `NEXT_PUBLIC_API_URL=http://localhost:8000` |

The demo bearer tokens are seeded test data, not production secrets. Do not commit real `.env` or `.env.local` files.

---

## Seeded Users and Tokens

Six users are seeded across three companies on every startup. To switch the company perspective in the frontend, change `NEXT_PUBLIC_AUTH_TOKEN` in `web/.env.local` and restart the frontend.

| Token | Name | Role | Company | Visible Devices |
|---|---|---|---|---|
| `token-alice-brookfield` | Alice Chen | Building Manager | Brookfield Properties | ELV-001, ELV-002, ESC-002, CMP-001 |
| `token-bob-brookfield` | Bob Martinez | Technician | Brookfield Properties | ELV-001, ELV-002, ESC-002, CMP-001 |
| `token-carol-hines` | Carol Kim | Building Manager | Hines | ELV-003, ELV-004, CMP-002, CMP-004 |
| `token-dave-hines` | Dave Okafor | Technician | Hines | ELV-003, ELV-004, CMP-002, CMP-004 |
| `token-eve-mitsui` | Eve Tanaka | Building Manager | Mitsui Fudosan | ESC-001, CMP-003 |
| `token-frank-mitsui` | Frank Sato | Technician | Mitsui Fudosan | ESC-001, CMP-003 |

To use a token directly against the API (for example, in Swagger UI), set the `Authorization` header to `Bearer <token>`.

---

## API Endpoints

All endpoints (except `/health`) require `Authorization: Bearer <token>`. Results are scoped to the token owner's company.

| Method | Path | Description |
|---|---|---|
| GET | `/health` | Health check (no auth required) |
| GET | `/alerts` | List alerts with filters: `severity`, `status`, `device_id`, `q`, `from`, `to`, `page`, `page_size` |
| GET | `/alerts/stats` | Analytics summary: MTTR, status counts, severity counts, weekly trends, anomaly count |
| GET | `/alerts/:id` | Single alert with full timeline |
| POST | `/alerts/:id/acknowledge` | Transition new to acknowledged |
| POST | `/alerts/:id/assign` | Assign to a team member (body: `assignee_id`, optional `note`) |
| POST | `/alerts/:id/resolve` | Transition acknowledged to resolved (body: resolution fields) |
| POST | `/alerts/:id/notes` | Add a note to the timeline |
| POST | `/alerts/:id/dismiss` | Transition new or acknowledged to dismissed |
| POST | `/alerts/:id/reopen` | Transition resolved or dismissed back to acknowledged |
| POST | `/alerts/bulk/acknowledge` | Acknowledge multiple alerts in one request |
| POST | `/alerts/bulk/assign` | Assign multiple alerts in one request |
| GET | `/devices` | List devices |
| GET | `/devices/:id` | Device detail |
| GET | `/devices/:id/readings` | Readings in a time range. `start` and `end` are in device local time (ISO 8601). Response timestamps are also in device local time with UTC offset. |
| GET | `/users` | Team members in your company |

Invalid status transitions return `409 Conflict` with a descriptive message. Cross-company access returns `404` (not `403`) to avoid confirming the existence of IDs to unauthorized callers.

---

## Running Tests

### Backend Tests

With the virtual environment active:

```bash
cd api
source .venv/bin/activate         # Windows: .venv\Scripts\Activate.ps1
pytest -q
```

Expected result: **120 tests pass** across unit tests (transition rules, timezone utilities, ingest logic, alert service) and integration tests (full HTTP cycle with in-memory SQLite), covering 97 percent of application code.

To generate a coverage report:

```bash
pytest --cov=app --cov-report=term-missing -q
```

### Frontend Tests

```bash
cd web
npm test -- --watchAll=false
```

Expected result: **103 tests pass** across component unit tests, Redux slice tests, utility function tests, and page-level integration tests using MSW.

---

## Render Deployment

The live demo is deployed as two free Render Web Services from this repository. The backend uses SQLite and rebuilds its demo database from the bundled data on startup.

### Backend Service

Create a Render Web Service from the public repository URL:

```text
https://github.com/raunak-choudhary/knaq-iot-triage
```

Use these settings:

| Setting | Value |
|---|---|
| Name | `knaq-iot-triage-api` |
| Runtime | `Python 3` |
| Branch | `main` |
| Build command | `pip install -r api/requirements.txt` |
| Start command | `cd api && uvicorn app.main:app --host 0.0.0.0 --port $PORT` |
| Instance type | Free |

Environment variables:

```text
DATABASE_URL=sqlite:///./knaq.db
CORS_ORIGINS=https://knaq-iot-triage-web.onrender.com
LOG_LEVEL=INFO
PYTHON_VERSION=3.12.9
```

If you use a different frontend host, replace `CORS_ORIGINS` with that URL. For private values in real projects, document placeholders such as `1234-xxxx-xxxx` instead of committing actual secrets.

### Frontend Service

Create a second Render Web Service from the same repository URL:

| Setting | Value |
|---|---|
| Name | `knaq-iot-triage-web` |
| Runtime | `Node` |
| Branch | `main` |
| Root directory | `web` |
| Build command | `npm ci && npm run build` |
| Start command | `npm start -- -p $PORT` |
| Instance type | Free |

Environment variables:

```text
NEXT_PUBLIC_API_URL=https://knaq-iot-triage-api.onrender.com
NEXT_PUBLIC_AUTH_TOKEN=token-alice-brookfield
NODE_VERSION=22.13.0
```

After deployment, verify:

```bash
curl https://knaq-iot-triage-api.onrender.com/health
open https://knaq-iot-triage-web.onrender.com
```

For Vercel, deploy only the `web` directory and set the same `NEXT_PUBLIC_API_URL` and `NEXT_PUBLIC_AUTH_TOKEN` values. The FastAPI backend still needs a separate host such as Render.

---

## Docker Setup (Optional)

A `docker-compose.yml` is provided at the project root for one-command local bring-up.

For a no-install review, use the live Render deployment linked at the top of this README. Docker is only needed if you want to run both services locally.

On macOS, Docker Desktop is not required. Use **Colima**, a lightweight CLI-only container runtime:

```bash
# Install once
brew install colima docker docker-compose

# Start the runtime before using Docker
colima start --cpu 2 --memory 4

# Build and start both services
docker compose up --build

# Stop
docker compose down
```

This starts the API on port 8000 and the frontend on port 3000. The API container auto-runs migrations, seed, and ingest on startup.

---

## Keyboard Shortcuts

On the Alert Queue, press **`a`** (or `A`) while one or more `new` alerts are selected to bulk acknowledge them. The shortcut is ignored when a text input or textarea has focus.

---

## Design Decisions

Key architectural decisions are documented in detail in [DESIGN_DECISIONS.md](DESIGN_DECISIONS.md). A brief summary:

- **SQLite for development, PostgreSQL-compatible schema** via SQLAlchemy. Switching to PostgreSQL requires changing only `DATABASE_URL`.
- **Layered backend architecture**: routers delegate to services, services delegate to repositories. This keeps business logic isolated and independently testable.
- **Triage state stored inline** in the `alerts` table, not a separate table. Alert and its lifecycle are always accessed together.
- **Timestamps stored as bigint epoch milliseconds** throughout. This avoids SQLAlchemy naive/aware datetime comparison issues entirely.
- **Company scoping enforced at the query level**, never as a post-fetch check, to eliminate time-of-check to time-of-use vulnerabilities.
- **Pessimistic UI updates**: the frontend waits for server confirmation before updating state. This preserves audit trail accuracy.
- **Anomaly detection using z-scores**: readings that are within threshold range but more than 2 standard deviations from that device's own mean for the same reading type are flagged as anomalies.

---

## Assumptions

- Bearer tokens are hardcoded for simplicity. A production system would use signed JWTs with expiry.
- Recoveries do not automatically close matched alerts. Human triage is always required.
- The provided `sensor_messages.json` dataset is intentionally dirty. Two malformed messages and some unknown reading types are handled gracefully, logged, and skipped.

---

## About the Author

**Project Built by:**

Raunak Choudhary

NYU Masters' CS Grad @ Class' 26

raunakchoudhary17@gmail.com | rc5553@nyu.edu
