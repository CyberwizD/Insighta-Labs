# Insighta Labs+

Insighta Labs+ is a Python implementation of the updated Stage 3 backend engineering task. It upgrades the Stage 2 profile intelligence system into a secured product with:

- GitHub OAuth authentication with PKCE-aware CLI login
- access and refresh token lifecycle management
- role-based access control for `admin` and `analyst`
- protected versioned APIs
- a globally installable CLI
- a server-rendered web portal using HTTP-only cookies
- rate limiting, request logging, CSRF protection, and README/CI scaffolding

## Important Note

This implementation is organized as a single workspace for local development in the directory you provided. The Stage 3 brief asks for separate backend, CLI, and web repositories for final submission/deployment. The code here cleanly separates those concerns at the application level, but you will still need to split them into separate repos if that is a submission requirement.

## What Is Implemented

### Authentication

- `GET /auth/github`
- `GET /auth/github/callback`
- `POST /auth/refresh`
- `POST /auth/logout`

Two auth modes are supported:

1. Real GitHub OAuth with `INSIGHTA_GITHUB_CLIENT_ID` and `INSIGHTA_GITHUB_CLIENT_SECRET`
2. A local mock GitHub provider for end-to-end testing without external setup

### Token Strategy

- Access token TTL: `3 minutes`
- Refresh token TTL: `5 minutes`
- Refresh tokens are stored server-side and revoked on logout
- Refresh token rotation is enforced immediately on `POST /auth/refresh`
- CLI retries protected API calls after refreshing expired access tokens

### User System

The `users` table includes:

- `id`
- `github_id`
- `username`
- `email`
- `avatar_url`
- `role`
- `is_active`
- `last_login_at`
- `created_at`
- `updated_at`

If `is_active` is false, authenticated requests are rejected with `403`.

### Roles

- `admin`
  - create profiles
  - delete profiles
  - list, search, and read profiles
- `analyst`
  - list, search, and read profiles only

Default role is `analyst`, unless the username matches one of `INSIGHTA_ADMIN_USERNAMES`.

### Versioned API Contract

All `/api/*` endpoints require:

```text
X-API-Version: 1
```

Requests without that header return:

```json
{
  "status": "error",
  "message": "API version header required"
}
```

### Profile APIs

- `GET /api/users/me`
- `GET /api/profiles`
- `GET /api/profiles/search`
- `GET /api/profiles/{id}`
- `POST /api/profiles`
- `DELETE /api/profiles/{id}`
- `GET /api/profiles/export?format=csv`

Supported profile query features:

- filtering by `gender`, `country`, `country_id`, `age_group`
- range filtering with `min_age` and `max_age`
- probability filters with `min_gender_probability` and `min_country_probability`
- sorting by `created_at`, `age`, `name`, `gender_probability`, `country_probability`
- pagination with `page`, `limit`, `total`, `total_pages`, and `links`
- natural language search

### CSV Export

`GET /api/profiles/export?format=csv` supports the same filters and sorting params as `GET /api/profiles`.

CSV columns:

```text
id,name,gender,gender_probability,age,age_group,country_id,country_name,country_probability,created_at
```

### CLI

The CLI is installed as:

```bash
insighta
```

Commands:

```bash
insighta login
insighta logout
insighta whoami

insighta profiles list
insighta profiles list --gender male
insighta profiles list --country NG --age-group adult
insighta profiles list --min-age 25 --max-age 40
insighta profiles list --sort-by age --order desc
insighta profiles list --page 2 --limit 20

insighta profiles get <id>
insighta profiles search "young males from nigeria"
insighta profiles create --name "Harriet Tubman"
insighta profiles export --format csv
insighta profiles export --format csv --gender male --country NG
```

CLI tokens are stored at:

```text
~/.insighta/credentials.json
```

### Web Portal

Pages:

- `/web/login`
- `/web/dashboard`
- `/web/profiles`
- `/web/profiles/{id}`
- `/web/search`
- `/web/account`

Security:

- access and refresh tokens are stored in HTTP-only cookies
- CSRF protection is included for the web logout form
- cookie-backed web sessions are enforced at route boundaries

### Rate Limiting and Logging

- `/auth/*`: 10 requests per minute per client IP
- all other non-static routes: 60 requests per minute per user/IP
- every request logs:
  - method
  - endpoint
  - status code
  - response time

## Running Locally

### 1. Create and activate a virtual environment

```bash
py -3 -m venv .venv
```

PowerShell:

```powershell
.\.venv\Scripts\Activate.ps1
```

### 2. Install dependencies

```bash
py -3 -m pip install -e .
```

### 3. Configure environment

At minimum:

```powershell
$env:INSIGHTA_SECRET_KEY="change-me-to-a-long-random-secret-key"
$env:INSIGHTA_ENABLE_MOCK_GITHUB="true"
$env:INSIGHTA_APP_BASE_URL="http://127.0.0.1:8000"
```

For real GitHub OAuth:

```powershell
$env:INSIGHTA_GITHUB_CLIENT_ID="your-client-id"
$env:INSIGHTA_GITHUB_CLIENT_SECRET="your-client-secret"
```

### 4. Start the app

```bash
py -3 -m uvicorn app.main:app --reload
```

### 5. Open the web portal

```text
http://127.0.0.1:8000/web/login
```

### 6. Use the CLI

```bash
insighta login --api-url http://127.0.0.1:8000
insighta whoami --api-url http://127.0.0.1:8000
insighta profiles list --api-url http://127.0.0.1:8000 --gender male
```

## End-to-End Authentication Flow

### Web Flow

1. User opens `/web/login`
2. Browser visits `GET /auth/github`
3. Backend redirects to GitHub or the mock provider
4. Provider redirects to `GET /auth/github/callback`
5. Backend upserts the user, issues tokens, sets cookies, sets a CSRF token, and redirects to `/web/dashboard`

### CLI Flow

1. User runs `insighta login`
2. CLI generates `state`, `code_verifier`, and `code_challenge`
3. CLI starts a temporary localhost callback server
4. Browser opens `GET /auth/github?mode=cli...`
5. Provider redirects to the local callback server
6. CLI forwards `code`, `state`, and `code_verifier` to `GET /auth/github/callback?mode=cli`
7. Backend returns `access_token` and `refresh_token`
8. CLI stores credentials in `~/.insighta/credentials.json`

## Natural Language Parsing Approach

The search path first tries to interpret structured intent from phrases such as:

- `young males`
- `females above 30`
- `adult males from kenya`
- `people from nigeria`

It extracts:

- gender
- country
- age group
- min/max age rules

If no structured intent is found, it falls back to direct name/country matching. If the query still cannot be interpreted into a meaningful result, the API returns a standardized error.

## Role Enforcement Approach

Role enforcement is centralized:

- authentication is resolved from bearer tokens or HTTP-only cookies
- the current user is loaded once at the route boundary
- inactive users are blocked early
- write operations call `require_role(user, "admin")`

This keeps permission logic consistent and avoids scattered authorization checks.

## CI

A GitHub Actions workflow is included at:

```text
.github/workflows/ci.yml
```

It runs on PRs to `main` and performs:

- dependency installation
- source compilation
- import/build sanity checks

## Verification Performed

The implementation was verified locally with:

```bash
py -3 -m py_compile app\config.py app\database.py app\ids.py app\models.py app\auth.py app\http_runtime.py app\profiles.py app\main.py cli.py run.py
```

Manual smoke tests were also run for:

- mock OAuth login
- admin profile creation
- analyst access restrictions
- API version header enforcement
- refresh token rotation
- CSV export
- CLI `whoami`, `profiles list`, and `profiles export`
