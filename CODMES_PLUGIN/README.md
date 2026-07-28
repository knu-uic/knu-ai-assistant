# Codmes KNU plugin

This package registers the KNU declarative surface and its MCP tools as one Codmes
installation unit. Docker is not required for local development.

```sh
# KNU API/MCP: SERVER/.env must contain MCP_AUTH_TOKEN=<a secret value>
cd SERVER
RUNTIME_ENV=local ../.venv/bin/python -m uvicorn api.main:app --port 8000

# Codmes must store the same MCP token in its server-side credential store.
printf '%s' "$MCP_AUTH_TOKEN" | codmes mcp credential set knu \
  --root /path/to/CodmesWorkspace
codmes plugin install ./CODMES_PLUGIN --root /path/to/CodmesWorkspace
```

The default manifest expects the declarative Surface API and MCP at
`http://127.0.0.1:8000`. Codmes does not load the KNU website in a WebView.
FastAPI returns a Surface document and Codmes renders it with native SwiftUI.
The manifest contains only the credential id `knu`;
the actual token remains in Codmes `.codmes/config/auth.json` and KNU
`SERVER/.env`.

Docker/Caddy remains an optional production path. Install
`plugin.docker.json` as a file when the KNU API is exposed on local port 80:

```sh
codmes plugin install ./CODMES_PLUGIN/plugin.docker.json \
  --root /path/to/CodmesWorkspace
```

The native Surface contains 공지, LMS, 포털, 설정 sections. macOS and iPad
render these in a persistent Notes-style sidebar. iPhone selects a section and
enters its native content hierarchy.

The sidebar shows only Kongju portal connection status and compact
login/logout controls. Login opens the native plugin settings screen and sends
the portal student ID and password once to `POST /api/auth/portal-login`. KNU
returns HTTP 202 with only a random `job_id`:

```json
{"job_id":"<random-id>"}
```

Codmes polls `POST /api/auth/portal-login/status` with that job ID. The status
response is one of `queued`, `running`, `failed`, or `done`. A successful
`done` response is the only response that contains `access_token` and
`token_type: "bearer"`; failed responses use one generic message and never
return portal error details. Unknown, expired, or non-portal job IDs return
HTTP 404. The job expires after at most 210 seconds, so a worker that is not
running remains queued only during the polling window.

The API process only encrypts the password and enqueues the existing ARQ
`portal_sync` worker with username `portal:<student_id>`. Portal login and
portal data synchronization therefore run in the worker's Playwright
environment; the API process does not run Playwright or a background sync.
After receiving `done`, Codmes stores the JWT in its server-side credential
store and calls the existing `POST /api/lms/sync/start` separately with the
same student ID and password plus `Authorization: Bearer <access_token>`.
That request uses the existing `lms_sync` worker; KNU's `portal_sync` job does
not run LMS synchronization a second time. The password and worker-side
temporary session are discarded according to the existing worker contract.
KNU JWTs intentionally have no `exp` claim; logging out removes the local
credential. Server-side token revocation should be added before treating
logout as remote invalidation.

The `portal` route returns a declarative `dashboard` document. Codmes renders
its key-value and table sections natively on macOS, iPadOS, and iOS; the plugin
does not embed the legacy KNU web application.
