"""Tiny HTTP server for the LinkedIn draft review dashboard.

Serves static files from data/review/ and provides JSON API endpoints for
approve / skip / edit / regenerate-image actions.

Run:
    python run.py review-server --port 8080
"""
from __future__ import annotations

import json
import logging
import mimetypes
import re
import shutil
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path
from urllib.parse import unquote, urlparse

from config.calendar import day_plan
from config.settings import DATA_DIR, QUEUE_DIR, REVIEW_DIR, ensure_dirs
from pipeline.approval import approve_draft, edit_draft, skip_draft
from pipeline.content_analyst import analyze_queued_items
from pipeline.drafting import Draft, _draft_markdown, _parse_draft_markdown, load_drafts
from pipeline.image_engine import image_for_post
from pipeline.storage import Item, load_item

logger = logging.getLogger(__name__)

API_PREFIX = "/api"
REVIEW_IMAGES_DIR = REVIEW_DIR / "images"
REVIEW_SKIPPED_DIR = QUEUE_DIR / "skipped"


def _json_response(handler, status: int, data: dict) -> None:
    body = json.dumps(data).encode("utf-8")
    handler.send_response(status)
    handler.send_header("Content-Type", "application/json; charset=utf-8")
    handler.send_header("Content-Length", str(len(body)))
    handler.end_headers()
    handler.wfile.write(body)


def _read_json(handler) -> dict:
    length = int(handler.headers.get("Content-Length", 0))
    if length == 0:
        return {}
    raw = handler.rfile.read(length).decode("utf-8")
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        return {}


class _Handler(BaseHTTPRequestHandler):
    def log_message(self, fmt: str, *args) -> None:
        logger.info("%s - " + fmt, self.address_string(), *args)

    def do_GET(self) -> None:
        parsed = urlparse(self.path)
        path = unquote(parsed.path)
        if path == "/":
            path = "/index.html"

        if path.startswith("/api/"):
            self._handle_api_get(path)
            return

        # Static file serving from REVIEW_DIR
        safe_root = REVIEW_DIR.resolve()
        file_path = (safe_root / path.lstrip("/")).resolve()
        if not str(file_path).startswith(str(safe_root)):
            self.send_error(403, "Forbidden")
            return
        if not file_path.exists() or file_path.is_dir():
            self.send_error(404, "Not found")
            return
        self._serve_file(file_path)

    def _serve_file(self, file_path: Path) -> None:
        mime, _ = mimetypes.guess_type(str(file_path))
        mime = mime or "application/octet-stream"
        data = file_path.read_bytes()
        self.send_response(200)
        self.send_header("Content-Type", mime)
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def _handle_api_get(self, path: str) -> None:
        if path == "/api/drafts":
            pending = [d for d in load_drafts(QUEUE_DIR) if not d.approved and not d.published]
            analysis = analyze_queued_items(limit=50)
            analysis_by_id = {r.item_id: r for r in analysis}
            out = []
            for draft in pending:
                a = analysis_by_id.get(draft.item_id)
                out.append({
                    "item_id": draft.item_id,
                    "title": draft.title,
                    "pillar": draft.pillar,
                    "source_url": draft.source_url,
                    "image_path": draft.image_path,
                    "linkedin_post": draft.linkedin_post,
                    "hashtags": draft.hashtags,
                    "analysis": {
                        "relevance_score": a.relevance_score if a else 0,
                        "accuracy_score": a.accuracy_score if a else 0,
                        "perfection_score": a.perfection_score if a else 0,
                        "issues": a.issues if a else [],
                        "proposed_action": a.proposed_action if a else "—",
                    } if a else None,
                })
            _json_response(self, 200, {"ok": True, "drafts": out})
            return
        _json_response(self, 404, {"ok": False, "error": "Unknown endpoint"})

    def do_POST(self) -> None:
        parsed = urlparse(self.path)
        path = unquote(parsed.path)
        if not path.startswith(API_PREFIX + "/"):
            self.send_error(404, "Not found")
            return
        action = path[len(API_PREFIX) + 1 :]
        payload = _read_json(self)

        if action == "approve":
            self._do_approve(payload)
        elif action == "skip":
            self._do_skip(payload)
        elif action == "edit":
            self._do_edit(payload)
        elif action == "regenerate-image":
            self._do_regenerate_image(payload)
        else:
            _json_response(self, 404, {"ok": False, "error": "Unknown action"})

    def _do_approve(self, payload: dict) -> None:
        item_id = payload.get("item_id", "").strip()
        if not item_id:
            _json_response(self, 400, {"ok": False, "error": "missing item_id"})
            return
        ok = approve_draft(item_id)
        _json_response(self, 200 if ok else 404, {"ok": ok, "item_id": item_id})

    def _do_skip(self, payload: dict) -> None:
        item_id = payload.get("item_id", "").strip()
        if not item_id:
            _json_response(self, 400, {"ok": False, "error": "missing item_id"})
            return
        ok = skip_draft(item_id, skipped_dir=REVIEW_SKIPPED_DIR)
        _json_response(self, 200 if ok else 404, {"ok": ok, "item_id": item_id})

    def _do_edit(self, payload: dict) -> None:
        item_id = payload.get("item_id", "").strip()
        post = payload.get("linkedin_post", "")
        if not item_id:
            _json_response(self, 400, {"ok": False, "error": "missing item_id"})
            return
        ok = edit_draft(item_id, post)
        _json_response(self, 200 if ok else 404, {"ok": ok, "item_id": item_id})

    def _do_regenerate_image(self, payload: dict) -> None:
        item_id = payload.get("item_id", "").strip()
        if not item_id:
            _json_response(self, 400, {"ok": False, "error": "missing item_id"})
            return

        path = None
        for p in sorted(QUEUE_DIR.glob("*.md"), reverse=True):
            text = p.read_text()
            draft = _parse_draft_markdown(text)
            if draft and draft.item_id == item_id:
                path = p
                break
        if not path:
            _json_response(self, 404, {"ok": False, "error": "draft not found"})
            return

        draft = _parse_draft_markdown(path.read_text())
        if not draft:
            _json_response(self, 500, {"ok": False, "error": "could not parse draft"})
            return

        item = load_item(draft.source_url)
        if not item:
            _json_response(self, 404, {"ok": False, "error": "source item not found"})
            return

        plan = day_plan()
        try:
            img_path = image_for_post(
                item_url=item.item_url,
                title=draft.title,
                day=plan.day_name,
                pillar=draft.pillar,
                linkedin_post=draft.linkedin_post,
                hashtags=" ".join(draft.hashtags),
                skip_og=True,
            )
        except Exception as exc:
            logger.exception("Image regeneration failed for %s", item_id)
            _json_response(self, 500, {"ok": False, "error": f"image engine failed: {exc}"})
            return

        if not img_path:
            _json_response(self, 500, {"ok": False, "error": "no image returned"})
            return

        # Persist image path on draft and item
        draft.image_path = str(img_path)
        item.image_path = str(img_path)
        from pipeline.storage import save_item
        try:
            save_item(item)
        except Exception:
            logger.exception("Failed to persist item image_path")

        backup = path.with_suffix(".md.bak")
        backup.write_text(path.read_text())
        tmp = path.with_suffix(".tmp")
        tmp.write_text(_draft_markdown(draft))
        tmp.replace(path)

        # Copy into review images dir for the dashboard preview
        ext = img_path.suffix or ".png"
        dest = REVIEW_IMAGES_DIR / f"{item_id}{ext}"
        REVIEW_IMAGES_DIR.mkdir(parents=True, exist_ok=True)
        try:
            shutil.copy2(img_path, dest)
        except OSError:
            logger.exception("Failed to copy regenerated image to review dir")

        rel = str(dest.relative_to(REVIEW_DIR))
        _json_response(self, 200, {"ok": True, "item_id": item_id, "image_url": f"/{rel}"})


def run_server(host: str = "0.0.0.0", port: int = 8080) -> None:
    ensure_dirs()
    server = HTTPServer((host, port), _Handler)
    logger.info("Review server listening on http://%s:%s", host, port)
    print(f"Review server listening on http://{host}:{port}")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nShutting down review server.")
        server.shutdown()


if __name__ == "__main__":
    run_server()
