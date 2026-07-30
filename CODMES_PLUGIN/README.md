# Codmes KNU plugin

This package registers the KNU declarative surface and its MCP tools as one Codmes
installation unit. Docker is not required for local development.

`tools.json` declares the stable public names `knu_search_notices` and
`knu_get_notice_detail`, their independent JSON input schemas, read-only flags,
and approval policy. Codmes validates the declarations during installation and
maps them to the KNU MCP server's `search_knu_notices` and
`get_knu_notice_detail` tools.

```sh
# KNU API/MCP: SERVER/.env must contain MCP_AUTH_TOKEN=<a secret value>
cd SERVER
RUNTIME_ENV=local ../.venv/bin/python -m uvicorn api.main:app --port 8000

# Codmes must store the same MCP token in its server-side credential store.
printf '%s' "$MCP_AUTH_TOKEN" | codmes mcp credential set knu \
  --root /path/to/CodmesWorkspace
codmes plugin install ./CODMES_PLUGIN --root /path/to/CodmesWorkspace
```

The default manifest expects the KNU domain data API and MCP at
`http://127.0.0.1:8000`. Codmes does not load the KNU website in a WebView.
`surface.json` in this package owns navigation, presentation, filters, icons,
and data bindings. FastAPI returns only KNU data; Codmes combines both inputs
and renders the resulting document with native SwiftUI.
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
the portal student ID and password once to `/api/auth/portal-login`. The KNU
server verifies them against the university SSO without creating or looking up
a KNU PICK account. The verified browser session is then reused by a server
background task to fetch and persist the student's name, major, year, weekly
timetable, graduation credits, grade distribution, and cumulative grades.
The same background task uses the one-time password to create a temporary
Canvas/LearningX session and synchronize LMS courses, assignments,
announcements, and incomplete lectures. The password and temporary browser
session are discarded after synchronization, and Codmes stores only the
KNU-issued JWT in its server-side credential store. KNU JWTs intentionally
have no `exp` claim; logging out removes the local credential. Server-side
token revocation should be added before treating logout as remote invalidation.

The `portal` route binds `/api/codmes/data/portal` domain JSON to a declarative
`dashboard`. Codmes renders its key-value and table sections natively on macOS,
iPadOS, and iOS; the plugin does not embed the legacy KNU web application.
