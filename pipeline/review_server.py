"""HTTP server for the LinkedIn draft review dashboard.

Serves static review assets and provides JSON API endpoints for approving,
editing, regenerating images, and listing drafts by status.
"""
from __future__ import annotations

import json
import logging
import mimetypes
import shutil
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path
from urllib.parse import parse_qs, unquote, urlparse

from config.calendar import day_plan
from config.settings import QUEUE_DIR, REVIEW_DIR, ensure_dirs
from pipeline.approval import (
    approve_draft,
    edit_draft,
    list_approved,
    list_pending,
    list_rejected,
    skip_draft,
)
from pipeline.drafting import Draft, _draft_markdown, _parse_draft_markdown
from pipeline.image_engine import IMAGE_DIR, image_for_post
from pipeline.llm_client import chat, is_available
from pipeline.storage import load_item, save_item

logger = logging.getLogger(__name__)

ensure_dirs()
REVIEW_IMAGES_DIR = REVIEW_DIR / "images"
API_PREFIX = "/api"
AUTH_HEADER_PREFIX = "Basic "


def _require_auth(handler: BaseHTTPRequestHandler) -> bool:
    """Basic auth check using REVIEW_PASSWORD env var."""
    password = (os.environ.get("REVIEW_PASSWORD") or "").strip()
    if not password:
        return True  # no password configured = open (not recommended)
    auth = handler.headers.get("Authorization", "")
    if not auth.startswith(AUTH_HEADER_PREFIX):
        handler.send_response(401)
        handler.send_header("WWW-Authenticate", 'Basic realm="Review"')
        handler.end_headers()
        return False
    import base64

    try:
        decoded = base64.b64decode(auth[len(AUTH_HEADER_PREFIX) :]).decode("utf-8")
        _, provided = decoded.split(":", 1)
    except (ValueError, UnicodeDecodeError, base64.binascii.Error):
        provided = ""
    if provided != password:
        handler.send_response(401)
        handler.send_header("WWW-Authenticate", 'Basic realm="Review"')
        handler.end_headers()
        return False
    return True


def _read_json(handler: BaseHTTPRequestHandler) -> dict:
    length = int(handler.headers.get("Content-Length", 0))
    if not length:
        return {}
    try:
        return json.loads(handler.rfile.read(length).decode("utf-8")) or {}
    except json.JSONDecodeError:
        return {}


def _json_response(handler: BaseHTTPRequestHandler, code: int, data: dict) -> None:
    body = json.dumps(data).encode("utf-8")
    handler.send_response(code)
    handler.send_header("Content-Type", "application/json")
    handler.send_header("Content-Length", str(len(body)))
    handler.end_headers()
    handler.wfile.write(body)


def _copy_image_for_review(image_path: str, item_id: str) -> str | None:
    if not image_path:
        return None
    src = Path(image_path)
    if not src.exists():
        return None
    ext = src.suffix or ".png"
    dest = REVIEW_IMAGES_DIR / f"{item_id}{ext}"
    dest.parent.mkdir(parents=True, exist_ok=True)
    try:
        shutil.copy2(src, dest)
    except OSError:
        logger.exception("Failed to copy image %s to review dir", src)
        return None
    return str(dest.relative_to(REVIEW_DIR))


def _draft_to_json(draft: Draft, analysis: dict | None = None, status: str = "pending") -> dict:
    image_rel = _copy_image_for_review(draft.image_path, draft.item_id)
    candidates_rel: list[str] = []
    for cand in draft.image_candidates or []:
        cand_path = Path(cand)
        if cand_path.is_absolute() and cand_path.exists():
            ext = cand_path.suffix or ".jpg"
            dest = REVIEW_IMAGES_DIR / f"{draft.item_id}_cand_{len(candidates_rel)}{ext}"
            REVIEW_IMAGES_DIR.mkdir(parents=True, exist_ok=True)
            try:
                shutil.copy2(cand_path, dest)
            except OSError:
                continue
            candidates_rel.append(str(dest.relative_to(REVIEW_DIR)))
        elif (REVIEW_DIR / cand).exists():
            candidates_rel.append(cand)

    out = {
        "item_id": draft.item_id,
        "title": draft.title,
        "pillar": draft.pillar,
        "source_url": draft.source_url,
        "linkedin_post": draft.linkedin_post,
        "hashtags": draft.hashtags,
        "image_url": f"/{image_rel}" if image_rel else None,
        "image_source": draft.image_source,
        "image_candidates": candidates_rel,
        "created_at": draft.created_at,
        "approved_at": draft.approved_at,
        "status": status,
        "analysis": analysis or {},
    }
    return out


class _Handler(BaseHTTPRequestHandler):
    def log_message(self, fmt: str, *args) -> None:
        logger.info("%s - " + fmt, self.address_string(), *args)

    def do_HEAD(self) -> None:
        if not _require_auth(self):
            return
        parsed = urlparse(self.path)
        path = unquote(parsed.path)
        if path == "/":
            path = "/index.html"
        if path.startswith("/api/"):
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            return
        safe_root = REVIEW_DIR.resolve()
        file_path = (safe_root / path.lstrip("/")).resolve()
        if not str(file_path).startswith(str(safe_root)) or not file_path.exists() or file_path.is_dir():
            self.send_error(404, "Not found")
            return
        mime, _ = mimetypes.guess_type(str(file_path))
        mime = mime or "application/octet-stream"
        self.send_response(200)
        self.send_header("Content-Type", mime)
        self.send_header("Content-Length", str(file_path.stat().st_size))
        self.end_headers()

    def do_GET(self) -> None:
        if not _require_auth(self):
            return
        parsed = urlparse(self.path)
        path = unquote(parsed.path)
        query = parse_qs(parsed.query)

        if path == "/" or path == "/index.html":
            _serve_static(self, REVIEW_DIR / "index.html")
            return

        if path.startswith("/api"):
            self._handle_api_get(path, query)
            return

        _serve_static(self, REVIEW_DIR / path.lstrip("/"))

    def _handle_api_get(self, path: str, query: dict) -> None:
        if path == "/api/drafts":
            self._api_drafts(query)
            return
        _json_response(self, 404, {"ok": False, "error": "Unknown endpoint"})

    def _api_drafts(self, query: dict) -> None:
        status = (query.get("status") or ["pending"])[0].lower()
        offset = int((query.get("offset") or ["0"])[0])
        limit = int((query.get("limit") or ["50"])[0])

        if status == "pending":
            drafts = list_pending()
            status_label = "pending"
        elif status == "approved":
            drafts = list_approved()
            status_label = "approved"
        elif status == "rejected":
            drafts = list_rejected()
            status_label = "rejected"
        else:
            _json_response(self, 400, {"ok": False, "error": "status must be pending, approved, or rejected"})
            return

        analysis_map = {}
        total = len(drafts)
        page = drafts[offset : offset + limit]
        out = [_draft_to_json(d, analysis_map.get(d.item_id), status=status_label) for d in page]
        _json_response(
            self,
            200,
            {
                "ok": True,
                "total": total,
                "offset": offset,
                "limit": limit,
                "drafts": out,
            },
        )

    def do_POST(self) -> None:
        if not _require_auth(self):
            return
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
        elif action == "reject":
            self._do_reject(payload)
        elif action == "edit":
            self._do_edit(payload)
        elif action == "agent-edit":
            self._do_agent_edit(payload)
        elif action == "select-image":
            self._do_select_image(payload)
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
        ok = skip_draft(item_id)
        _json_response(self, 200 if ok else 404, {"ok": ok, "item_id": item_id})

    def _do_reject(self, payload: dict) -> None:
        """Reject a draft with optional feedback; moves it to skipped folder."""
        item_id = payload.get("item_id", "").strip()
        feedback = payload.get("feedback", "").strip()
        if not item_id:
            _json_response(self, 400, {"ok": False, "error": "missing item_id"})
            return
        ok = skip_draft(item_id, feedback=feedback)
        _json_response(self, 200 if ok else 404, {"ok": ok, "item_id": item_id})

    def _do_edit(self, payload: dict) -> None:
        item_id = payload.get("item_id", "").strip()
        post = payload.get("linkedin_post", "")
        if not item_id:
            _json_response(self, 400, {"ok": False, "error": "missing item_id"})
            return
        ok = edit_draft(item_id, post)
        _json_response(self, 200 if ok else 404, {"ok": ok, "item_id": item_id})

    def _do_agent_edit(self, payload: dict) -> None:
        """Rewrite the LinkedIn post based on a human prompt via the LLM."""
        item_id = payload.get("item_id", "").strip()
        instruction = payload.get("instruction", "").strip()
        if not item_id:
            _json_response(self, 400, {"ok": False, "error": "missing item_id"})
            return
        if not instruction:
            _json_response(self, 400, {"ok": False, "error": "missing instruction"})
            return
        if not is_available():
            _json_response(self, 503, {"ok": False, "error": "LLM not available"})
            return

        path = _find_draft_path(item_id)
        if not path:
            _json_response(self, 404, {"ok": False, "error": "draft not found"})
            return
        draft = _parse_draft_markdown(path.read_text())
        if not draft:
            _json_response(self, 500, {"ok": False, "error": "could not parse draft"})
            return

        prompt = f"""Rewrite the following LinkedIn post based on this instruction.
Instruction: {instruction}

Current post:
{draft.linkedin_post}

Return ONLY the rewritten LinkedIn post text (no markdown, no JSON, no explanation)."""
        try:
            rewritten = chat(prompt, model=None)
        except Exception as exc:
            logger.exception("Agent edit failed for %s", item_id)
            _json_response(self, 500, {"ok": False, "error": f"LLM failed: {exc}"})
            return
        if not rewritten:
            _json_response(self, 500, {"ok": False, "error": "LLM returned empty response"})
            return
        draft.linkedin_post = rewritten.strip()
        _persist_draft(draft, path)
        _json_response(self, 200, {"ok": True, "item_id": item_id, "linkedin_post": draft.linkedin_post})

    def _do_select_image(self, payload: dict) -> None:
        """Choose a downloaded image candidate as the active image for a draft."""
        item_id = payload.get("item_id", "").strip()
        candidate = payload.get("candidate", "").strip()
        if not item_id or not candidate:
            _json_response(self, 400, {"ok": False, "error": "missing item_id or candidate"})
            return
        path = _find_draft_path(item_id)
        if not path:
            _json_response(self, 404, {"ok": False, "error": "draft not found"})
            return
        draft = _parse_draft_markdown(path.read_text())
        if not draft:
            _json_response(self, 500, {"ok": False, "error": "could not parse draft"})
            return
        candidate_path = Path(candidate)
        if not candidate_path.is_absolute():
            candidate_path = REVIEW_DIR / candidate_path
        if not candidate_path.exists():
            _json_response(self, 404, {"ok": False, "error": "candidate file not found"})
            return
        # Copy selected candidate to IMAGE_DIR with predictable slug
        slug = _slug(draft.title) or item_id
        dest = IMAGE_DIR / f"{slug}.jpg"
        try:
            shutil.copy2(candidate_path, dest)
        except OSError as exc:
            _json_response(self, 500, {"ok": False, "error": f"copy failed: {exc}"})
            return
        draft.image_path = str(dest)
        draft.image_source = "article"
        _persist_draft(draft, path)
        # Copy into review images dir for dashboard preview
        ext = dest.suffix or ".jpg"
        review_dest = REVIEW_IMAGES_DIR / f"{item_id}{ext}"
        REVIEW_IMAGES_DIR.mkdir(parents=True, exist_ok=True)
        try:
            shutil.copy2(dest, review_dest)
        except OSError:
            logger.exception("Failed to copy selected image to review dir")
        rel = str(review_dest.relative_to(REVIEW_DIR))
        _json_response(self, 200, {"ok": True, "item_id": item_id, "image_path": str(dest), "image_url": f"/{rel}"})

    def _do_regenerate_image(self, payload: dict) -> None:
        """Regenerate image via image engine (RunPod/FLUX fallback)."""
        item_id = payload.get("item_id", "").strip()
        if not item_id:
            _json_response(self, 400, {"ok": False, "error": "missing item_id"})
            return

        path = _find_draft_path(item_id)
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
            img_path, img_source = image_for_post(
                item_url=item.item_url,
                title=draft.title,
                day=plan.day_name,
                pillar=draft.pillar,
                linkedin_post=draft.linkedin_post,
                hashtags=" ".join(draft.hashtags),
                skip_og=True,
                item_id=item.id,
            )
        except Exception as exc:
            logger.exception("Image regeneration failed for %s", item_id)
            _json_response(self, 500, {"ok": False, "error": f"image engine failed: {exc}"})
            return

        if not img_path:
            _json_response(self, 500, {"ok": False, "error": "no image returned"})
            return

        draft.image_path = str(img_path)
        draft.image_source = img_source
        item.image_path = str(img_path)
        item.image_source = img_source
        try:
            save_item(item)
        except (OSError, RuntimeError):
            logger.exception("Failed to persist item image_path")

        _persist_draft(draft, path)

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


def _find_draft_path(item_id: str) -> Path | None:
    for path in sorted(QUEUE_DIR.glob("*.md"), reverse=True):
        text = path.read_text()
        draft = _parse_draft_markdown(text)
        if draft and draft.item_id == item_id:
            return path
    return None


def _slug(title: str) -> str:
    import re
    s = title.lower().strip()
    s = re.sub(r"[^\w]+", "-", s)
    return s.strip("-")[:60] or "image"


def _persist_draft(draft: Draft, path: Path) -> None:
    tmp = path.with_suffix(".tmp")
    tmp.write_text(_draft_markdown(draft))
    tmp.replace(path)


def _serve_static(handler: BaseHTTPRequestHandler, file_path: Path) -> None:
    safe_root = REVIEW_DIR.resolve()
    resolved = file_path.resolve()
    if not str(resolved).startswith(str(safe_root)) or not resolved.exists() or resolved.is_dir():
        handler.send_error(404, "Not found")
        return
    mime, _ = mimetypes.guess_type(str(resolved))
    mime = mime or "application/octet-stream"
    data = resolved.read_bytes()
    handler.send_response(200)
    handler.send_header("Content-Type", mime)
    handler.send_header("Content-Length", str(len(data)))
    handler.end_headers()
    handler.wfile.write(data)


def run_server(host: str = "127.0.0.1", port: int = 8080) -> None:
    ensure_dirs()
    server = HTTPServer((host, port), _Handler)
    logger.info("Review server listening on http://%s:%s", host, port)
    print(f"Review server listening on http://{host}:{port}")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nShutting down review server.")
        server.shutdown()


import os

if __name__ == "__main__":
    run_server()
