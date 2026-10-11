"""
server.py — Flask SSE server for Matzo Mate (multi-client build)

Each phone opens a /stream/<upc> connection. Concurrent scans of the
same UPC share a single search (in-flight deduplication); different UPCs
run in parallel up to SEARCH_CONCURRENCY.

No stdout redirect — all internal logging goes to Python's logging
system (server-side). Only structured progress messages and the final
RESULT: payload are sent over SSE to the client.
"""

import json
import logging
import os
import queue
import threading

from flask import Flask, Response, request, jsonify, send_file
import database
from main import productSearch, checkIngredients

# ---------------------------------------------------------------------------
# Logging
# ---------------------------------------------------------------------------

from logconfig import setup_logging, debug_enabled
setup_logging()
logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# App
# ---------------------------------------------------------------------------

app = Flask(__name__)

# ---------------------------------------------------------------------------
# Concurrency controls
# ---------------------------------------------------------------------------

# Max simultaneous external searches (DDG/APIs/Amazon). Each search can
# itself fire parallel async tasks internally, so keep this conservative.
SEARCH_CONCURRENCY = int(os.getenv("SEARCH_CONCURRENCY", "10"))
_search_sem = threading.Semaphore(SEARCH_CONCURRENCY)

# In-flight deduplication: barcode → list of subscriber queues.
# The first request for a barcode does the search; subsequent requests
# for the same barcode subscribe and receive the same result when ready.
_inflight: dict[str, list[queue.Queue]] = {}
_inflight_lock = threading.Lock()

# SSE queue size cap — prevents unbounded memory if a client reads slowly.
_QUEUE_MAXSIZE = 50

# How long a subscriber waits for a result before timing out (seconds).
_SEARCH_TIMEOUT = 120


# ---------------------------------------------------------------------------
# Static routes
# ---------------------------------------------------------------------------

@app.route("/")
def index():
    return send_file(
        os.path.join(os.path.dirname(os.path.abspath(__file__)), "index.html")
    )


@app.route("/sounds/<path:filename>")
def sounds(filename):
    sounds_dir = os.path.realpath(
        os.path.join(os.path.dirname(os.path.abspath(__file__)), "sounds")
    )
    target = os.path.realpath(os.path.join(sounds_dir, filename))
    # Reject path traversal attempts
    if not target.startswith(sounds_dir + os.sep):
        return jsonify({"error": "forbidden"}), 403
    if not os.path.isfile(target):
        return jsonify({"error": "not found"}), 404
    return send_file(target)


@app.after_request
def _cors(resp):
    resp.headers["Access-Control-Allow-Origin"] = "*"
    resp.headers["Access-Control-Allow-Headers"] = "Content-Type"
    resp.headers["Access-Control-Allow-Methods"] = "GET, POST, OPTIONS"
    return resp


def _verdict(product, upc=""):
    ingredients = product.get("ingredients") or []
    results = checkIngredients(ingredients)
    chametz = results.get("chametz") or []
    real = [item for item in chametz if not str(item).startswith("[AI flagged]")]
    flags = [item for item in chametz if str(item).startswith("[AI flagged]")]
    return {
        "upc": upc,
        "product_name": product.get("product_name", "Unknown"),
        "manufacturer": product.get("manufacturer"),
        "source": product.get("source", ""),
        "url": product.get("url", ""),
        "ingredients": ingredients,
        "chametz": real,
        "ai_flags": flags,
        "kosher_for_passover": not real,
    }


@app.route("/api")
def api_index():
    return jsonify({
        "service": "Matzo Mate",
        "routes": [
            {"method": "GET", "path": "/api/health"},
            {"method": "GET", "path": "/api/check/<upc>"},
            {"method": "POST", "path": "/api/check", "body": {"upc": "012345678905"}},
            {"method": "POST", "path": "/api/check", "body": {"ingredients": ["salt", "wheat flour"]}},
        ],
    })


@app.route("/api/health")
def health():
    return jsonify({"ok": True, "service": "Matzo Mate"})


@app.route("/api/check", methods=["GET", "POST", "OPTIONS"])
@app.route("/api/check/<upc>", methods=["GET", "OPTIONS"])
def api_check(upc=None):
    if request.method == "OPTIONS":
        return ("", 204)

    body = request.get_json(silent=True) or {}
    raw = body.get("ingredients")
    if isinstance(raw, str):
        ingredients = [item.strip() for item in raw.split(",") if item.strip()]
    elif isinstance(raw, list):
        ingredients = [str(item).strip() for item in raw if str(item).strip()]
    else:
        ingredients = None

    upc = str(upc or body.get("upc") or request.args.get("upc") or "").strip()

    if ingredients is not None and not upc:
        return jsonify(_verdict({
            "product_name": "Custom list",
            "ingredients": ingredients,
            "source": "request",
        }))

    if not upc:
        return jsonify({"error": "upc or ingredients required"}), 400
    if len(upc) > 20:
        return jsonify({"error": "Invalid UPC"}), 400

    product = productSearch(upc)
    if not product:
        return jsonify({"error": "product not found", "upc": upc, "status": "not_found"}), 404
    return jsonify(_verdict(product, upc))


# ---------------------------------------------------------------------------
# SSE stream
# ---------------------------------------------------------------------------

@app.route("/stream/<upc>")
def stream(upc):
    """
    Opens an SSE stream for a barcode lookup.

    If another request is already searching the same UPC, this request
    subscribes to that search and receives the result when it completes
    — no duplicate external calls are made.
    """

    def generate():
        q: queue.Queue = queue.Queue(maxsize=_QUEUE_MAXSIZE)

        with _inflight_lock:
            if upc in _inflight:
                # Piggyback on the existing search
                _inflight[upc].append(q)
                is_primary = False
                logger.info("UPC %s: subscriber added (%d waiting)", upc, len(_inflight[upc]))
            else:
                _inflight[upc] = [q]
                is_primary = True

        if is_primary:
            _start_worker(upc, q)

        # Stream items from the queue until None (sentinel) or timeout
        while True:
            try:
                line = q.get(timeout=_SEARCH_TIMEOUT)
            except queue.Empty:
                logger.warning("UPC %s: stream timed out after %ds", upc, _SEARCH_TIMEOUT)
                yield "data: Search timed out.\n\n"
                break
            if line is None:
                break
            yield f"data: {line}\n\n"

    return Response(
        generate(),
        mimetype="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


def _start_worker(upc: str, primary_q: queue.Queue) -> None:
    """Spawn the background search thread for a UPC."""

    def worker():
        result_line: str | None = None

        with _search_sem:
            logger.info("UPC %s: search started (semaphore %d/%d)",
                        upc, SEARCH_CONCURRENCY - _search_sem._value, SEARCH_CONCURRENCY)
            try:
                primary_q.put("Searching…")
                productData = productSearch(upc)

                if not productData:
                    primary_q.put("Product not found.")
                else:
                    results = checkIngredients(productData["ingredients"])
                    chametz = results["chametz"]
                    payload = {
                        "upc":          upc,
                        "product_name": productData.get("product_name", "Unknown"),
                        "source":       productData.get("source", "cache"),
                        "url":          productData.get("url", ""),
                        "ingredients":  productData.get("ingredients", []),
                        "chametz":  [f for f in chametz if not f.startswith("[AI flagged]")],
                        "ai_flags": [f for f in chametz if     f.startswith("[AI flagged]")],
                    }
                    result_line = f"RESULT:{json.dumps(payload)}"
                    primary_q.put(result_line)
                    logger.info("UPC %s: search complete via %s", upc, payload["source"])

            except Exception:
                logger.exception("UPC %s: unhandled error in worker", upc)
                primary_q.put("Search failed due to an internal error.")

            finally:
                # Broadcast result to all subscribers, then close all queues
                with _inflight_lock:
                    subscribers = _inflight.pop(upc, [])

                for sq in subscribers:
                    if sq is primary_q:
                        continue
                    if result_line:
                        try:
                            sq.put_nowait(result_line)
                        except queue.Full:
                            logger.warning("UPC %s: subscriber queue full, result dropped", upc)
                    sq.put(None)

                primary_q.put(None)

    t = threading.Thread(target=worker, daemon=True, name=f"search-{upc[:8]}")
    t.start()


# ---------------------------------------------------------------------------
# Contribute endpoint
# ---------------------------------------------------------------------------

@app.route("/contribute", methods=["POST"])
def contribute():
    body = request.get_json(force=True, silent=True)
    if not body:
        return jsonify({"error": "Invalid JSON"}), 400

    upc = str(body.get("upc", "")).strip()
    raw = str(body.get("ingredients", "")).strip()

    if not upc or not raw:
        return jsonify({"error": "Missing upc or ingredients"}), 400
    if len(upc) > 20:
        return jsonify({"error": "Invalid UPC"}), 400

    ingredients = [i.strip() for i in raw.split(",") if i.strip()]
    database.addProduct(upc, "User contributed", ingredients, "", "user")
    logger.info("Contribution received for UPC %s (%d ingredients)", upc, len(ingredients))
    return jsonify({"ok": True, "count": len(ingredients)})


# ---------------------------------------------------------------------------
# Delete endpoint
# ---------------------------------------------------------------------------

@app.route("/delete", methods=["POST"])
def delete():
    body = request.get_json(force=True, silent=True)
    if not body:
        return jsonify({"error": "Invalid JSON"}), 400

    upc = str(body.get("upc", "")).strip()
    if not upc:
        return jsonify({"error": "Missing upc"}), 400
    if len(upc) > 20:
        return jsonify({"error": "Invalid UPC"}), 400

    database.deleteProduct(upc)
    logger.info("Deleted UPC %s from database", upc)
    return jsonify({"ok": True, "upc": upc})


# ---------------------------------------------------------------------------

if __name__ == "__main__":
    debug = os.getenv("FLASK_DEBUG", "0") == "1"   # Werkzeug debugger/reloader (dev only)
    port  = int(os.getenv("PORT", "5000"))
    print(f"Matzo Mate server on port {port} — debug logging "
          f"{'ON' if debug_enabled() else 'OFF (use DEBUG=1 or --debug)'}")
    # Render / production:
    #   gunicorn server:app --worker-class gthread --workers 1 --threads 8 --timeout 180 --bind 0.0.0.0:$PORT
    app.run(debug=debug, threaded=True, host="0.0.0.0", port=port)
