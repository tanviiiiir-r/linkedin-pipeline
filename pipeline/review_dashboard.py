"""Generate a static review dashboard for LinkedIn drafts.

Usage:
    from pipeline.review_dashboard import generate_dashboard
    generate_dashboard()

CLI wrapper lives in pipeline/hermes.py (`review-dashboard`).
"""
from __future__ import annotations

import html
import logging
import shutil
from datetime import datetime, timezone
from pathlib import Path

from config.calendar import day_plan
from config.settings import QUEUE_DIR, REVIEW_DIR, ensure_dirs
from pipeline.approval import list_pending
from pipeline.content_analyst import analyze_queued_items
from pipeline.drafting import Draft

logger = logging.getLogger(__name__)

ASSETS_DIR = Path(__file__).with_suffix("").parent / "review_assets"
REVIEW_IMAGES_DIR = REVIEW_DIR / "images"
REVIEW_SKIPPED_DIR = QUEUE_DIR / "skipped"


def _asset_path(name: str) -> Path:
    return REVIEW_DIR / "assets" / name


def _ensure_assets() -> None:
    (_review_css := _asset_path("style.css")).parent.mkdir(parents=True, exist_ok=True)
    _review_css.write_text(_CSS)


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


def _score_color(score: int) -> str:
    if score >= 80:
        return "good"
    if score >= 60:
        return "warn"
    return "bad"


def _bar(score: int) -> str:
    filled = round(score / 10)
    empty = 10 - filled
    return "●" * filled + "○" * empty


def _draft_card(draft: Draft, analysis: dict | None, image_rel: str | None) -> str:
    title_escaped = html.escape(draft.title)
    post_escaped = html.escape(draft.linkedin_post).replace("\n", "\u003cbr\u003e")
    hashtags = " ".join(html.escape(t) for t in draft.hashtags)
    rel = analysis or {}
    rel_score = rel.get("relevance_score", 0)
    acc_score = rel.get("accuracy_score", 0)
    perf_score = rel.get("perfection_score", 0)
    issues = rel.get("issues", [])
    action = rel.get("proposed_action", "—")

    image_html = ""
    if image_rel:
        image_html = f'''
        <div class="image-box">
            <img src="images/{html.escape(Path(image_rel).name)}" alt="Draft image" loading="lazy" />
        </div>'''

    issues_html = ""
    if issues:
        issues_html = "\n".join(f"        <li>⚠️ {html.escape(str(i))}</li>" for i in issues)
        issues_html = f"      <ul class=\"issues\"\u003e\n{issues_html}\n      </ul\u003e"

    return f'''
    <article class="draft-card" data-item-id="{html.escape(draft.item_id)}" data-pillar="{html.escape(draft.pillar)}">
      <div class="card-header">
        <div class="meta">
          <span class="day-badge">{html.escape(day_plan().day_name)}</span>
          <span class="pillar">{html.escape(draft.pillar.replace('_', ' ').title())}</span>
          <span class="item-id">#{html.escape(draft.item_id[:8])}</span>
        </div>
        <h2>{title_escaped}</h2>
        <a href="{html.escape(draft.source_url)}" target="_blank" rel="noopener" class="source-link">Source →</a>
      </div>
{image_html}
      <div class="post-preview">
        <div class="post-body" id="post-{html.escape(draft.item_id)}">{post_escaped}</div>
        <div class="hashtags">{hashtags}</div>
      </div>
      <div class="quality-card">
        <div class="score-row">
          <span>Relevance</span>
          <span class="score {_score_color(rel_score)}">{rel_score}/100 {_bar(rel_score)}</span>
        </div>
        <div class="score-row">
          <span>Accuracy</span>
          <span class="score {_score_color(acc_score)}">{acc_score}/100 {_bar(acc_score)}</span>
        </div>
        <div class="score-row">
          <span>Perfection</span>
          <span class="score {_score_color(perf_score)}">{perf_score}/100 {_bar(perf_score)}</span>
        </div>
        <div class="action-line">Proposed action: <strong>{html.escape(action)}</strong></div>
{issues_html}
      </div>
      <div class="actions">
        <button class="btn approve" onclick="approve('{html.escape(draft.item_id)}')">✅ Approve</button>
        <button class="btn edit" onclick="startEdit('{html.escape(draft.item_id)}')">✏️ Edit</button>
        <button class="btn image" onclick="regenerateImage('{html.escape(draft.item_id)}')">🔄 Regenerate image</button>
        <button class="btn skip" onclick="skip('{html.escape(draft.item_id)}')">⏭ Skip</button>
      </div>
      <div class="edit-box" id="edit-{html.escape(draft.item_id)}" style="display:none;">
        <textarea id="textarea-{html.escape(draft.item_id)}" rows="10">{html.escape(draft.linkedin_post)}</textarea>
        <div class="edit-actions">
          <button class="btn save" onclick="saveEdit('{html.escape(draft.item_id)}')">💾 Save</button>
          <button class="btn cancel" onclick="cancelEdit('{html.escape(draft.item_id)}')">Cancel</button>
        </div>
      </div>
    </article>'''


def _empty_state() -> str:
    return '''
    <article class="draft-card empty">
      <h2>No pending drafts</h2>
      <p>Run <code>python run.py draft-today --with-image</code> to create one.</p>
    </article>'''


def generate_dashboard() -> Path:
    """Generate data/review/index.html from pending drafts."""
    ensure_dirs()
    _ensure_assets()
    REVIEW_SKIPPED_DIR.mkdir(parents=True, exist_ok=True)

    pending = list_pending()
    # Run analysis across pending drafts for today
    analysis_results = analyze_queued_items(limit=50) if pending else []
    analysis_by_id = {r.item_id: r for r in analysis_results}

    cards: list[str] = []
    for draft in pending:
        analysis = analysis_by_id.get(draft.item_id)
        analysis_dict = None
        if analysis:
            analysis_dict = {
                "relevance_score": analysis.relevance_score,
                "accuracy_score": analysis.accuracy_score,
                "perfection_score": analysis.perfection_score,
                "issues": analysis.issues,
                "proposed_action": analysis.proposed_action,
            }
        image_rel = _copy_image_for_review(draft.image_path, draft.item_id)
        cards.append(_draft_card(draft, analysis_dict, image_rel))

    body = "\n".join(cards) if cards else _empty_state()

    index_path = REVIEW_DIR / "index.html"
    index_path.write_text(_HTML_TEMPLATE.format(
        generated_at=datetime.now(timezone.utc).isoformat(),
        count=len(cards),
        body=body,
    ))
    logger.info("Review dashboard generated: %s (%s drafts)", index_path, len(cards))
    return index_path


_HTML_TEMPLATE = '''<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1.0" />
  <title>Review — LinkedIn Drafts</title>
  <link rel="stylesheet" href="assets/style.css" />
</head>
<body>
  <header>
    <div class="wrap">
      <h1>🔗 LinkedIn Draft Review</h1>
      <p class="sub">Human approval gate. Approve, edit, skip, or regenerate images before publishing.</p>
      <nav class="tabs">
        <button class="tab active" disabled>LinkedIn</button>
        <!-- Tabs reserved for future workstreams -->
      </nav>
      <div class="stats">
        <span>{count} pending draft(s)</span>
        <span class="generated">Generated {generated_at}</span>
      </div>
    </div>
  </header>
  <main class="wrap">
{body}
  </main>
  <footer class="wrap">
    <p class="note">No post is published from this screen. After approval, run <code>python run.py publish --dry-run</code> or the full publish command.</p>
  </footer>
  <script>
    async function api(path, payload) {{
      const r = await fetch('/api' + path, {{
        method: 'POST',
        headers: {{'Content-Type': 'application/json'}},
        body: JSON.stringify(payload)
      }});
      return r.json();
    }}
    async function approve(id) {{
      const data = await api('/approve', {{item_id: id}});
      if (data.ok) document.querySelector(`article[data-item-id="${{id}}"]`).classList.add('approved');
      alert(data.ok ? 'Approved' : 'Failed: ' + (data.error || 'unknown'));
    }}
    async function skip(id) {{
      if (!confirm('Skip this draft? It will be moved to the skipped folder.')) return;
      const data = await api('/skip', {{item_id: id}});
      if (data.ok) document.querySelector(`article[data-item-id="${{id}}"]`).remove();
      alert(data.ok ? 'Skipped' : 'Failed: ' + (data.error || 'unknown'));
    }}
    function startEdit(id) {{
      document.getElementById('edit-' + id).style.display = 'block';
    }}
    function cancelEdit(id) {{
      document.getElementById('edit-' + id).style.display = 'none';
    }}
    async function saveEdit(id) {{
      const text = document.getElementById('textarea-' + id).value;
      const data = await api('/edit', {{item_id: id, linkedin_post: text}});
      if (data.ok) {{
        document.getElementById('post-' + id).innerHTML = text.replace(/\n/g, '<br>');
        cancelEdit(id);
      }}
      alert(data.ok ? 'Saved' : 'Failed: ' + (data.error || 'unknown'));
    }}
    async function regenerateImage(id) {{
      if (!confirm('This may wake and run your RunPod ComfyUI pod. Continue?')) return;
      const btn = event.target;
      btn.disabled = true;
      btn.textContent = 'Running…';
      const data = await api('/regenerate-image', {{item_id: id}});
      btn.disabled = false;
      btn.textContent = '🔄 Regenerate image';
      if (data.ok && data.image_url) {{
        const card = document.querySelector(`article[data-item-id="${{id}}"]`);
        let box = card.querySelector('.image-box');
        const imgHtml = `<div class="image-box"><img src="${{data.image_url}}" alt="Draft image" /></div>`;
        if (box) box.outerHTML = imgHtml;
        else card.querySelector('.post-preview').insertAdjacentHTML('beforebegin', imgHtml);
      }}
      alert(data.ok ? 'Image regenerated' : 'Failed: ' + (data.error || 'unknown'));
    }}
  </script>
</body>
</html>'''


_CSS = '''
:root {{
  --bg: #0f1115;
  --card: #161922;
  --line: #2a2f3a;
  --txt: #e2e8f0;
  --mut: #94a3b8;
  --ok: #4ade80;
  --warn: #facc15;
  --bad: #f87171;
  --accent: #60a5fa;
}}
* {{ box-sizing: border-box; }}
body {{
  margin: 0;
  font-family: ui-sans-serif, system-ui, -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif;
  background: var(--bg);
  color: var(--txt);
  line-height: 1.55;
}}
.wrap {{
  max-width: 760px;
  margin: 0 auto;
  padding: 0 18px;
}}
header {{
  border-bottom: 1px solid var(--line);
  padding: 24px 0 18px;
  margin-bottom: 24px;
}}
h1 {{ margin: 0 0 6px; font-size: 24px; }}
.sub {{ color: var(--mut); margin: 0 0 16px; }}
.tabs {{
  display: flex;
  gap: 8px;
  margin-bottom: 16px;
}}
.tab {{
  background: transparent;
  border: 1px solid var(--line);
  color: var(--mut);
  padding: 8px 14px;
  border-radius: 999px;
  font-size: 14px;
}}
.tab.active {{
  background: var(--card);
  color: var(--txt);
  border-color: var(--accent);
}}
.stats {{
  display: flex;
  justify-content: space-between;
  color: var(--mut);
  font-size: 13px;
}}
.generated {{ font-family: ui-monospace, monospace; }}
.draft-card {{
  background: var(--card);
  border: 1px solid var(--line);
  border-radius: 14px;
  padding: 18px;
  margin: 18px 0;
}}
.draft-card.approved {{
  border-color: var(--ok);
  opacity: 0.85;
}}
.card-header {{
  display: flex;
  flex-wrap: wrap;
  gap: 8px;
  align-items: baseline;
  justify-content: space-between;
  margin-bottom: 12px;
}}
.meta {{
  display: flex;
  gap: 8px;
  align-items: center;
  flex-wrap: wrap;
}}
.day-badge {{
  background: var(--accent);
  color: #0b1020;
  padding: 2px 10px;
  border-radius: 999px;
  font-size: 12px;
  font-weight: 600;
}}
.pillar {{
  color: var(--mut);
  font-size: 13px;
  text-transform: capitalize;
}}
.item-id {{
  color: var(--mut);
  font-size: 12px;
  font-family: ui-monospace, monospace;
}}
h2 {{
  font-size: 18px;
  margin: 0;
  flex: 1 1 100%;
}}
.source-link {{
  color: var(--accent);
  font-size: 13px;
  text-decoration: none;
}}
.image-box {{
  margin: 14px 0;
  border-radius: 10px;
  overflow: hidden;
  border: 1px solid var(--line);
}}
.image-box img {{
  display: block;
  width: 100%;
  height: auto;
}}
.post-preview {{
  background: #0b1020;
  border: 1px solid var(--line);
  border-radius: 10px;
  padding: 14px;
  margin: 14px 0;
  white-space: pre-wrap;
}}
.post-body {{
  font-size: 15px;
  margin-bottom: 10px;
}}
.hashtags {{
  color: var(--accent);
  font-size: 14px;
}}
.quality-card {{
  background: #0b1020;
  border: 1px solid var(--line);
  border-radius: 10px;
  padding: 14px;
  margin: 14px 0;
}}
.score-row {{
  display: flex;
  justify-content: space-between;
  align-items: center;
  padding: 4px 0;
  font-size: 14px;
}}
.score {{
  font-family: ui-monospace, monospace;
  font-size: 13px;
}}
.good {{ color: var(--ok); }}
.warn {{ color: var(--warn); }}
.bad {{ color: var(--bad); }}
.action-line {{
  margin-top: 8px;
  font-size: 13px;
  color: var(--mut);
}}
.issues {{
  margin: 10px 0 0 18px;
  padding: 0;
  font-size: 13px;
  color: var(--warn);
}}
.actions {{
  display: flex;
  flex-wrap: wrap;
  gap: 8px;
  margin-top: 14px;
}}
.btn {{
  background: var(--line);
  color: var(--txt);
  border: 1px solid var(--line);
  padding: 8px 14px;
  border-radius: 8px;
  cursor: pointer;
  font-size: 14px;
}}
.btn:hover {{ opacity: 0.85; }}
.btn.approve {{ background: #14532d; border-color: #22c55e; }}
.btn.edit {{ background: #1e3a8a; border-color: #3b82f6; }}
.btn.image {{ background: #581c87; border-color: #a855f7; }}
.btn.skip {{ background: #450a0a; border-color: #ef4444; }}
.btn.save {{ background: #14532d; border-color: #22c55e; }}
.btn.cancel {{ background: transparent; }}
.edit-box {{
  margin-top: 14px;
}}
.edit-box textarea {{
  width: 100%;
  background: #0b1020;
  color: var(--txt);
  border: 1px solid var(--line);
  border-radius: 8px;
  padding: 10px;
  font-family: inherit;
  font-size: 14px;
}}
.edit-actions {{
  display: flex;
  gap: 8px;
  margin-top: 8px;
}}
.empty {{
  text-align: center;
  color: var(--mut);
}}
footer {{
  border-top: 1px solid var(--line);
  margin-top: 32px;
  padding: 18px 0 40px;
}}
.note {{
  color: var(--mut);
  font-size: 13px;
}}
code {{
  font-family: ui-monospace, monospace;
  background: #0b1020;
  padding: 2px 5px;
  border-radius: 4px;
}}
@media (max-width: 520px) {{
  .stats {{ flex-direction: column; gap: 4px; }}
  h2 {{ font-size: 16px; }}
}}
'''


if __name__ == "__main__":
    path = generate_dashboard()
    print(path)
