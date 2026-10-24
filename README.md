# Kings Portal Global (KP Global) — Django website, dashboards and mobile API

The original static HTML/CSS/JS site, converted to a Django project:

* **Public website + role-based dashboards**: normal Django views, URLs, forms and templates (template inheritance, server-side validation).
* **Mobile API** for the Expo/React Native app: Django REST Framework under `/api/v1/`, JWT auth (SimpleJWT).
* Both use the **same models, database and business logic** (`church/services.py`, `sermons/youtube.py`, …).

## Project layout

| App | Purpose |
|---|---|
| `kingsportal/` | settings, root URLs |
| `core/` | public pages (home, about, events, ministries, locations, prayer, praise, devotionals, contact, give…), site settings |
| `accounts/` | custom `User` (roles), `Profile`, signals, login/register/profile/password reset, access helpers |
| `church/` | branches, ministries, members, workers, worker applications, events, announcements, devotionals, notifications, prayer, praise, giving, stories + all dashboards |
| `sermons/` | YouTube Data API service, caching, live-stream detection, sermon pages + dashboard |
| `bible/` | Bible JSON translation management (Super Admin only) |
| `api/` | DRF serializers/viewsets/routers for the mobile app |
| `templates/website/` | your original public pages, now Django templates extending `base.html` |
| `templates/dashboard/` | your original `admin/*.html` pages, now Django templates extending `base.html` |
| `templates/accounts/` | login (your original admin login design), register, profile, password reset |
| `static/site/`, `static/dashboard/` | your original `assets/` and `admin/assets/` (CSS/JS/images) |

## Setup

```bash
python -m venv .venv && source .venv/bin/activate      # Windows: .venv\Scripts\activate
pip install -r requirements.txt
cp .env.example .env                                   # then edit it
```

### PostgreSQL

```sql
CREATE USER kingsportal WITH PASSWORD 'change-me';
CREATE DATABASE kingsportal OWNER kingsportal;
```
Put the same values in `.env` (`DB_NAME`, `DB_USER`, `DB_PASSWORD`, `DB_HOST`, `DB_PORT`).
For a quick throwaway run without PostgreSQL you may set `USE_SQLITE=1`.

### Migrations, superuser, run

The project uses a **custom user model** (`accounts.User`), so generate migrations *before* the first `migrate`:

```bash
python manage.py makemigrations accounts core church sermons bible
python manage.py migrate
python manage.py createsuperuser        # asks for username, email, password
python manage.py check
python manage.py runserver
```
Commit the generated `*/migrations/*.py` files afterwards.

* Website: http://127.0.0.1:8000/ · Sign in: `/accounts/login/` · Dashboards: `/portal/`
* Django admin: `/django-admin/` · API root: `/api/v1/`

### Tests

```bash
python manage.py test
```
Covers: profile signals, registration, branch relationships, role/branch permissions (website and API), worker applications (no duplicates, scope), YouTube caching/stale fallback/quota/live detection, Bible upload validation, and key API endpoints.

## Environment variables (see `.env.example`)

`DJANGO_SECRET_KEY`, `DJANGO_DEBUG`, `DJANGO_ALLOWED_HOSTS`, `DJANGO_CSRF_TRUSTED_ORIGINS`, `DB_*`, `USE_SQLITE`,
`YOUTUBE_API_KEY`, `YOUTUBE_CHANNEL_ID` (default `UC_ZPT2rA26JsWdO-FnJUhQQ`), `YOUTUBE_CACHE_SECONDS` (900), `YOUTUBE_LIVE_CACHE_SECONDS` (120),
`REDIS_URL` (optional shared cache), `CORS_ALLOWED_ORIGINS`, `JWT_ACCESS_MINUTES`, `JWT_REFRESH_DAYS`, `BIBLE_MAX_UPLOAD_MB`, email settings.
No secret is hardcoded and the YouTube key is only ever used server-side.

## Roles (enforced server-side in views *and* API)

| Role | Can |
|---|---|
| **Super Admin** (`is_superuser` or role) | everything: branches, members, workers, applications, events, content, Bible JSON, settings, giving, prayer/praise |
| **Branch Admin** | only branches in `Branch.admins`: members, workers, events, announcements, notifications, approve/reject applications for those branches. Other branches' records return 404; global content is read-only |
| **Worker** | worker dashboard (updates, sermons, events, devotionals, notifications, assignments), own profile |
| **Member** | member dashboard, notifications, profile, **Apply to Become a Worker** + status tracking |

Self-registration always creates a *Member*. Roles are changed by administrators only (assigning a user as branch admin promotes them; approving an application makes them a worker).

## Sermons and live stream

`sermons/youtube.py` is the single YouTube integration (uploads playlist → `videos.list` for details and `liveStreamingDetails`).
* Sermon pages are cached ~15 min; live status ~2 min; every fresh result also writes a 7-day *stale* copy used when YouTube is down or the quota is exhausted (quota errors pause API calls for 1 hour; other failures back off for 30 s).
* Pagination uses YouTube page tokens, so the archive goes past 50 videos.
* A **LIVE NOW** banner sits above the navbar on every public page, polls `/sermons/live-status/` every 2 minutes and hides itself when the broadcast ends. An "upcoming live" variant shows scheduled streams.
* Live detection checks the 10 latest uploads (cheap: ~2 quota units). If your channel's streams don't appear in the uploads playlist, extend `get_live_status` with a `search.list?eventType=live` call (100 units; cache it).
* Use `REDIS_URL` in production so all workers share the cache (the default per-process memory cache is fine for development).

## Bible JSON management

`/portal/bible/` (Super Admin only): list, upload, replace, delete. Validates `.json` extension, size (`BIBLE_MAX_UPLOAD_MB`), UTF-8, JSON syntax and non-empty content; version names are `[A-Za-z0-9_-]{1,12}`, unique case-insensitively; stored names are generated from the version name (client filenames are ignored) inside `MEDIA_ROOT/bible/`; deletions check the path is inside that directory. `django-cleanup` removes replaced/deleted files.
In production serve `MEDIA_ROOT` with your web server (Django only serves media when `DEBUG=True`).

## Mobile API (`/api/v1/`)

JWT: `Authorization: Bearer <access>`. Lists are paginated (`?page=`, `?page_size=`), searchable (`?search=`), filterable.

| Endpoint | Access |
|---|---|
| `POST auth/register/` · `POST auth/token/` (`email`,`password`) · `POST auth/token/refresh/` | public |
| `GET/PATCH me/` · `POST me/password/` | authenticated |
| `GET branches/` (CRUD for super admin) | public read |
| `members/`, `workers/` | staff only, branch-scoped |
| `worker-applications/` (+ `mine/`, `POST {id}/approve/`, `POST {id}/reject/`) | applicants: create/list own; staff: review within their branches |
| `events/` (+ `upcoming/`) | public read (confirmed); staff write within their branches |
| `announcements/` | authenticated read (own branches + global); staff write |
| `sermons/` (`?page_token=`), `sermons/{video_id}/`, `live/` | public |
| `devotionals/` (+ `today/`) | public |
| `notifications/` (+ `{id}/read/`, `read-all/`, `unread_count/`) | authenticated |
| `bible/versions/` → `[{name, size, size_in_bytes, url}]` | public |

Logout on mobile = discard the tokens (blacklisting isn't enabled).

## Notes and known limitations

* **Giving**: the Give page shows instructions you enter under Settings; no payment gateway is integrated. "Giving" in the dashboard records gifts manually.
* The member-growth chart, stats and lists use real data; sample numbers from the static demo were removed.
* Demonstration notes and client-side fake saves in the original admin pages were removed; all forms post to the server.
* Stories media is stored under `MEDIA_ROOT/stories/`.
