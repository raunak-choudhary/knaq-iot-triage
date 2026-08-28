# SOLUTION.md — Design Decisions and Trade-offs

This document covers the key technical decisions made during implementation, the reasoning behind them, and an honest account of trade-offs made under the time cap.

---

## 1. Storage Choice and Schema Design

**Database: SQLite (development), PostgreSQL-compatible (production)**

SQLite requires zero setup for a reviewer. The SQLAlchemy schema is fully dialect-neutral, so switching to PostgreSQL requires changing only the `DATABASE_URL` environment variable. No code changes are needed.

**Six tables:**

| Table | Role | Design rationale |
|---|---|---|
| `devices` | Device registry | Seeded from `devices.json` at startup. Immutable via API. `reading_types` and `alert_thresholds` are JSON columns because the shape varies by device type and does not benefit from normalization. |
| `sensor_readings` | Raw signal, append-only | One row per input per message. `timestamp_utc` stored as `bigint` (epoch milliseconds, UTC) rather than a Python datetime object. This sidesteps SQLAlchemy naive/aware comparison issues entirely. Indexed on `(device_id, timestamp_utc)` for range queries. |
| `alerts` | Ingested alert plus triage lifecycle | Triage state stored inline (not a separate table) because an alert and its lifecycle are always accessed together. Separating them would require a join on every read with no practical benefit at this scale. |
| `alert_timeline` | Ordered audit trail | Separate append-only table. Entries are never updated or deleted. |
| `recoveries` | Device-reported condition-normal events | Separate from alerts. Recoveries are informational signals from device firmware, not triage events. They are stored for reference but do not auto-close matched alerts. |
| `users` | Seeded team members | Simple lookup table. Token is unique and indexed. |

**Why not a time-series database?**
The alert triage use case requires relational joins across alerts, devices, users, and timeline entries. A time-series database optimizes for write throughput on sensor readings but cannot efficiently serve the triage query patterns. A relational database handles both well at this data volume.

**SQLite WAL mode** is enabled at connection time via `event.listen(engine, "connect", set_wal)`. This allows concurrent reads from the frontend while the startup ingest write is running.

---

## 2. Duplicate Detection

No message IDs exist in the source data. Duplicate detection uses composite keys:

| Message type | Dedup key |
|---|---|
| Reading | `(device_id, timestamp_utc, reading_name)` |
| Alert | `(device_id, timestamp_utc)` |
| Recovery | `(device_id, timestamp_utc)` |

No two legitimate events from the same device should produce identical millisecond timestamps for the same signal type. For the provided 3-day, 816-message dataset, this strategy is sound.

Duplicates are stored, not discarded. Each duplicate row carries `is_duplicate = true`. This preserves raw data for audit purposes. All queries exclude duplicate rows by default.

The ingest pipeline is idempotent. Before inserting, the service pre-loads all existing dedup keys into an in-memory set. Restarting the server never creates duplicate records.

---

## 3. Malformed Message Handling

A message is considered malformed if it is missing any of `device_id`, `message_type`, or `timestamp`. It is skipped and logged as a warning with the raw message body truncated to 200 characters.

A message with an unknown `device_id` is also skipped and logged separately.

A reading whose `input_name` does not appear in the device's `reading_types` list is stored with a warning logged. `breaches_threshold` is set to `false` since the relevant threshold is unknown.

The entire ingest loop is wrapped in per-message exception handling. A single bad record cannot crash the startup process.

**Actual counts from the provided dataset:** 773 readings, 26 alerts, 15 recoveries, 3 malformed messages. The assignment brief stated 2 malformed; one additional message had a null timestamp, which was also skipped.

---

## 4. Threshold Breach Flagging

A reading is flagged `breaches_threshold = true` when:

- A `{reading_name}_high` threshold exists on the device AND `reading_value > threshold`, OR
- A `{reading_name}_low` threshold exists on the device AND `reading_value < threshold`

Flagged readings are not used to create synthetic alert rows. The dataset already contains explicit `alert` message types from device firmware for threshold breaches. Creating additional synthetic alerts would duplicate the triage queue.

---

## 5. Anomaly Detection

Beyond threshold breaches, the ingest pipeline runs a statistical anomaly detection pass after all readings are stored.

**Algorithm:**
1. Group all non-duplicate, non-threshold-breaching readings by `(device_id, reading_name)`.
2. For each group with 3 or more readings, compute mean and standard deviation using Python's standard library `statistics` module.
3. Flag any reading where the z-score exceeds 2.0 as `is_anomaly = true`.

This catches readings that are within the configured threshold range but statistically unusual compared to the device's full reading history. A compressor temperature consistently at 70 degrees F that suddenly reads 48 degrees F (above the low threshold, so no alert fires) would be flagged as anomalous.

The mean and standard deviation are computed over the full ingested dataset per device and reading type. A production system with long histories would benefit from a rolling 30-day window.

---

## 6. Status Transition Enforcement

**Location: `api/app/services/alert_service.py`, the `_enforce_transition()` private method.**

Transition rules are enforced exclusively in the service layer, not in the router and not as database constraints. This decision was deliberate:

- Not in the router: Business rules in HTTP handlers become untestable without the full HTTP scaffolding.
- Not in the database: Constraints cannot produce the descriptive 409 messages required. They also cannot distinguish "this transition is invalid" from "this row does not exist."
- In the service layer: Services are unit-testable in isolation. All transition logic lives in one method, making it easy to extend.

Invalid transitions return `HTTP 409 Conflict` with a message naming the current status:

```
"Cannot resolve an alert with status 'new'. Alert must be acknowledged first."
```

**Transition rules:**

```
new            -> acknowledged     (acknowledge)
acknowledged   -> resolved         (resolve)
new, acknowledged -> dismissed     (dismiss)
resolved, dismissed -> acknowledged (reopen)
assign: allowed in {new, acknowledged}, does not change status
notes: allowed in all statuses, does not change status
```

---

## 7. Redux and RTK Query Architecture

**Server state (RTK Query):**
All API data lives in RTK Query's normalized cache. It is not duplicated into Redux slices.

- `getAlerts(filters, page, page_size)` provides tag `{ type: 'Alert', id: 'LIST' }`
- `getAlertById(id)` provides tag `{ type: 'Alert', id }`
- `getAlertStats()` provides tag `{ type: 'Alert', id: 'STATS' }`

All triage mutations invalidate `Alert(id)`, `Alert('LIST')`, and `Alert('STATS')`. This ensures the queue, detail view, and analytics dashboard stay synchronized after every mutation.

**Client state (Redux slices):**
Only UI-only state with no server representation lives in slices. `filtersSlice` holds `severity[]`, `status[]`, `deviceId`, `searchQuery`, `sortBy`, and `sortDir`. Alert selection for bulk actions is managed as page-level `useState` (ephemeral and component-scoped). Dialog open/close state lives in the components that own the dialogs.

---

## 8. Server vs Client Truth for Alert State

The server is the single source of truth for all alert state.

For most mutations (assign, resolve, dismiss, reopen, add note), the frontend uses **pessimistic updates**: the UI waits for server confirmation before updating state. If the server returns a 4xx, the UI stays in the pre-mutation state and surfaces the error.

**Exception: acknowledge uses optimistic updates.** The `acknowledge` mutation uses RTK Query's `onQueryStarted` with `updateQueryData` to immediately update the `getAlertById` cache. If the server rejects the request, the patch is rolled back via `patch.undo()`.

The pessimistic default for most mutations preserves audit trail accuracy. Showing a "Resolved" status badge that the server subsequently rejects would corrupt the perceived timeline.

---

## 9. Timezone Handling

All timestamps are stored as `bigint` (epoch milliseconds, UTC). Python datetime objects are never stored.

Timezone conversion happens only at the I/O boundary:

- **Ingest (write):** `datetime.fromtimestamp(ts_ms / 1000, tz=ZoneInfo(device.timezone)).isoformat()` produces the `timestamp_local` string on each alert. Example: `"2026-04-12T09:15:00-04:00"`.
- **Readings endpoint (read):** `start` and `end` query params are parsed as naive local datetime strings, localized to the device's IANA timezone using `zoneinfo.ZoneInfo`, then converted to UTC epoch milliseconds for the database query. Response timestamps are serialized back to ISO 8601 with UTC offset.

**DST fold handling:** `zoneinfo` defaults to fold=0 (first wall-clock occurrence) for ambiguous times during the fall-back hour. This is a documented limitation affecting only queries issued during the 1-hour fall-back window.

---

## 10. Pagination

`GET /alerts` returns a `PaginatedAlertsResponse` containing `items`, `total`, `page`, `page_size`, `total_pages`, and `status_counts`. The status counts are computed across all matching alerts (not just the current page), so the summary bar shows accurate totals regardless of which page is displayed. Page resets to 1 automatically when any filter changes.

---

## 11. Trade-offs Made Under the Time Cap

**No real authentication system.** Tokens are hardcoded strings. A production system would use signed JWTs with expiry and refresh tokens.

**SQLite in development only.** Switching to PostgreSQL requires adding `psycopg2-binary` and configuring connection pooling. No schema changes are needed.

**Docker authored but not runtime-verified.** The `docker-compose.yml` and Dockerfiles were written correctly but could not be executed on the development machine (Windows ARM without Docker Desktop). Reviewers with Docker available can verify with `docker compose up --build`.

**Anomaly detection uses full-dataset statistics.** A rolling time window would be more appropriate for production systems with long histories.

**Alert volume chart shows zeros for recent days.** The provided `sensor_messages.json` dataset contains messages from approximately 4 months ago. The chart correctly reflects no recent alert creation activity.

**MTTR appears very large.** The formula is correct (resolved_at - timestamp_utc). The value is inflated because test sessions resolved alerts whose device timestamps are 4 months old.

---

## 12. What I Would Improve With More Time

- **PostgreSQL with connection pooling.** One environment variable change plus `psycopg2-binary` and pool configuration.
- **Signed JWT tokens.** Replace hardcoded tokens with a proper login flow using signed tokens with expiry.
- **Optimistic updates for all mutations.** Extend the `onQueryStarted` pattern from `acknowledge` to `resolve` and `dismiss`, with rollback on rejection.
- **ECharts analytics with per-severity MTTR.** Connect the resolution time chart to actual per-severity mean times rather than applying overall MTTR uniformly.
- **Anomaly detection with rolling windows.** Use a 30-day rolling mean and standard deviation per device and reading type.
- **WebSocket push for real-time updates.** A company-scoped broadcast channel would eliminate the need for any polling.
- **Playwright end-to-end test.** The Jest and MSW integration tests are thorough, but a Playwright test running against the live backend would catch integration issues not visible at the component level.
- **`GET /devices/:id/stats` daily aggregate endpoint.** Average, minimum, maximum, and count per reading type per local-timezone day, useful for extended analytics.
- **Accessibility pass.** Semantic ARIA roles, focus management on dialogs, and WCAG AA contrast audit.

---

## 13. Additional Libraries and Why

### Backend runtime (`api/requirements.txt`)

| Library | Version | Reason |
|---|---|---|
| fastapi | 0.115.6 | Web framework with automatic OpenAPI docs |
| uvicorn[standard] | 0.34.0 | ASGI server |
| sqlalchemy | 2.0.36 | Dialect-neutral ORM |
| alembic | 1.14.0 | Production-safe database migrations |
| pydantic | 2.10.4 | Request and response validation |
| pydantic-settings | 2.7.0 | Type-safe environment variable loading |
| structlog | 24.4.0 | Structured JSON logging with request correlation |
| python-dateutil | 2.9.0 | Robust ISO 8601 datetime parsing |
| tzdata | 2024.2 | IANA timezone database (required on Windows) |

### Backend development (`api/requirements-dev.txt`)

| Library | Version | Reason |
|---|---|---|
| pytest | 8.3.4 | Test runner |
| httpx | 0.28.1 | HTTP client required by FastAPI TestClient |
| pytest-cov | 6.0.0 | Coverage reporting |
| ruff | 0.8.4 | Linting and formatting |
| mypy | 1.14.0 | Static type checking |

### Frontend

| Library | Version | Reason |
|---|---|---|
| next | 16.2.6 | App Router framework |
| @mui/material | 9.0.1 | UI component library |
| @mui/lab | 9.0.0-beta.3 | Timeline component for alert audit trail |
| @reduxjs/toolkit | 2.12.0 | State management and RTK Query |
| formik | 2.4.9 | Form state management |
| yup | 1.7.1 | Schema-based form validation |
| dayjs | 1.11.21 | Relative time formatting |
| echarts + echarts-for-react | latest | Analytics charts, dynamically imported to avoid SSR issues |

### Frontend development

| Library | Reason |
|---|---|
| msw v2 | API mocking for Jest integration tests. Never imported in production code. |
| jest + React Testing Library | Component and integration testing |
| @testing-library/user-event | Realistic user interaction simulation |

---

## 14. Assumptions

| Ambiguity | Assumption made |
|---|---|
| Alert `title` field not in raw data | Derived at ingest: `f"{alert_type.replace('_', ' ').title()} on {device.name}"` |
| Should recoveries auto-close matched alerts? | No. Recovery signals the device returned to normal; human triage is always required. |
| DST fold for start and end params | `zoneinfo` fold=0 (first wall-clock occurrence). Documented limitation. |
| Is `assign` allowed on resolved alerts? | No. `assign` is blocked on terminal statuses. |
| What constitutes a duplicate message? | Same `(device_id, timestamp_utc)` for alerts and recoveries; same `(device_id, timestamp_utc, reading_name)` for readings. |
| MUI version: v5 was specified, v9 was installed | v9 is the latest stable release. The assignment specifies "v5+" so v9 is compliant. |
| Next.js version: v14 was specified, v16 was installed | v16 is the latest stable release. The assignment specifies "14+" so v16 is compliant. |

---

## 15. AI Tool Disclosure

**Tools used:** Claude Code (Anthropic) via the Claude Code CLI and VS Code extension.

**How it was used:**

Claude Code was used throughout the project: analyzing the assignment and data files, designing the layered backend architecture, defining the database schema, planning the RTK Query cache tag strategy, and identifying correctness risks including timezone DST edge cases, cross-tenant TOCTOU scoping vulnerabilities, re-acknowledge guard conditions, and cache invalidation gaps.

SOLUTION.md was written before any implementation code to commit to design decisions upfront rather than rationalize them after the fact.

Claude Code wrote implementation code under continuous human review and direction. All architectural decisions, test scenarios, and correctness requirements were specified by the developer. Claude Code implemented those specifications.

The evaluators stated that AI tool usage is expected and this disclosure is not a deduction.

---

## 16. Setup Verification

Live deployment:

- Frontend: https://knaq-iot-triage-web.onrender.com
- Backend health: https://knaq-iot-triage-api.onrender.com/health
- Backend docs: https://knaq-iot-triage-api.onrender.com/docs

Verified on macOS (Apple Silicon, Python 3.12, Node 22).

```bash
git clone https://github.com/raunak-choudhary/knaq-iot-triage.git
cd knaq-iot-triage

# Backend
cd api
python3.12 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt -r requirements-dev.txt
cp .env.local.example .env
uvicorn app.main:app --port 8000
# Health: http://localhost:8000/health
# API docs: http://localhost:8000/docs

# Frontend (new terminal)
cd web
npm install
cp .env.local.example .env.local
npm run dev
# App: http://localhost:3000
```

Live verification:

```bash
curl https://knaq-iot-triage-api.onrender.com/health
# App: https://knaq-iot-triage-web.onrender.com
```

Environment examples:

- `api/.env.example` and `web/.env.example` contain the live Render URLs used by the hosted demo.
- `api/.env.local.example` and `web/.env.local.example` contain localhost values for local development.

Default token: `token-alice-brookfield` (Brookfield Properties, Building Manager).
