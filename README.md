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

## Environment Variables

| Variable | Description | Default |
|---|---|---|
| `DATABASE_URL` | PostgreSQL connection string | `postgresql://reddalert:reddalert@db:5432/reddalert` |
| `JWT_SECRET` | Secret key for JWT tokens | (required) |
| `REDDIT_CLIENT_ID` | Reddit API client ID | (required) |
| `REDDIT_CLIENT_SECRET` | Reddit API client secret | (required) |
| `REDDIT_USER_AGENT` | Reddit API user agent | `reddalert/1.0` |
| `CORS_ORIGINS` | Allowed CORS origins | `http://localhost:3000` |
| `POLL_INTERVAL_MINUTES` | Minutes between poll cycles | `5` |
| `RETENTION_DAYS` | Days to retain old content | `30` |
| `NEXT_PUBLIC_API_URL` | Backend API URL for frontend | `http://localhost:8000` |

## Production Deployment

### Docker Compose

1. Copy and configure your environment file:
   ```bash
   cp backend/.env.example backend/.env
   ```
2. Edit `backend/.env` with your production values (set a strong `JWT_SECRET`, add Reddit API credentials, etc.).
3. Build and start all services:
   ```bash
   docker-compose up -d --build
   ```
4. Services automatically run Alembic migrations on startup before the backend and worker begin serving requests.

### Railway Deployment

1. Link your GitHub repository to a new Railway project.
2. Set the required environment variables (`DATABASE_URL`, `JWT_SECRET`, `REDDIT_CLIENT_ID`, `REDDIT_CLIENT_SECRET`) in the Railway dashboard.
3. Deploy. Railway will use the `railway.toml` configuration to build from the backend Dockerfile and configure health checks automatically.
