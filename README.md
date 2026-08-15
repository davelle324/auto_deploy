# Auto Deploy

A self-hosted web app for deploying websites to Vercel, Netlify, and Render from a single dashboard. Store your platform API tokens once, then create projects and deployments through one interface.

## Features

- Deploy static sites and web apps to **Vercel**, **Netlify**, or **Render**
- Optionally connect a **GitHub repo** for continuous deployment
- Encrypted token storage (Fernet + SHA-256 key derivation)
- Dashboard to view all deployments across platforms
- FastAPI JSON API with auto-generated docs at `/docs`

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

Generate a secret key:
```bash
python -c "import secrets; print(secrets.token_hex(32))"
```

## Usage

```bash
uvicorn main:app --reload
```

Open [http://localhost:8000](http://localhost:8000).

1. Go to **Settings** and add your API tokens for each platform
2. Go to **New Deployment**, choose a platform and project name
3. Optionally paste a GitHub repo URL for auto-deployment on push
4. View all deployments on the **Dashboard**

### Getting API Tokens

| Platform | Where to generate |
|----------|------------------|
| Vercel | Account Settings → Tokens |
| Netlify | User Settings → Applications → Personal access tokens |
| Render | Account Settings → API Keys |

## API Reference

The full OpenAPI spec is available at `/docs` (Swagger UI) and `/redoc`.

| Endpoint | Method | Description |
|----------|--------|-------------|
| `/api/tokens/` | `POST` | Store or update a platform token |
| `/api/tokens/` | `GET` | List configured/unconfigured platforms |
| `/api/tokens/{platform}` | `DELETE` | Remove a platform token |
| `/api/deployments/` | `POST` | Create a new deployment |
| `/api/deployments/` | `GET` | List all deployments (filter with `?platform=vercel`) |
| `/api/deployments/{id}` | `GET` | Get a single deployment |

## Running Tests

```bash
python -m pytest tests/ -v
```

## Notes on Free Tiers

- **Vercel**: No deploy limits on the Hobby (free) plan
- **Netlify**: ~20 production deploys/month on the free plan (branch deploys are free)
- **Render**: Static sites are free and unlimited; web services sleep after 15 min of inactivity
- **Render static sites require a GitHub repo** — Render's API does not support direct file upload
