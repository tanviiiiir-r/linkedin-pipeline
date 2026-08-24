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
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path
from urllib.parse import unquote, urlparse

from config.calendar import day_plan
from config.settings import QUEUE_DIR, REVIEW_DIR, ensure_dirs
from pipeline.approval import approve_draft, edit_draft, skip_draft
from pipeline.content_analyst import analyze_queued_items
from pipeline.drafting import Draft, _draft_markdown, _parse_draft_markdown, load_drafts
from pipeline.image_engine import IMAGE_DIR, image_for_post
from pipeline.llm_client import chat, is_available
from pipeline.storage import load_item, save_item

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



def _slug(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", "_", text.lower()).strip("_")[:60]


def _draft_path(item_id: str) -> Path | None:
    for p in sorted(QUEUE_DIR.glob("*.md"), reverse=True):
        text = p.read_text()
        draft = _parse_draft_markdown(text)
        if draft and draft.item_id == item_id:
            return p
    return None


def _persist_draft(draft: Draft, path: Path) -> None:
    backup = path.with_suffix(".md.bak")
    backup.write_text(path.read_text())
    tmp = path.with_suffix(".tmp")
    tmp.write_text(_draft_markdown(draft))
    tmp.replace(path)

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
            # Pagination via query string (e.g. /api/drafts?offset=2)
            query = urlparse(self.path).query
            offset_match = re.search(r"(?:^|&)offset=(\d+)", query)
            offset = int(offset_match.group(1)) if offset_match else 0
            total = len(pending)
            page = pending[offset:] if offset < total else []
            out = []
            for draft in page:
                a = analysis_by_id.get(draft.item_id)
                # Resolve candidate URLs relative to review dir
                candidates = []
                for cand in draft.image_candidates or []:
                    cand_path = Path(cand)
                    if cand_path.exists():
                        try:
                            rel = cand_path.relative_to(REVIEW_DIR)
                            candidates.append(f"/{rel.as_posix()}")
                        except ValueError:
                            candidates.append(cand)
                    else:
                        candidates.append(cand)
                out.append({
                    "item_id": draft.item_id,
                    "title": draft.title,
                    "pillar": draft.pillar,
                    "source_url": draft.source_url,
                    "image_path": draft.image_path,
                    "image_source": draft.image_source,
                    "image_candidates": candidates,
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
            _json_response(self, 200, {
                "ok": True,
                "total": total,
                "offset": offset,
                "drafts": out,
            })
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
        ok = skip_draft(item_id, skipped_dir=REVIEW_SKIPPED_DIR)
        _json_response(self, 200 if ok else 404, {"ok": ok, "item_id": item_id})

    def _do_reject(self, payload: dict) -> None:
        """Reject a draft with feedback; moves it to skipped folder and stores reason."""
        item_id = payload.get("item_id", "").strip()
        feedback = payload.get("feedback", "").strip()
        if not item_id:
            _json_response(self, 400, {"ok": False, "error": "missing item_id"})
            return
        path = _draft_path(item_id)
        if not path:
            _json_response(self, 404, {"ok": False, "error": "draft not found"})
            return
        draft = _parse_draft_markdown(path.read_text())
        if not draft:
            _json_response(self, 500, {"ok": False, "error": "could not parse draft"})
            return
        draft.published = False
        draft.approved = False
        # Append feedback to newsletter section for future review
        if feedback:
            draft.newsletter_section += f"\n\n**Rejection feedback:** {feedback}"
        _persist_draft(draft, path)
        ok = skip_draft(item_id, skipped_dir=REVIEW_SKIPPED_DIR)
        _json_response(self, 200 if ok else 500, {"ok": ok, "item_id": item_id})

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

        path = _draft_path(item_id)
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
        path = _draft_path(item_id)
        if not path:
            _json_response(self, 404, {"ok": False, "error": "draft not found"})
            return
        draft = _parse_draft_markdown(path.read_text())
        if not draft:
            _json_response(self, 500, {"ok": False, "error": "could not parse draft"})
            return
        candidate_path = Path(candidate)
        if not candidate_path.is_absolute():
            candidate_path = Path.cwd() / candidate_path
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

        # Persist image path on draft and item
        draft.image_path = str(img_path)
        draft.image_source = img_source
        item.image_path = str(img_path)
        item.image_source = img_source
        try:
            save_item(item)
        except (OSError, RuntimeError):
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

if __name__ == "__main__":
    run_server()
