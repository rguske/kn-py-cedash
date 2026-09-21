# kn-py-cedash CloudEvent Dashboard Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Extend the seeded `kn-py-echo`-derived Flask app (`kn-py-cedash`, repo `rguske/kn-py-cedash`) so that, in addition to its existing `POST /` CloudEvent decode/log behavior, it serves a PatternFly 6 dashboard at `GET /` showing the most recently received CloudEvents, updating automatically via polling.

**Architecture:** A module-level, thread-safe in-memory ring buffer (`collections.deque(maxlen=50)`) records each decoded CloudEvent as `POST /` receives it. `GET /` renders a Jinja2 template (`templates/index.html`) containing a two-section PatternFly 6 layout (upper: function name; lower: event list container) plus a small vanilla-JS polling loop. `GET /api/events` exposes the buffer as JSON for that polling loop to consume. No new Python dependencies; PatternFly 6 is loaded client-side from a CDN, no build step.

**Tech Stack:** Python 3.12, Flask 3.1.3, cloudevents 2.2.0 (all unchanged from the seeded baseline), PatternFly 6 CSS (CDN), vanilla JS.

## Global Constraints

- No new Python dependency is introduced — `requirements.txt` stays exactly `Flask==3.1.3` / `cloudevents==2.2.0`.
- The event buffer is capped at 50 entries (`MAX_EVENTS = 50`), newest first, in-memory only (no persistence).
- Update mechanism is client-side polling (`fetch('/api/events')` every 2.5s) — no SSE/WebSocket.
- Existing `POST /` response/logging behavior (pretty-printed JSON, 200/400 status codes) must remain unchanged for callers — the only addition is recording the event into the buffer.
- The dashboard's upper section displays the literal string `kn-py-cedash`.
- Directory: `kn-py-cedash/` repo root (all file paths below are relative to this root).
- All dynamic values inserted into the DOM by client-side JS must be HTML-escaped.

---

### Task 1: Event buffer + `GET /` + `GET /api/events` in `handler.py`

**Files:**
- Modify: `handler.py`

**Interfaces:**
- Produces: module-level `_events` (a `collections.deque`, newest-first, JSON-native dict entries shaped `{"received_at": str, "attributes": dict, "data": ...}`) and `_events_lock` (`threading.Lock`) — consumed by Task 2's manual verification only (no other task imports these directly; Task 2's template/JS talks to them only via the `GET /api/events` HTTP endpoint, not by importing Python).
- Produces: `GET /` route rendering `templates/index.html` with a `display_name="kn-py-cedash"` template variable — Task 2 creates that template.
- Produces: `GET /api/events` route returning a JSON array (newest-first) of the buffer's contents — Task 2's JS consumes this shape: each item has `received_at` (ISO 8601 string), `attributes` (dict of CloudEvent attributes, all JSON-native — e.g. `time` is already a string, not a raw `datetime`), and `data` (the event payload, dict or string).

- [ ] **Step 1: Replace `handler.py` with the buffer + new routes added**

Replace the entire file with:

```python
from flask import Flask, request, Response, jsonify, render_template
from cloudevents.core.bindings.http import from_http_event, HTTPMessage
from collections import deque
from threading import Lock
from datetime import datetime, timezone
import logging, json

logging.basicConfig(level=logging.DEBUG,format='%(asctime)s %(levelname)s %(name)s %(threadName)s : %(message)s')

app = Flask(__name__)

DISPLAY_NAME = "kn-py-cedash"
MAX_EVENTS = 50
_events = deque(maxlen=MAX_EVENTS)
_events_lock = Lock()

@app.route('/', methods=['GET'])
def dashboard():
    return render_template("index.html", display_name=DISPLAY_NAME)

@app.route('/api/events', methods=['GET'])
def list_events():
    with _events_lock:
        return jsonify(list(_events))

@app.route('/', methods=['POST'])
def echo():
    try:
        event = from_http_event(HTTPMessage(dict(request.headers), request.get_data()))

        data = event.get_data()
        # hack to handle non JSON payload, e.g. xml
        if not isinstance(data,dict):
            data = str(data)

        e = {
            "attributes": dict(event.get_attributes()),
            "data": data
        }
        payload = json.dumps(e, indent=2, default=str)

        with _events_lock:
            _events.appendleft({
                "received_at": datetime.now(timezone.utc).isoformat(),
                **json.loads(payload),
            })

        app.logger.info(f'***cloud event*** {payload}')
        return Response(payload, status=200, mimetype='application/json')
    except Exception as e:
        sc = 400
        msg = f'could not decode cloud event: {e}'
        app.logger.error(msg)
        message = {
            'status': sc,
            'error': msg,
        }
        resp = Response(json.dumps(message, indent=2), status=sc, mimetype='application/json')
        return resp

# hint: run with FLASK_ENV=development FLASK_APP=handler.py flask run
if __name__ == "__main__":
    app.run()
```

Notes:
- `json.loads(payload)` (re-parsing the already-`default=str`-serialized `e` dict) is used when storing into the buffer specifically so the buffer only ever holds fully JSON-native types (no raw `datetime` objects) — this makes `jsonify(list(_events))` in `list_events()` trivial and avoids any datetime-encoding edge cases in that endpoint.
- `dashboard()` will fail with a `jinja2.TemplateNotFound` error until Task 2 creates `templates/index.html` — that's expected; Task 2 completes the picture. This task's own verification (Step 3 below) only exercises `POST /` and `GET /api/events`, not `GET /`.

- [ ] **Step 2: Verify `POST /` behavior is unchanged and events are buffered**

```bash
python3 -m venv .venv-check && source .venv-check/bin/activate
pip install --no-cache-dir -r requirements.txt
FLASK_APP=handler.py FLASK_ENV=development flask run --port=8090 &
sleep 2
curl -s -i -d@test/testevent.json localhost:8090
echo "---second post---"
curl -s -i -d@test/event.json localhost:8090
echo "---events endpoint---"
curl -s localhost:8090/api/events | python3 -m json.tool
```

Expected:
- Both `POST /` calls return `HTTP/1.1 200 OK` with the same pretty-printed JSON body shape as before this task (attributes + data).
- `GET /api/events` returns a JSON array of exactly 2 items, **newest first** (the `test/event.json` post should appear at index 0, `test/testevent.json` at index 1), each with `received_at`, `attributes`, `data` keys.

- [ ] **Step 3: Clean up and commit**

```bash
kill %1
deactivate
rm -rf .venv-check __pycache__
git add handler.py
git commit -m "feat: add in-memory event buffer, GET / dashboard route, GET /api/events endpoint"
```

---

### Task 2: `templates/index.html` dashboard UI + `Containerfile` update

**Files:**
- Create: `templates/index.html`
- Modify: `Containerfile`

**Interfaces:**
- Consumes: `GET /` template variable `display_name` (a string, e.g. `"kn-py-cedash"`) from Task 1's `dashboard()` view.
- Consumes: `GET /api/events` JSON shape from Task 1 — array of `{received_at, attributes, data}` objects, newest first.

- [ ] **Step 1: Create `templates/index.html`**

```html
<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>{{ display_name }}</title>
    <link rel="stylesheet" href="https://unpkg.com/@patternfly/patternfly@6/patternfly.min.css">
    <style>
        :root {
            --cedash-purple: #6f2da8;
            --cedash-purple-dark: #4a1d73;
            --cedash-purple-light: #a06cd5;
        }
        body {
            background: linear-gradient(135deg, #1a1a1a 0%, #2d2d2d 50%, #1a1a1a 100%);
            min-height: 100vh;
            font-size: 16px;
        }
        .pf-v6-l-bullseye {
            min-height: 100vh;
            padding: var(--pf-t--global--spacer--lg);
        }
        .cedash-card {
            max-width: 900px;
            width: 100%;
        }
        .pf-v6-c-card.cedash-card {
            --pf-v6-c-card--BackgroundColor: rgba(30, 30, 30, 0.95);
            border: 2px solid var(--cedash-purple);
            box-shadow: 0 0 40px rgba(111, 45, 168, 0.35);
        }
        .cedash-header {
            text-align: center;
            padding: var(--pf-t--global--spacer--xl) 0;
            background: linear-gradient(180deg, rgba(111, 45, 168, 0.15) 0%, transparent 100%);
            border-radius: var(--pf-t--global--border--radius--medium) var(--pf-t--global--border--radius--medium) 0 0;
        }
        .cedash-title {
            font-size: 2.25rem;
            font-weight: 700;
            color: #ffffff;
            margin: 0;
            text-shadow: 0 0 20px rgba(111, 45, 168, 0.6);
        }
        .cedash-subtitle {
            color: #cccccc;
            font-size: 1rem;
            margin-top: var(--pf-t--global--spacer--sm);
        }
        .pf-v6-c-card__body {
            color: #e0e0e0;
        }
        .cedash-event-card {
            background: rgba(111, 45, 168, 0.08);
            border-left: 3px solid var(--cedash-purple);
            border-radius: var(--pf-t--global--border--radius--medium);
            padding: var(--pf-t--global--spacer--md);
            margin-bottom: var(--pf-t--global--spacer--md);
        }
        .cedash-event-card h3 {
            color: var(--cedash-purple-light) !important;
            font-size: 1.1rem;
            margin: 0 0 var(--pf-t--global--spacer--xs) 0;
        }
        .cedash-event-meta {
            color: #aaaaaa;
            font-size: 0.85rem;
            margin-bottom: var(--pf-t--global--spacer--sm);
        }
        .cedash-event-meta span {
            margin-right: var(--pf-t--global--spacer--md);
        }
        .cedash-event-data {
            background: rgba(0, 0, 0, 0.35);
            color: #e0e0e0;
            padding: var(--pf-t--global--spacer--sm);
            border-radius: var(--pf-t--global--border--radius--small);
            overflow-x: auto;
            font-size: 0.85rem;
            margin: 0;
        }
    </style>
</head>
<body>
    <div class="pf-v6-l-bullseye">
        <div class="pf-v6-c-card cedash-card">
            <div class="cedash-header">
                <h1 class="cedash-title">{{ display_name }}</h1>
                <p class="cedash-subtitle">Live CloudEvents dashboard</p>
            </div>
            <div class="pf-v6-c-card__body">
                <div id="events-list">
                    <div class="pf-v6-c-empty-state">
                        <div class="pf-v6-c-empty-state__content">
                            <p class="pf-v6-c-empty-state__body">Waiting for CloudEvents&hellip;</p>
                        </div>
                    </div>
                </div>
            </div>
            <div class="pf-v6-c-card__footer" style="text-align:center; color:#888; font-size:0.85rem;">
                <p>Showing up to 50 most recent events &middot; refreshes every 2.5s</p>
            </div>
        </div>
    </div>

    <script>
        function escapeHtml(value) {
            return String(value)
                .replace(/&/g, '&amp;')
                .replace(/</g, '&lt;')
                .replace(/>/g, '&gt;')
                .replace(/"/g, '&quot;')
                .replace(/'/g, '&#039;');
        }

        function renderEmptyState() {
            return (
                '<div class="pf-v6-c-empty-state">' +
                '<div class="pf-v6-c-empty-state__content">' +
                '<p class="pf-v6-c-empty-state__body">Waiting for CloudEvents&hellip;</p>' +
                '</div>' +
                '</div>'
            );
        }

        function renderEvent(evt) {
            const attrs = evt.attributes || {};
            const dataJson = JSON.stringify(evt.data, null, 2);
            return (
                '<div class="cedash-event-card">' +
                '<h3>' + escapeHtml(attrs.type || 'unknown type') + '</h3>' +
                '<div class="cedash-event-meta">' +
                '<span><strong>id:</strong> ' + escapeHtml(attrs.id || '') + '</span>' +
                '<span><strong>source:</strong> ' + escapeHtml(attrs.source || '') + '</span>' +
                '<span><strong>received:</strong> ' + escapeHtml(evt.received_at || '') + '</span>' +
                '</div>' +
                '<pre class="cedash-event-data">' + escapeHtml(dataJson) + '</pre>' +
                '</div>'
            );
        }

        async function refresh() {
            try {
                const res = await fetch('/api/events');
                const events = await res.json();
                const container = document.getElementById('events-list');
                container.innerHTML = events.length === 0
                    ? renderEmptyState()
                    : events.map(renderEvent).join('');
            } catch (err) {
                console.error('Failed to refresh events', err);
            }
        }

        refresh();
        setInterval(refresh, 2500);
    </script>
</body>
</html>
```

- [ ] **Step 2: Update `Containerfile` to copy the templates directory**

In `Containerfile`, immediately after the existing `COPY handler.py .` line, add:

```dockerfile
COPY templates/ templates/
```

The full file should read:

```dockerfile
FROM python:3.12-slim

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY handler.py .
COPY templates/ templates/

RUN useradd --create-home --shell /usr/sbin/nologin appuser
USER appuser

ENV FLASK_APP=handler.py
ENV PORT=8080
EXPOSE 8080

CMD ["sh", "-c", "flask run --host=0.0.0.0 --port=${PORT}"]
```

- [ ] **Step 3: Verify locally with a venv (GET / and GET /api/events together)**

```bash
python3 -m venv .venv-check && source .venv-check/bin/activate
pip install --no-cache-dir -r requirements.txt
FLASK_APP=handler.py FLASK_ENV=development flask run --port=8090 &
sleep 2
curl -s -d@test/testevent.json localhost:8090 > /dev/null
curl -s -i localhost:8090/ | head -20
echo "---check content---"
curl -s localhost:8090/ | grep -o 'kn-py-cedash' | head -1
curl -s localhost:8090/ | grep -o 'unpkg.com/@patternfly/patternfly@6' | head -1
kill %1
deactivate
rm -rf .venv-check __pycache__
```

Expected: `GET /` returns `HTTP/1.1 200 OK` with `Content-Type: text/html`; the body contains the literal string `kn-py-cedash` and the PatternFly CDN URL.

- [ ] **Step 4: Verify with Podman (full container build/run)**

```bash
podman build -t kn-py-cedash:test -f Containerfile .
podman run -d --rm -p 8081:8080 -e PORT=8080 --name kn-py-cedash-test kn-py-cedash:test
sleep 2
curl -s -d@test/testevent.json localhost:8081 > /dev/null
curl -s -i localhost:8081/
curl -s localhost:8081/api/events | python3 -m json.tool
podman logs kn-py-cedash-test
podman stop kn-py-cedash-test
```

Expected: `GET /` returns `200` with the dashboard HTML (confirming `templates/` was copied into the image correctly); `GET /api/events` returns the one posted event; container logs show the pretty-printed CloudEvent log line.

- [ ] **Step 5: Commit**

```bash
git add templates/index.html Containerfile
git commit -m "feat: add PatternFly 6 dashboard template, copy templates/ in Containerfile"
```

---

### Task 3: Rename Knative manifest + update `README.md`

**Files:**
- Modify: `function.yaml`
- Modify: `README.md`

**Interfaces:**
- Consumes: nothing from Task 1/2 code directly — this task only updates deployment manifest names/docs, no behavior change.

- [ ] **Step 1: Update `function.yaml`**

Replace the entire file with:

```yaml
oc create -f - <<EOF
apiVersion: serving.knative.dev/v1
kind: Service
metadata:
  name: kn-py-cedash-fn
spec:
  template:
    metadata:
      annotations:
        autoscaling.knative.dev/maxScale: "1"
        autoscaling.knative.dev/minScale: "1"
    spec:
      containers:
        - image: quay.io/rguske/kn-py-cedash:1.0
---
apiVersion: eventing.knative.dev/v1
kind: Trigger
metadata:
  labels:
    eventing.knative.dev/broker: inmem-broker-transformer
  name: trigger-py-cedash-fn
spec:
  broker: inmem-broker-transformer
  filter:
    attributes: {}
  subscriber:
    ref:
      apiVersion: serving.knative.dev/v1
      kind: Service
      name: kn-py-cedash-fn
EOF
```

- [ ] **Step 2: Update `README.md`**

Replace the entire file with:

```markdown
# kn-py-cedash

Example Python function with a `Flask` REST API running in Knative. It
decodes and logs incoming [CloudEvents](https://github.com/cloudevents/sdk-python)
(same behavior as `kn-py-echo`), and additionally serves a live dashboard at
`GET /` showing the most recently received CloudEvents (PatternFly 6 UI,
purple theme), refreshing automatically as new events arrive.

## Step 1 - Build with `Buildpacks`

[Buildpacks](https://buildpacks.io) are used to create the container image.

\`\`\`shell
IMAGE=<docker-username>/<repo>/kn-py-cedash:1.0
pack build -B gcr.io/buildpacks/builder:v1 ${IMAGE}
\`\`\`

## Step 1 (alternative) - Build with Podman

Instead of Buildpacks, you can build the container image directly from the
included `Containerfile` using [Podman](https://podman.io):

\`\`\`shell
IMAGE=<registry>/<repo>/kn-py-cedash:1.0
podman build -t ${IMAGE} -f Containerfile .
\`\`\`

## Step 2 - Test

Verify the container image works by executing it locally.

\`\`\`bash
podman run -e PORT=8080 -it --rm -p 8080:8080 ${IMAGE}
\`\`\`

Open `http://localhost:8080/` in a browser to see the dashboard — it starts
empty ("Waiting for CloudEvents...") until an event is posted.

In a separate terminal window, use the `testevent.json` file to validate the
function is working.

\`\`\`shell
curl -i -d@test/testevent.json localhost:8080
\`\`\`

You should see a `200 OK` response with the pretty-printed decoded
CloudEvent as the JSON body, and the browser dashboard should update with
the new event within ~3 seconds without a manual reload.

## Step 3 - Deploy

> **Note:** The following steps assume a working Knative environment using
the `default` Rabbit `broker`. The Knative `service` and `trigger` will be
installed in the `vmware-functions` Kubernetes namespace, assuming that the
`broker` is also available there.

Push your container image to an accessible registry once you're done
developing and testing your function logic.

\`\`\`shell
docker push <docker-username>/<repo>/kn-py-cedash:1.0
\`\`\`

Edit the `function.yaml` file with the name of the container image from
Step 1 if you made any changes. Deploy the function:

\`\`\`shell
kubectl -n vmware-functions apply -f function.yaml
\`\`\`

For testing purposes, the `function.yaml` contains the following
annotations, which will ensure the Knative Service Pod will always run
**exactly** one instance for debugging purposes (otherwise Knative may scale
to zero, which resets the in-memory event buffer on the next cold start):

\`\`\`yaml
annotations:
  autoscaling.knative.dev/maxScale: "1"
  autoscaling.knative.dev/minScale: "1"
\`\`\`

## Step 4 - Undeploy

\`\`\`console
# undeploy function
kubectl -n vmware-functions delete -f function.yaml
\`\`\`
```

(Use literal triple-backtick fences in the actual file — the escaping above is only to nest this inside the plan document.)

- [ ] **Step 3: Verify fence balance and commit**

```bash
grep -c '```' README.md
```

Expected: an even number (every opening fence has a matching close).

```bash
git add function.yaml README.md
git commit -m "docs: rename Knative manifest to kn-py-cedash-fn, document dashboard in README"
```

---

## Self-Review Notes

- **Spec coverage:** event buffer + `GET /api/events` (Task 1), `GET /` dashboard route (Task 1), PatternFly 6 template with purple theme + polling JS (Task 2), `Containerfile` template copy (Task 2), `function.yaml` rename (Task 3), `README.md` update (Task 3) — all spec items covered. `requirements.txt`/`Procfile`/`pyvenv.cfg`/`test/*.json` intentionally untouched per the spec's "out of scope" list.
- **Placeholder scan:** none found; every step has literal file contents and exact commands.
- **Type/name consistency:** `display_name` is passed by `handler.py`'s `dashboard()` (Task 1) and consumed by `templates/index.html`'s `{{ display_name }}` (Task 2) — names match. `GET /api/events`'s JSON shape (`received_at`, `attributes`, `data`) as produced in Task 1 matches exactly what Task 2's `renderEvent()` JS reads (`evt.received_at`, `evt.attributes`, `evt.data`).
