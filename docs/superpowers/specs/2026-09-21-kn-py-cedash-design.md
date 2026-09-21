# kn-py-cedash: CloudEvent Dashboard (PatternFly 6)

## Context

`kn-py-cedash` is a new, standalone Knative Python function/repo, seeded from
`rguske/knative-functions`'s `kn-py-echo` (commit `d143ccd`). `kn-py-echo`
remains untouched in its original repo.

The goal is a small Flask app that, instead of just logging received
CloudEvents, also serves a simple web dashboard: a purple-themed frame split
into two sections — an upper section showing the function's name, and a
lower section showing recently received CloudEvents, updating as new events
arrive.

Reference for the "simple frame" visual style:
[`rguske/bootable-containers/demos/webserver`](https://github.com/rguske/bootable-containers/tree/main/demos/webserver) —
confirmed (via direct fetch of its `index.html`) to be a **pure static
HTML + CSS page**, no JS, no build tooling: PatternFly 6 CSS is loaded from
a CDN (`https://unpkg.com/@patternfly/patternfly@6/patternfly.min.css`), and
theming is done via CSS custom properties (`--rh-red`, `--rh-red-dark`,
`--rh-red-light`) swapped at container build time. `kn-py-cedash` follows the
same "PatternFly via CDN, no build step" approach, adapted with a purple
theme and enough client-side JS to poll for new events.

## Decisions

- **Scope:** Extend the copied `kn-py-echo` code in place (this repo) rather
  than keep two divergent copies — there is no separate "echo-only" function
  in this repo; `kn-py-cedash` both decodes/logs CloudEvents (existing
  behavior, unchanged) and displays them.
- **Update mechanism:** Client-side polling. The page's JS calls
  `GET /api/events` every 2–3 seconds and re-renders the lower section.
  Chosen over SSE/WebSockets because long-lived connections are awkward with
  Knative's scale-to-zero model, and polling is far simpler to implement and
  debug.
- **Event buffer:** In-memory only, `collections.deque(maxlen=50)` guarded
  by a `threading.Lock`. Not persisted — acceptable for a demo/dashboard;
  resets on pod restart/cold start. Oldest events are dropped once the cap
  is hit.
- **Display name:** The upper section shows the literal string
  `kn-py-cedash` (the repo name is also the display name — no further
  renaming needed since we are not keeping a separate "echo" identity).
- **Theme:** Custom hex-based purple theme via CSS custom properties,
  following the exact same pattern as the reference repo's
  `--rh-red`/`--rh-red-dark`/`--rh-red-light` variables (just a purple
  palette instead of red). No build-time templating step (like the
  reference's `sed`-based `THEME_COLOR` substitution) is needed since this
  is a single, fixed theme — the CSS variables are hardcoded directly in the
  template.
- **Templating:** A Flask/Jinja2 template (`templates/index.html`) rather
  than an inline Python string, to keep `handler.py` focused on
  request-handling logic. The `Containerfile` copies the `templates/`
  directory alongside `handler.py`.

## Changes (relative to the seeded `kn-py-echo` baseline)

### 1. `handler.py`

- Add a module-level, thread-safe ring buffer:
  ```python
  from collections import deque
  from threading import Lock
  from datetime import datetime, timezone

  MAX_EVENTS = 50
  _events = deque(maxlen=MAX_EVENTS)
  _events_lock = Lock()
  ```
- In the existing `POST /` handler (`echo`), after building the `e` dict
  (`{"attributes": ..., "data": ...}`), also record it in the buffer:
  ```python
  with _events_lock:
      _events.appendleft({
          "received_at": datetime.now(timezone.utc).isoformat(),
          **e,
      })
  ```
  (`appendleft` so the buffer is already newest-first; no change to the
  existing response/logging behavior.)
- Add `GET /` — renders `templates/index.html` via
  `render_template("index.html", display_name="kn-py-cedash")`.
- Add `GET /api/events` — returns the current buffer as JSON:
  ```python
  @app.route('/api/events', methods=['GET'])
  def list_events():
      with _events_lock:
          return jsonify(list(_events))
  ```
  (Re-add `jsonify` to the Flask import — it was dropped in a prior commit
  when the echo responses switched to raw `Response` objects; `jsonify` is
  fine here since this endpoint doesn't need pretty-printing, the page JS
  re-indents for display if needed.)

### 2. `templates/index.html` (new file)

- `<head>`: PatternFly 6 CSS via CDN (`unpkg.com/@patternfly/patternfly@6/patternfly.min.css`), plus a `<style>` block defining purple theme CSS variables (`--cedash-purple`, `--cedash-purple-dark`, `--cedash-purple-light`) applied the same way the reference repo applies its red theme (border/box-shadow on a `pf-v6-c-card`, header gradient, etc).
- Body: a single `pf-v6-c-card` split into two sections:
  - Upper: `pf-v6-c-card__header` showing `{{ display_name }}` (e.g. "kn-py-cedash") as the title, styled like the reference's `demo-title`.
  - Lower: `pf-v6-c-card__body` containing an empty container (`<div id="events-list"></div>`) that client-side JS populates/re-populates on each poll. Each event renders as its own `pf-v6-c-card` (nested) or `pf-v6-c-list__item`, showing `id`, `type`, `source`, `received_at` as a small header line, and the `data` payload as a `<pre>` block (pretty-printed JSON, reusing the same `JSON.stringify(data, null, 2)` idea client-side).
  - If the buffer is empty, show a PatternFly empty-state (`pf-v6-c-empty-state`) with a "Waiting for CloudEvents…" message instead of an empty area.
- A `<script>` block (vanilla JS, no dependency):
  ```js
  async function refresh() {
    const res = await fetch('/api/events');
    const events = await res.json();
    renderEvents(events);
  }
  function renderEvents(events) {
    const container = document.getElementById('events-list');
    if (events.length === 0) {
      container.innerHTML = /* empty-state markup */;
      return;
    }
    container.innerHTML = events.map(renderEvent).join('');
  }
  function renderEvent(evt) { /* returns one card's HTML, escaping values */ }
  refresh();
  setInterval(refresh, 2500);
  ```
  All dynamic values must be HTML-escaped before insertion (a small
  `escapeHtml()` helper) to avoid injecting arbitrary CloudEvent payload
  content as raw HTML.

### 3. `Containerfile`

- Add `COPY templates/ templates/` after the existing `COPY handler.py .`
  line. No other changes — base image, non-root user, `PORT`/`EXPOSE 8080`,
  and the `flask run` `CMD` all stay exactly as in the seeded version.

### 4. `function.yaml`

- Rename `metadata.name` (Service) from `kn-py-echo-fn` to `kn-py-cedash-fn`,
  the Trigger's `metadata.name` from `trigger-py-echo-fn` to
  `trigger-py-cedash-fn`, and the Trigger's `subscriber.ref.name` to match
  the renamed Service. Image reference placeholder updated to
  `quay.io/rguske/kn-py-cedash:1.0` (adjust when actually pushing an image).

### 5. `README.md`

- Update the title/description to describe the dashboard (not just an
  echo). Keep both the Buildpacks (`pack build`) and Podman
  (`podman build -f Containerfile .`) instructions from the seeded version.
  Add a short note that `GET /` now serves a live dashboard of recently
  received events at `http://<host>:<port>/`, in addition to the existing
  `POST /` CloudEvents receiver behavior.

### Out of scope / unchanged

- `Procfile`, `pyvenv.cfg`, `requirements.txt` — unchanged; no new Python
  dependency is introduced (dashboard is served with Flask's own
  `render_template`/`jsonify`, no extra package).
- `test/testevent.json`, `test/event.json` — unchanged, still used to
  exercise `POST /`.
- Persistence, auth, multi-replica event sharing — explicitly out of scope;
  this is a single-pod, in-memory demo dashboard.

## Verification Plan

1. Local venv: `pip install -r requirements.txt`, `flask run`, then:
   - `curl -i -d@test/testevent.json localhost:8080` (repeat 2–3 times with
     slightly different payloads) still returns the existing pretty-printed
     JSON response/log behavior, unchanged.
   - `curl -s localhost:8080/api/events | python3 -m json.tool` shows the
     posted events, newest first, capped at 50.
   - `curl -s localhost:8080/` returns HTML containing `kn-py-cedash` and
     the PatternFly CDN `<link>`.
2. Podman: `podman build -t kn-py-cedash:test -f Containerfile .`,
   `podman run -p 8080:8080 ...`, repeat the same curl checks against the
   containerized instance to confirm `templates/` was copied correctly and
   the app runs the same as in the venv.
3. Manual visual check: open `http://localhost:8080/` in a browser, POST a
   couple of test events, confirm the lower section updates within ~3
   seconds without a manual page reload, and that the empty-state shows
   before any events arrive.
