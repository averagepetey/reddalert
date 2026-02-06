# Final Specification Summary — Reddalert

## Stack

| Layer    | Technology                     |
|----------|--------------------------------|
| Backend  | Python + FastAPI               |
| Frontend | Next.js + React + Tailwind CSS |
| Database | PostgreSQL                     |
| Worker   | Separate background process    |
| Hosting  | Railway or Render              |
| Repo     | Monorepo (/backend, /frontend) |

## Core Behavior

| Setting               | Value                          |
|-----------------------|--------------------------------|
| Primary alert         | Discord webhook                |
| Backup alert          | Email + dashboard              |
| Default poll interval | Hourly (configurable per client) |
| Proximity window      | 15 words default               |
| Comment depth         | Top-level only                 |
| Snippet length        | 200 characters                 |
| Data retention        | 90 days                        |
| Reddit auth           | Shared app default, BYOC option |

## Matching Logic

| Feature          | Behavior                                    |
|------------------|---------------------------------------------|
| OR groups        | Field-based UI, enter to add                |
| Negations        | Separate exclude field                      |
| Exclusion scope  | User configurable (anywhere vs proximity)   |
| Stemming         | User toggle (off by default)                |
| Single words     | Allowed with warning                        |
| Case sensitivity | Case-insensitive                            |

## Alert Behavior

| Feature               | Behavior                         |
|-----------------------|----------------------------------|
| Batching              | Batch if 3+ in 2 min             |
| Multi-keyword match   | Primary + "also matched" note    |
| Duplicate suppression | Never re-alert same post/keyword |
| Failed webhook        | Retry 3x, then email + dashboard |
| Alert format          | Rich Discord embeds              |

## Content Handling

| Feature         | Behavior                    |
|-----------------|-----------------------------|
| Content storage | Full text                   |
| Deleted posts   | Keep copy, mark as deleted  |
| Crossposts      | User configurable           |
| Media posts     | User configurable           |
| Bot filtering   | Toggleable (off by default) |

## UX Flow

| Feature               | Behavior                                          |
|-----------------------|---------------------------------------------------|
| Onboarding            | Linear wizard                                     |
| Webhook setup         | "Connect to Discord" OAuth2 or manual URL paste    |
| Min setup             | 1 webhook + 1 subreddit + 1 keyword               |
| Subreddit suggestions | Keyword-based recommendations                     |
| Partial config        | Allowed with status indicator                     |
| Invalid subreddits    | Accept with status badge                          |
| Subreddit cap         | None for MVP                                      |
| Analytics             | Basic stats (match counts, top keywords/subs)     |

## Multi-Tenancy

| Feature            | Behavior                |
|--------------------|-------------------------|
| Architecture       | Multi-tenant from day 1 |
| Auth               | Email/password + JWT    |
| Per-client polling | Configurable interval   |

---

## Reddalert — Project Overview

### What It Does

Reddalert is a Reddit monitoring service that helps Discord-based businesses discover high-intent leads by tracking keyword mentions across subreddits in near real-time. When someone on Reddit talks about topics relevant to a business, Reddalert detects it and pushes an alert to Discord within minutes.

**Example use case:** A sports betting SaaS company wants to know whenever someone mentions "arbitrage betting" in r/sportsbook or r/sportsbetting. Reddalert monitors those subreddits, catches the mention, and sends a Discord notification with a link to the post — allowing the business to engage with a potential customer at the moment of intent.

---

## How It Works — System Flow

### 1. INGESTION (Background Worker)

```
┌──────────┐      ┌──────────────┐      ┌─────────────┐
│ Reddit   │ ──── │ Poller       │ ──── │ Raw Content │
│ API      │      │ (hourly/     │      │ Store       │
│          │      │  configurable)│      │ (PostgreSQL)│
└──────────┘      └──────────────┘      └─────────────┘
```

- Polls each monitored subreddit
- Fetches new posts + top-level comments
- Deduplicates by content hash
- Stores normalized text

### 2. MATCHING (Background Worker)

```
┌─────────────┐      ┌──────────────┐      ┌─────────────┐
│ New Content │ ──── │ Matcher      │ ──── │ Match       │
│ Queue       │      │ Engine       │      │ Records     │
└─────────────┘      └──────────────┘      └─────────────┘
```

- For each piece of content:
  - Load all active keywords for monitored subreddits
  - Tokenize content
  - Check phrase presence within proximity window
  - Apply negation filters
  - Generate match records with snippets

### 3. ALERTING (Background Worker)

```
┌─────────────┐      ┌──────────────┐      ┌─────────────┐
│ Match       │ ──── │ Alert        │ ──── │ Discord     │
│ Records     │      │ Dispatcher   │      │ Webhook     │
└─────────────┘      └──────────────┘      └─────────────┘
```

- Batches matches (3+ in 2 min)
- Formats rich embed message
- Sends to Discord
- On failure: retry 3x, then email + dashboard

### 4. API LAYER (FastAPI Server)

```
┌─────────────┐      ┌──────────────┐      ┌─────────────┐
│ Next.js     │ ──── │ REST API     │ ──── │ PostgreSQL  │
│ Frontend    │      │ (FastAPI)    │      │             │
└─────────────┘      └──────────────┘      └─────────────┘
```

- CRUD for keywords, subreddits, webhooks
- Discord OAuth2 webhook setup (webhook.incoming scope)
- Match history retrieval
- Client configuration
- Basic analytics

---

## Core Components

### 1. Reddit Poller

- Connects to Reddit API via PRAW library
- Maintains last_seen_id per subreddit to only fetch new content
- Respects rate limits (100 requests/min)
- Runs on configurable interval (default hourly, can be faster)
- Shared polling — one poll serves all clients monitoring that subreddit

### 2. Text Normalizer

- Lowercases text
- Strips URLs and markdown formatting
- Normalizes whitespace
- Tokenizes into words
- Segments into sentences
- Produces clean, matchable text

### 3. Proximity Matcher

- Takes a phrase like "arbitrage betting"
- Splits into tokens: ["arbitrage", "betting"]
- Scans normalized content for all tokens
- Verifies tokens appear within N-word window (default 15)
- Handles OR groups (match any phrase in group)
- Handles negations (reject if exclusion word present)
- Returns match with span indexes and confidence score

### 4. Deduplicator

- Hashes normalized content
- Checks hash against seen index before processing
- Prevents duplicate matches, alerts, and embeddings
- Applies at ingestion time (cheap) not matching time (expensive)

### 5. Alert Dispatcher

- Pulls pending matches
- Batches if multiple matches within 2-minute window
- Formats Discord embed with:
  - Subreddit name
  - Matched keyword
  - 200-char snippet with context
  - Link to Reddit post
  - "Also matched" note if multiple keywords hit
- Sends via webhook
- Logs delivery status
- Retries with exponential backoff on failure
- Falls back to email + dashboard after 3 failures

### 6. REST API

- Auth: Email/password registration + login, JWT Bearer token per request
- Endpoints:
  - `POST /auth/register` — register with email + password, returns JWT
  - `POST /auth/login` — login with email + password, returns JWT
  - `GET/PATCH /clients/me` — view/update client settings
  - `GET/POST/DELETE /keywords` — manage keyword phrases
  - `GET/POST/DELETE /subreddits` — manage monitored subs
  - `GET /discord/auth-url` — Discord OAuth2 authorization URL
  - `POST /discord/callback` — exchange Discord code for webhook
  - `GET/POST /webhooks` — manage Discord webhooks
  - `GET /matches` — retrieve match history
  - `GET /stats` — basic analytics
- Validation: Subreddit existence check, webhook test on creation

### 7. Next.js Dashboard

- Onboarding wizard: Webhook (Discord OAuth2 or manual paste) → Subreddits → Keywords → Done
- Keyword manager: Add phrases with enter-to-add UI, exclusions, proximity config
- Subreddit manager: Add subs, see suggestions based on keywords, status indicators
- Match feed: Recent matches with filtering
- Settings: Polling interval, notification preferences, backup email

---

## Data Model

```
Client
├── id (uuid)
├── email (unique, required)
├── password_hash (PBKDF2-SHA256)
├── polling_interval (minutes)
├── created_at
│
├── Keywords[]
│   ├── id
│   ├── phrases[] (OR group)
│   ├── exclusions[]
│   ├── proximity_window (default 15)
│   ├── require_order (default false)
│   ├── use_stemming (default false)
│   ├── is_active
│   └── created_at
│
├── MonitoredSubreddits[]
│   ├── id
│   ├── name (e.g., "sportsbook")
│   ├── status (active/inaccessible/private)
│   ├── include_media_posts
│   ├── dedupe_crossposts
│   ├── filter_bots
│   └── last_polled_at
│
└── WebhookConfigs[]
    ├── id
    ├── url
    ├── is_primary
    ├── is_active
    └── last_tested_at

Match
├── id
├── client_id (FK)
├── keyword_id (FK)
├── content_id (reddit post/comment id)
├── content_type (post/comment)
├── subreddit
├── matched_phrase
├── also_matched[] (other keywords that hit)
├── snippet (200 chars)
├── full_text
├── proximity_score
├── reddit_url
├── reddit_author
├── is_deleted (source deleted flag)
├── detected_at
├── alert_sent_at (null if pending)
├── alert_status (pending/sent/failed)
└── created_at

RedditContent (shared across clients)
├── id
├── reddit_id
├── subreddit
├── content_type
├── title
├── body
├── author
├── normalized_text
├── content_hash (for dedup)
├── reddit_created_at
├── fetched_at
└── is_deleted
```

---

## Multi-Tenancy Model

All clients share infrastructure:

```
Shared Reddit Poller
        │
        ▼
┌───────────────────────────────────────┐
│           Shared Database             │
│  ┌─────────┐ ┌─────────┐ ┌─────────┐ │
│  │Client A │ │Client B │ │Client C │ │
│  │Keywords │ │Keywords │ │Keywords │ │
│  │Matches  │ │Matches  │ │Matches  │ │
│  └─────────┘ └─────────┘ └─────────┘ │
└───────────────────────────────────────┘
```

- Every query filters by client_id
- Reddit is polled once per subreddit, results fan out to relevant clients
- Efficient: 10 clients watching r/entrepreneur = 1 poll, 10 match checks

---

## Implementation Order

1. Data models — SQLAlchemy models, migrations
2. Text normalizer — Standalone module with tests
3. Proximity matcher — Standalone module with tests
4. Reddit poller — PRAW integration, content storage
5. Deduplicator — Hash-based skip logic
6. Match engine — Connect content to keywords
7. Alert dispatcher — Discord webhook sender
8. REST API — FastAPI endpoints
9. Background worker — Scheduled polling + matching
10. Frontend — Next.js dashboard with wizard

---

## Build Status

**All 3 phases + Discord OAuth2 complete. 241 tests passing, 0 failures.**

### Phase 1 — Foundation (67 tests)

| Component | File | Tests |
|-----------|------|-------|
| Text normalizer | `backend/app/services/normalizer.py` | 26 |
| Proximity matcher | `backend/app/services/matcher.py` | 32 |
| Deduplicator | `backend/app/services/deduplicator.py` | 9 |
| DB models (6 tables) | `backend/app/models/` | — |
| Alembic migration | `backend/alembic/versions/001_initial_schema.py` | — |
| Project scaffolding | `.gitignore`, `docker-compose.yml`, Dockerfiles, configs | — |

### Phase 2 — Core Engine (52 tests)

| Component | File | Tests |
|-----------|------|-------|
| Reddit poller | `backend/app/services/poller.py` | 14 |
| Match engine | `backend/app/services/match_engine.py` | 8 |
| Alert dispatcher | `backend/app/services/alert_dispatcher.py` | 17 |
| Match engine | `backend/app/services/match_engine.py` | 8 |

### Phase 3 — API + Worker + Frontend + Security (106 tests)

| Component | File | Tests |
|-----------|------|-------|
| REST API (24 routes) | `backend/app/api/` | 47 |
| Security hardening | `backend/app/api/security.py`, `backend/app/api/auth.py` | 38 |
| Background worker | `backend/app/worker/` | 14 |
| Next.js frontend | `frontend/src/` | — |

### Discord OAuth2 Integration (9 tests)

| Component | File | Tests |
|-----------|------|-------|
| Discord OAuth2 endpoints | `backend/app/api/discord.py` | 9 |
| Discord callback page | `frontend/src/app/discord/callback/page.tsx` | — |
| Onboarding "Connect to Discord" | `frontend/src/app/onboarding/page.tsx` | — |

---

## File Map

### Backend — `backend/`

```
backend/
├── app/
│   ├── api/
│   │   ├── __init__.py          # Router exports
│   │   ├── auth.py              # JWT auth, PBKDF2-SHA256 password hashing, Bearer token validation
│   │   ├── clients.py           # POST /api/auth/register, POST /api/auth/login, GET/PATCH /api/clients/me
│   │   ├── discord.py           # GET /api/discord/auth-url, POST /api/discord/callback (OAuth2 webhook setup)
│   │   ├── keywords.py          # CRUD /api/keywords (soft delete)
│   │   ├── subreddits.py        # CRUD /api/subreddits (duplicate detection)
│   │   ├── webhooks.py          # CRUD /api/webhooks + POST test
│   │   ├── matches.py           # GET /api/matches (paginated + filters)
│   │   ├── stats.py             # GET /api/stats (analytics)
│   │   ├── schemas.py           # Pydantic v2 request/response models + validators
│   │   └── security.py          # Security utilities (SSRF prevention, input sanitization)
│   ├── models/
│   │   ├── base.py              # DeclarativeBase, UUID mixin, timestamp mixin
│   │   ├── clients.py           # Client model
│   │   ├── keywords.py          # Keyword model (ARRAY phrases/exclusions)
│   │   ├── subreddits.py        # MonitoredSubreddit model
│   │   ├── webhooks.py          # WebhookConfig model
│   │   ├── content.py           # RedditContent model
│   │   └── matches.py           # Match model (AlertStatus enum)
│   ├── services/
│   │   ├── normalizer.py        # Text normalization (URLs, markdown, whitespace)
│   │   ├── matcher.py           # Proximity matching (OR groups, negations, stemming)
│   │   ├── poller.py            # Reddit polling via PRAW
│   │   ├── deduplicator.py      # SHA256 content hashing + duplicate check
│   │   ├── match_engine.py      # Multi-client fan-out matching
│   │   └── alert_dispatcher.py  # Discord webhook dispatch + batching + retry
│   ├── worker/
│   │   ├── main.py              # APScheduler entry point
│   │   ├── pipeline.py          # Poll → Match → Alert pipeline
│   │   └── retention.py         # 90-day data cleanup
│   ├── database.py              # SQLAlchemy engine + session factory
│   └── main.py                  # FastAPI app (CORS, routers, error handler)
├── tests/
│   ├── conftest.py              # Shared SQLite ARRAY adapter
│   ├── test_normalizer.py       # 26 tests
│   ├── test_matcher.py          # 32 tests
│   ├── test_deduplicator.py     # 9 tests
│   ├── test_poller.py           # 14 tests
│   ├── test_match_engine.py     # 8 tests
│   ├── test_alert_dispatcher.py # 17 tests
│   ├── test_api.py              # 47 tests (all endpoints + auth + isolation)
│   ├── test_discord.py          # 9 tests (OAuth2 auth-url + callback)
│   ├── test_security.py         # 30 tests (password hashing, JWT auth, validation, SSRF, CORS)
│   └── test_worker.py           # 14 tests
├── alembic/                     # Database migrations
├── requirements.txt
├── pyproject.toml
└── Dockerfile
```

### Frontend — `frontend/`

```
frontend/
├── src/
│   ├── app/
│   │   ├── page.tsx             # Landing / login page
│   │   ├── layout.tsx           # Root layout with Navbar
│   │   ├── globals.css          # Tailwind base styles
│   │   ├── dashboard/page.tsx   # Stats dashboard (match counts, top keywords/subs)
│   │   ├── onboarding/page.tsx  # 4-step wizard (webhook via Discord OAuth2 or manual → subreddits → keywords → confirm)
│   │   ├── discord/callback/page.tsx  # Discord OAuth2 redirect handler
│   │   ├── keywords/page.tsx    # Keyword CRUD (phrases, exclusions, proximity config)
│   │   ├── subreddits/page.tsx  # Subreddit manager (add/remove, status badges)
│   │   ├── webhooks/page.tsx    # Webhook manager (add, test, set primary)
│   │   ├── matches/page.tsx     # Match feed with filtering + pagination
│   │   └── settings/page.tsx    # Client settings (polling interval, email)
│   ├── components/
│   │   ├── Navbar.tsx           # Navigation bar with active link highlighting
│   │   ├── AuthGuard.tsx        # Redirects unauthenticated users to login
│   │   ├── ChipInput.tsx        # Enter-to-add tag input for phrases
│   │   ├── StatusBadge.tsx      # Color-coded status indicators
│   │   ├── MatchCard.tsx        # Match display card with snippet + metadata
│   │   ├── StatCard.tsx         # Metric card for dashboard
│   │   ├── StepIndicator.tsx    # Progress steps for onboarding wizard
│   │   └── EmptyState.tsx       # Placeholder for empty lists
│   └── lib/
│       ├── api.ts               # API client (apiFetch, typed endpoints)
│       └── auth.ts              # localStorage JWT token management
├── package.json
├── tailwind.config.ts
├── tsconfig.json
└── Dockerfile
```

### API Routes (24 total)

| Method | Endpoint | Auth | Description |
|--------|----------|------|-------------|
| POST | `/api/auth/register` | No | Register with email + password, returns JWT |
| POST | `/api/auth/login` | No | Login with email + password, returns JWT |
| GET | `/api/clients/me` | Yes | Get current client info |
| PATCH | `/api/clients/me` | Yes | Update email / polling interval |
| GET | `/api/keywords` | Yes | List active keywords |
| POST | `/api/keywords` | Yes | Create keyword (phrases, exclusions, proximity) |
| GET | `/api/keywords/{id}` | Yes | Get single keyword |
| PATCH | `/api/keywords/{id}` | Yes | Update keyword fields |
| DELETE | `/api/keywords/{id}` | Yes | Soft-delete keyword |
| GET | `/api/subreddits` | Yes | List monitored subreddits |
| POST | `/api/subreddits` | Yes | Add subreddit (duplicate check, r/ strip) |
| PATCH | `/api/subreddits/{id}` | Yes | Update subreddit settings |
| DELETE | `/api/subreddits/{id}` | Yes | Stop monitoring subreddit |
| GET | `/api/discord/auth-url` | Yes | Get Discord OAuth2 authorization URL + CSRF state |
| POST | `/api/discord/callback` | Yes | Exchange Discord auth code for webhook, save to DB |
| GET | `/api/webhooks` | Yes | List webhooks |
| POST | `/api/webhooks` | Yes | Add Discord webhook (SSRF validated) |
| PATCH | `/api/webhooks/{id}` | Yes | Update webhook (set primary) |
| DELETE | `/api/webhooks/{id}` | Yes | Remove webhook |
| POST | `/api/webhooks/{id}/test` | Yes | Test webhook delivery |
| GET | `/api/matches` | Yes | List matches (paginated, filterable) |
| GET | `/api/matches/{id}` | Yes | Get single match detail |
| GET | `/api/stats` | Yes | Dashboard analytics |
| GET | `/health` | No | Health check |

### Security Features

- **Password hashing**: PBKDF2-SHA256 with random salt (timing-attack resistant)
- **JWT auth**: HS256 tokens with 24h expiry, `Authorization: Bearer` header
- **CORS lockdown**: Only allows `http://localhost:3000` (configurable via `CORS_ORIGINS` env)
- **SSRF prevention**: Webhook URLs must match Discord webhook pattern only
- **Input validation**: Subreddit name regex, phrase length limits, angle bracket sanitization
- **Client isolation**: All queries filter by `client_id`, tested with cross-client assertions
- **Error safety**: Global exception handler prevents stack trace / path leakage
- **No plaintext secrets**: Passwords hashed before storage, JWT secret via `JWT_SECRET` env var
