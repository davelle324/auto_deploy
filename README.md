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
- **Type tagging** — mark each deployment as `static` or `backend`; auto-detected on import

### Observability
- **Build logs** — view recent build output for any deployment in a modal
- **Deploy history** — timeline of every triggered deployment with status and timestamp
- **Last deployed** — relative timestamp ("2h ago") on every card with hover for the full date
- **Ping / uptime** — HTTP-check any deployment URL and see response time; ping an entire project at once
- **Live status polling** — in-progress builds auto-refresh every 5 seconds
- **Browser notifications** — get a notification when a deployment finishes or fails (requires permission)

### Configuration
- **Environment variables** — list, add, update, and delete env vars on any deployment
- **Custom domains** — list, add, and remove custom domains per deployment
- **Build Config (Render)** — set build command and CORS headers on Render static sites via the 🔧 Build Config button (Render ignores `render.yaml` for API-created services; this applies settings directly via `PATCH /services/{id}`)
- **Notes** — attach personal notes to any deployment; saved on blur

### Dashboard
- **Search** — filter deployments by name, status, platform, URL, or repo
- **Filters & Sort** — collapsible panel with platform checkboxes, project/type selectors, and sort options (name, status, newest, oldest, last deployed)
- **Project groups** — organise deployments into collapsible project sections with per-project sync/deploy/ping buttons
- **Unassigned section** — unassigned deployments shown as a collapsible section with the same bulk actions as projects
- **Dark mode** — system-aware, manually toggleable
- **Stats widgets** — total deployments, live count, and failing count at a glance

### Automation
- **Webhooks** — receive build status events from all three platforms at `/api/webhook/{platform}` to auto-update deployment status without polling
- **HMAC verification** — webhook signatures validated when `WEBHOOK_SECRET` is set
- **Auto-refresh** — optional 60-second background refresh toggle on the dashboard

### Security
- Encrypted token storage (Fernet + SHA-256 key derivation)
- Tokens never returned in API responses
- Optional single-password login (`APP_PASSWORD`) with session cookies (1-hour expiry)
- **Demo mode** at `/demo` — fully functional UI backed by fake data; real `/api/*` routes remain blocked to unauthenticated users

## Installation

```bash
git clone <repo-url>
cd auto_deploy
pip install -e ".[dev]"
cp .env.example .env
# Edit .env and set SECRET_KEY to a random string
```

## Configuration

| Variable | Default | Description |
|----------|---------|-------------|
| `SECRET_KEY` | *(required)* | Random secret used to encrypt stored API tokens and sign session cookies |
| `APP_PASSWORD` | *(empty — auth disabled)* | Password for the login page. Set this before deploying publicly |
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
| `/api/deployments/{id}/type` | `PATCH` | Set deployment type (`static` / `backend`) |
| `/api/deployments/{id}/notes` | `PATCH` | Update personal notes |
| `/api/deployments/{id}/ping` | `GET` | HTTP-check the deployment URL |
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

## Deploying to Fly.io

Fly.io hosts the app on their servers so it runs 24/7 without your computer needing to be on. You get a public URL (e.g. `https://your-app.fly.dev`) protected by the login password you set.

https://auto-deploy.fly.dev/

### First-time setup

**1. Install the Fly CLI and log in**
```bash
# macOS
brew install flyctl

# Windows / Linux
curl -L https://fly.io/install.sh | sh

fly auth login
```

**2. Push your code to GitHub** (Fly.io deploys from your local directory, but having it on GitHub is good practice)

**3. Launch the app** (run once from the project directory)
```bash
fly launch --region <region-code>
```
When prompted:
- Choose an app name (or accept the generated one)
- Say **no** to adding a PostgreSQL database
- Say **no** to deploying now (you need to set up the volume first)

Common region codes (there is no Boston — pick the closest):

| Code | Location |
|------|----------|
| `ewr` | Secaucus, NJ (closest to Boston/NYC) |
| `iad` | Ashburn, VA (US East default) |
| `ord` | Chicago, IL |
| `lax` | Los Angeles, CA |
| `lhr` | London, UK |
| `fra` | Frankfurt, DE |

**4. Create a persistent volume for the SQLite database**
```bash
fly volumes create auto_deploy_data -r <region-code> -n 1
```
Use the same region code you passed to `fly launch` (e.g. `ewr`). The `-n 1` flag specifies one volume — Fly.io requires this exact syntax; `--size` and `--region` are not accepted in newer CLI versions.

**5. Add the volume mount to `fly.toml`** — open the generated `fly.toml` and add:
```toml
[mounts]
  source = "auto_deploy_data"
  destination = "/app/data"
```

Also ensure the `[[vm]]` section has `count = 1` to prevent Fly from spinning up multiple machines (SQLite only works on a single machine):
```toml
[[vm]]
  memory = '1gb'
  cpu_kind = 'shared'
  cpus = 1
  count = 1
```

**6. Set secrets** (these are your environment variables on Fly.io — never commit these)
```bash
fly secrets set SECRET_KEY=$(python -c "import secrets; print(secrets.token_hex(32))")
fly secrets set APP_PASSWORD=choose-a-strong-password
fly secrets set DATABASE_URL=sqlite+aiosqlite:////app/data/auto_deploy.db
```

> **Important:** `DATABASE_URL` must point to the volume path (`/app/data/...`) before you deploy. If you deploy without it, the app uses the container's temporary filesystem and all data is lost on every restart.
>
> Setting secrets does **not** trigger a redeploy — you must run `fly deploy` after.

**7. Deploy**
```bash
fly deploy
```

Your app is now live. Run `fly open` to open it in your browser.

### Updating the app

Any time you make changes, redeploy with:
```bash
fly deploy
```

That's it — Fly.io builds and restarts the app automatically. Your database and data are preserved on the persistent volume.

### Verifying data persists

After entering your API tokens, confirm they're actually stored on the volume:
```bash
fly ssh console
ls -lh /app/data/auto_deploy.db
# Should show a file larger than 4k once tokens are saved
```

A 4k database is empty (just the schema). If the file stays at 4k after saving tokens, `DATABASE_URL` is not pointing to the volume path — double-check `fly secrets list`.

### Avoiding the two-volume problem

Fly.io may create a second machine during a deploy, giving each machine its own separate database. Prevent this by keeping `count = 1` in `fly.toml` (shown in step 5 above). If you already have two volumes, fix it:
```bash
fly volume list          # identify the second volume
fly scale count 1        # reduce to one machine
fly volumes destroy <id> # remove the extra empty volume
fly deploy
```

### Stopping or pausing the app

**Pause** (keeps your data, stops billing for compute — free tier stays free):
```bash
fly scale count 0
```

**Resume** after pausing:
```bash
fly scale count 1
```

**Permanently delete** the app and all its data:
```bash
fly apps destroy your-app-name
```

### Deploying multiple apps

Each app you host on Fly.io is independent. To host a second app, just run `fly launch` inside that project's directory — it gets its own URL, its own volume, and its own secrets. Fly.io's free tier includes 3 VMs, so you can run up to 3 small apps simultaneously for free.

### Changing the URL

By default Fly.io gives you `https://your-app-name.fly.dev`. The name is chosen during `fly launch` — pick something meaningful then (you can't rename an app after the fact without destroying and recreating it).

If you own a custom domain, you can point it to your app:
```bash
fly certs add yourdomain.com
```
Fly.io will give you a DNS record to add at your registrar and handles the SSL certificate automatically.

### How deploys work

`fly deploy` builds and ships whatever is currently saved on your local machine — GitHub is not involved. Your computer just needs to be on long enough to run the command. Once deployed, the app runs on Fly.io's servers 24/7 regardless of whether your computer is on.

### Useful commands

```bash
fly deploy        # push local changes and redeploy
fly logs          # view live app logs
fly status        # check if the app is running
fly ssh console   # open a shell inside the running container
fly open          # open the app URL in your browser
fly secrets list  # see which secrets are set (values are hidden)
fly volume list   # confirm one volume is attached to one machine
```

## Running Tests

```bash
python -m pytest tests/ -v
```

Tests run automatically on every push via GitHub Actions (see `.github/workflows/test.yml`). The deploy workflow only runs if tests pass.

## Notes on Free Tiers

- **Vercel**: No deploy limits on the Hobby (free) plan
- **Netlify**: ~20 production deploys/month on the free plan (branch deploys are free)
- **Render**: Static sites are free and unlimited; web services sleep after 15 min of inactivity
- **Render static sites require a GitHub repo** — Render's API does not support direct file upload

## Platform-Specific Notes

- **Vercel git deployments** require the [Vercel GitHub App](https://vercel.com/docs/deployments/git/vercel-for-github) to be installed and granted access to the repo
- **Netlify deployments via API** require the [Netlify GitHub App](https://docs.netlify.com/configure-builds/repo-permissions-linking/) to be installed on the repo before git-triggered builds will work
- **Netlify env vars** — the API shape differs between personal and team accounts; listing may return a dict or array depending on account type
- **Render logs** — fetched from `/services/{id}/logs`; may be empty if no deploy has run yet
- **Render `render.yaml`** — ignored for services created via the API. Use the 🔧 Build Config modal to apply build commands and CORS headers programmatically; redeploy after applying to activate changes
