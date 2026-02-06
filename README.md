# Reddalert

Reddit monitoring and alerting service for Discord-based businesses. Tracks keyword mentions across subreddits and pushes alerts to Discord webhooks.

## Quick Start

### Prerequisites

- Python 3.11+
- Node.js 18+
- PostgreSQL 16 (or use Docker)

### Using Docker

```bash
docker-compose up -d
```

This starts PostgreSQL, the FastAPI backend (port 8000), the background worker, and the Next.js frontend (port 3000).

### Manual Setup

**Backend:**

```bash
cd backend
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env  # edit with your values
alembic upgrade head
uvicorn app.main:app --reload
```

**Frontend:**

```bash
cd frontend
npm install
cp .env.example .env.local  # edit with your values
npm run dev
```

## Project Structure

```
/backend        Python FastAPI application
/frontend       Next.js + React + Tailwind dashboard
docker-compose.yml
```
