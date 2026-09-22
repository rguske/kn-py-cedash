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
        # Preserve values that are already JSON-native (including None/null,
        # e.g. events with no data body) as-is. Only stringify anything else
        # (e.g. raw XML bytes) so it doesn't break json.dumps below.
        if data is not None and not isinstance(data, (dict, list, str, int, float, bool)):
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
