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
| Auth               | API key for v1          |
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

- Auth: API key validation per request
- Endpoints:
  - `POST /clients` — create client
  - `GET/POST/DELETE /keywords` — manage keyword phrases
  - `GET/POST/DELETE /subreddits` — manage monitored subs
  - `GET/POST /webhooks` — manage Discord webhooks
  - `GET /matches` — retrieve match history
  - `GET /stats` — basic analytics
- Validation: Subreddit existence check, webhook test on creation

### 7. Next.js Dashboard

- Onboarding wizard: Webhook → Subreddits → Keywords → Done
- Keyword manager: Add phrases with enter-to-add UI, exclusions, proximity config
- Subreddit manager: Add subs, see suggestions based on keywords, status indicators
- Match feed: Recent matches with filtering
- Settings: Polling interval, notification preferences, backup email

---

## Data Model

```
Client
├── id (uuid)
├── api_key (hashed)
├── email (backup contact)
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
