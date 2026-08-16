# Auto Deploy

A self-hosted web dashboard for deploying and managing websites across Vercel, Netlify, and Render from one interface. Store your platform API tokens once, then create, monitor, and manage all your projects from a single dashboard.

## Features

### Deployment Management
- Deploy static sites and web apps to **Vercel**, **Netlify**, or **Render**
- Optionally connect a **GitHub repo** for continuous deployment on push
- **Import** existing platform projects into the dashboard
- **Redeploy** any project with one click
- **Sync status** from the platform API on demand
- **Bulk sync** all deployments at once with the "↻ Sync All" button
- **Delete** a project on the platform, or **remove from tracking** without touching the platform

### Observability
- **Build logs** — view recent build output for any deployment in a modal
- **Deploy history** — timeline of every triggered deployment with status and timestamp
- **Live status polling** — in-progress builds auto-refresh every 5 seconds

### Configuration
- **Environment variables** — list, add, update, and delete env vars on any deployment
- **Custom domains** — list, add, and remove custom domains per deployment
- **Build Config (Render)** — set build command and CORS headers on Render static sites via the 🔧 Build Config button (Render ignores `render.yaml` for API-created services; this applies settings directly via `PATCH /services/{id}`)

### Dashboard
- **Search** — filter deployments by name, status, platform, URL, or repo
- **Platform filter** — multi-select dropdown to show only Vercel / Netlify / Render
- **Project groups** — organise deployments into collapsible project sections
- **Dark mode** — system-aware, manually toggleable
- **Stats widgets** — total deployments and live count at a glance

### Automation
- **Webhooks** — receive build status events from all three platforms at `/api/webhook/{platform}` to auto-update deployment status without polling
- **HMAC verification** — webhook signatures validated when `WEBHOOK_SECRET` is set

### Security
- Encrypted token storage (Fernet + SHA-256 key derivation)
- Tokens never returned in API responses

## Installation

```bash
git clone <repo-url>
cd auto_deploy
pip install -r requirements.txt
cp .env.example .env
# Edit .env and set SECRET_KEY to a random string
```

## Configuration

| Variable | Default | Description |
|----------|---------|-------------|
| `SECRET_KEY` | *(required)* | Random secret used to encrypt stored API tokens |
| `DATABASE_URL` | `sqlite+aiosqlite:///./auto_deploy.db` | SQLite database path |
| `DEBUG` | `false` | Enable SQLAlchemy query logging |
| `WEBHOOK_SECRET` | *(optional)* | Shared secret for HMAC-SHA256 webhook signature verification |

Generate a secret key:
```bash
python -c "import secrets; print(secrets.token_hex(32))"
```

## Usage

```bash
uvicorn main:app --reload
```

Open [http://localhost:8000](http://localhost:8000).

1. Go to **Settings** and add your API tokens for each platform you want to use
2. Go to **New Deployment**, choose a platform and project name
3. Optionally paste a GitHub repo URL for auto-deployment on push
4. View and manage all deployments on the **Dashboard**

### Getting API Tokens

| Platform | Where to generate |
|----------|------------------|
| Vercel | Account Settings → Tokens |
| Netlify | User Settings → Applications → Personal access tokens |
| Render | Account Settings → API Keys |

### Setting Up Webhooks (optional)

Register these URLs in your platform dashboard to receive automatic status updates:

| Platform | Webhook URL |
|----------|------------|
| Vercel | `https://your-host/api/webhook/vercel` |
| Netlify | `https://your-host/api/webhook/netlify` |
| Render | `https://your-host/api/webhook/render` |

Set `WEBHOOK_SECRET` in `.env` to the same value you configure in the platform webhook settings to enable HMAC signature verification.

## API Reference

The full OpenAPI spec is at `/docs` (Swagger UI) and `/redoc`.

### Tokens
| Endpoint | Method | Description |
|----------|--------|-------------|
| `/api/tokens/` | `POST` | Store or update a platform token |
| `/api/tokens/` | `GET` | List configured platforms |
| `/api/tokens/{platform}` | `DELETE` | Remove a platform token |

### Deployments
| Endpoint | Method | Description |
|----------|--------|-------------|
| `/api/deployments/` | `POST` | Create a new deployment |
| `/api/deployments/` | `GET` | List all deployments (`?platform=vercel` to filter) |
| `/api/deployments/{id}` | `GET` | Get a single deployment |
| `/api/deployments/{id}` | `DELETE` | Delete on platform + remove from DB |
| `/api/deployments/{id}/untrack` | `DELETE` | Remove from DB only (platform untouched) |
| `/api/deployments/{id}/sync` | `POST` | Refresh status from platform API |
| `/api/deployments/{id}/redeploy` | `POST` | Trigger a new deployment |
| `/api/deployments/{id}/repo` | `PATCH` | Connect a GitHub repo |
| `/api/deployments/{id}/project` | `PATCH` | Assign to an internal project group |
| `/api/deployments/{id}/logs` | `GET` | Fetch build log lines |
| `/api/deployments/{id}/history` | `GET` | List deploy events (most recent first) |
| `/api/deployments/{id}/build` | `PATCH` | Set build command + CORS headers (Render only) |
| `/api/deployments/import/{platform}` | `POST` | Import existing platform projects |

### Environment Variables
| Endpoint | Method | Description |
|----------|--------|-------------|
| `/api/deployments/{id}/env` | `GET` | List env vars |
| `/api/deployments/{id}/env` | `PUT` | Add or update env vars |
| `/api/deployments/{id}/env/{key}` | `DELETE` | Delete an env var by key |

### Domains
| Endpoint | Method | Description |
|----------|--------|-------------|
| `/api/deployments/{id}/domains` | `GET` | List custom domains |
| `/api/deployments/{id}/domains` | `POST` | Add a custom domain |
| `/api/deployments/{id}/domains/{domain}` | `DELETE` | Remove a custom domain |

### Projects
| Endpoint | Method | Description |
|----------|--------|-------------|
| `/api/projects/` | `POST` | Create a project group |
| `/api/projects/` | `GET` | List all project groups |
| `/api/projects/{id}` | `DELETE` | Delete a project group |

### Webhooks
| Endpoint | Method | Description |
|----------|--------|-------------|
| `/api/webhook/vercel` | `POST` | Receive Vercel deployment events |
| `/api/webhook/netlify` | `POST` | Receive Netlify deploy events |
| `/api/webhook/render` | `POST` | Receive Render service events |

## Running Tests

```bash
python -m pytest tests/ -v
```

## Notes on Free Tiers

- **Vercel**: No deploy limits on the Hobby (free) plan
- **Netlify**: ~20 production deploys/month on the free plan (branch deploys are free)
- **Render**: Static sites are free and unlimited; web services sleep after 15 min of inactivity
- **Render static sites require a GitHub repo** — Render's API does not support direct file upload

## Platform-Specific Notes

- **Vercel git deployments** require the [Vercel GitHub App](https://vercel.com/docs/deployments/git/vercel-for-github) to be installed and granted access to the repo
- **Netlify env vars** — the API shape differs between personal and team accounts; listing may return a dict or array depending on account type
- **Render logs** — fetched from `/services/{id}/logs`; may be empty if no deploy has run yet
- **Render `render.yaml`** — ignored for services created via the API. Use the 🔧 Build Config modal to apply build commands and CORS headers programmatically; redeploy after applying to activate changes
