"""Generate a polished review dashboard for LinkedIn drafts.

The dashboard renders each draft inside a LinkedIn-style post preview so the
operator sees exactly how the post will look in the feed before approving.
"""
from __future__ import annotations

import html
import logging
import shutil
from pathlib import Path

from config.calendar import day_plan
from config.settings import QUEUE_DIR, REVIEW_DIR, ensure_dirs
from pipeline.approval import list_pending
from pipeline.drafting import Draft

logger = logging.getLogger(__name__)

REVIEW_IMAGES_DIR = REVIEW_DIR / "images"
REVIEW_SKIPPED_DIR = QUEUE_DIR / "skipped"


def _asset_path(name: str) -> Path:
    return REVIEW_DIR / "assets" / name


def _ensure_assets() -> None:
    (_css := _asset_path("style.css")).parent.mkdir(parents=True, exist_ok=True)
    _css.write_text(_CSS)
    (_js := _asset_path("app.js")).write_text(_JS)


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


def _link_preview(draft: Draft, image_rel: str | None) -> str:
    """Render a LinkedIn-style link preview card when no image is provided."""
    if image_rel:
        return f'''
      <div class="ln-image">
        <img src="images/{html.escape(Path(image_rel).name)}" alt="" loading="lazy" />
      </div>'''
    from urllib.parse import urlparse
    try:
        domain = urlparse(draft.source_url).netloc.replace("www.", "")
    except ValueError as exc:
        logger.warning("Could not parse source URL for link preview: %s", exc)
        domain = "Source"
    if not domain:
        domain = "Source"
    return f'''
      <a class="ln-link-card" href="{html.escape(draft.source_url)}" target="_blank" rel="noopener">
        <div class="ln-link-placeholder">
          <div class="ln-link-icon">🔗</div>
          <div class="ln-link-title">{html.escape(draft.title[:90])}</div>
        </div>
        <div class="ln-link-domain">{html.escape(domain)}</div>
      </a>'''


def _format_post_body(text: str) -> str:
    """Format the LinkedIn post body for preview: keep line breaks, bold bullet-like markers."""
    text = html.escape(text)
    text = text.replace("\n", "<br />")
    # Highlight leading bullets
    text = re_sub_bullets(text)
    return text


def re_sub_bullets(text: str) -> str:
    import re
    return re.sub(r"(^|<br /\u003e)([•·\-\*])\s+", r"\1\2 ", text)


def _draft_card(draft: Draft, analysis: dict | None, image_rel: str | None) -> str:
    title_escaped = html.escape(draft.title)
    body_html = _format_post_body(draft.linkedin_post)
    hashtags = " ".join(f"<span>{html.escape(t)}</span>" for t in draft.hashtags)
    rel = analysis or {}
    rel_score = rel.get("relevance_score", 0)
    acc_score = rel.get("accuracy_score", 0)
    perf_score = rel.get("perfection_score", 0)
    issues = rel.get("issues", [])
    action = rel.get("proposed_action", "—")
    plan = day_plan()

    issues_html = ""
    if issues:
        issues_html = "\n".join(f"        <li>{html.escape(str(i))}</li>" for i in issues)
        issues_html = f"      <ul class=\"issues\"\u003e\n{issues_html}\n      </ul\u003e"

    linkedin_preview = f'''
    <div class="ln-post minimal">
      <div class="ln-body" id="post-{html.escape(draft.item_id)}">{body_html}</div>
      <div class="ln-hashtags">{hashtags}</div>
{_link_preview(draft, image_rel)}
    </div>'''

    return f'''
    <article class="draft-card" data-item-id="{html.escape(draft.item_id)}" data-pillar="{html.escape(draft.pillar)}">
      <div class="card-meta">
        <div class="left">
          <span class="day-badge">{html.escape(plan.day_name)}</span>
          <span class="pillar">{html.escape(draft.pillar.replace('_', ' ').title())}</span>
          <span class="item-id">#{html.escape(draft.item_id[:8])}</span>
        </div>
        <a class="source-link" href="{html.escape(draft.source_url)}" target="_blank" rel="noopener">Source →</a>
      </div>
      <h2 class="draft-title">{title_escaped}</h2>

      <div class="preview-shell">
        <div class="preview-label">LinkedIn preview</div>
{linkedin_preview}
      </div>

      <div class="quality-card">
        <div class="score-row">
          <span>Relevance</span>
          <span class="score {_score_color(rel_score)}">{rel_score}/100 <span class="bar">{_bar(rel_score)}</span></span>
        </div>
        <div class="score-row">
          <span>Accuracy</span>
          <span class="score {_score_color(acc_score)}">{acc_score}/100 <span class="bar">{_bar(acc_score)}</span></span>
        </div>
        <div class="score-row">
          <span>Perfection</span>
          <span class="score {_score_color(perf_score)}">{perf_score}/100 <span class="bar">{_bar(perf_score)}</span></span>
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
        <textarea id="textarea-{html.escape(draft.item_id)}" rows="12">{html.escape(draft.linkedin_post)}</textarea>
        <div class="edit-actions">
          <button class="btn save" onclick="saveEdit('{html.escape(draft.item_id)}')">💾 Save</button>
          <button class="btn cancel" onclick="cancelEdit('{html.escape(draft.item_id)}')">Cancel</button>
        </div>
      </div>
    </article>'''


def _bar(score: int) -> str:
    filled = round(score / 10)
    empty = 10 - filled
    return "█" * filled + "░" * empty


def _empty_state() -> str:
    return '''
    <article class="draft-card empty">
      <div class="empty-icon">📭</div>
      <h2>No pending drafts</h2>
      <p>Run <code>python run.py draft-today --with-image</code> to create one for review.</p>
    </article>'''


def generate_dashboard() -> Path:
    """Generate data/review/index.html from pending drafts."""
    ensure_dirs()
    _ensure_assets()
    REVIEW_SKIPPED_DIR.mkdir(parents=True, exist_ok=True)

    pending = list_pending()
    # Copy active images and candidate images into review/images for the dashboard
    for draft in pending:
        _copy_image_for_review(draft.image_path, draft.item_id)
        for cand in draft.image_candidates or []:
            cand_path = Path(cand)
            if not cand_path.exists():
                continue
            try:
                rel = cand_path.relative_to(REVIEW_DIR)
                dest = REVIEW_IMAGES_DIR / rel.name
            except ValueError:
                ext = cand_path.suffix or ".jpg"
                dest = REVIEW_IMAGES_DIR / f"{draft.item_id}_cand_{len(list(REVIEW_IMAGES_DIR.glob(f'{draft.item_id}*')))}{ext}"
            try:
                shutil.copy2(cand_path, dest)
            except OSError:
                logger.exception("Failed to copy candidate image %s", cand_path)

    plan = day_plan()
    index_path = REVIEW_DIR / "index.html"
    index_path.write_text(_HTML_TEMPLATE.format(
        day=html.escape(plan.day_name),
        pillar=html.escape(plan.post_type.replace('_', ' ').title()),
    ))
    logger.info("Review dashboard generated: %s (%s drafts)", index_path, len(pending))
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
  <header class="site-header">
    <div class="wrap">
      <div class="brand">
        <div class="logo">🔗</div>
        <div>
          <h1>Draft Review</h1>
          <div class="sub">Human approval gate for LinkedIn posts</div>
        </div>
      </div>
      <div class="today">
        <div class="day">{day}</div>
        <div class="pillar">{pillar}</div>
        <div class="counter" id="counter">0 / 0</div>
      </div>
    </div>
  </header>

  <main class="wrap" id="app">
    <div class="loading">Loading drafts…</div>
  </main>

  <footer class="wrap">
    <p class="note">No post is published from this screen. Approve here, then run <code>python run.py publish --dry-run</code>.</p>
  </footer>

  <script src="assets/app.js"></script>
</body>
</html>'''


_CSS = '''
:root {
  --bg: #0b0d10;
  --surface: #13161d;
  --card: #1a1e27;
  --line: #2a3040;
  --txt: #f0f2f7;
  --mut: #8b95a7;
  --ok: #22c55e;
  --warn: #f59e0b;
  --bad: #ef4444;
  --accent: #60a5fa;
  --ln-bg: #ffffff;
  --ln-txt: #1f1f1f;
  --ln-muted: #666666;
  --ln-link: #0a66c2;
  --ln-line: #e0e0e0;
  --ln-hover: #f3f2ef;
}
* { box-sizing: border-box; }
html { scroll-behavior: smooth; }
body {
  margin: 0;
  font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, Helvetica, Arial, sans-serif;
  background: var(--bg);
  color: var(--txt);
  line-height: 1.5;
}
.wrap {
  max-width: 860px;
  margin: 0 auto;
  padding: 0 18px;
}
.site-header {
  border-bottom: 1px solid var(--line);
  background: linear-gradient(180deg, rgba(96,165,250,0.08) 0%, transparent 100%);
}
.site-header .wrap {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 16px;
  padding-top: 22px;
  padding-bottom: 22px;
}
.brand { display: flex; align-items: center; gap: 12px; }
.logo {
  width: 44px; height: 44px; border-radius: 12px; background: var(--accent);
  color: #0b1020; display: flex; align-items: center; justify-content: center;
  font-size: 22px;
}
h1 { margin: 0; font-size: 20px; font-weight: 700; letter-spacing: -0.3px; }
.sub { color: var(--mut); font-size: 13px; margin-top: 2px; }
.today { text-align: right; }
.today .day { font-size: 14px; font-weight: 600; color: var(--accent); }
.today .pillar { font-size: 13px; color: var(--mut); text-transform: capitalize; }
.counter { font-size: 12px; color: var(--mut); margin-top: 4px; }
.loading { text-align: center; padding: 80px 20px; color: var(--mut); }
.empty { text-align: center; padding: 80px 20px; color: var(--mut); }
.empty-icon { font-size: 48px; margin-bottom: 12px; }

/* Draft navigator */
.nav-bar {
  display: flex; justify-content: space-between; align-items: center;
  gap: 12px; margin: 18px 0;
}
.nav-bar button {
  background: var(--surface); color: var(--txt); border: 1px solid var(--line);
  padding: 8px 16px; border-radius: 8px; cursor: pointer; font-size: 14px;
}
.nav-bar button:disabled { opacity: 0.4; cursor: not-allowed; }

/* Draft card */
.draft-card {
  background: var(--card); border: 1px solid var(--line); border-radius: 16px;
  padding: 20px; margin: 18px 0;
}
.draft-card.approved { border-color: var(--ok); opacity: 0.8; }
.draft-card.rejected { border-color: var(--bad); opacity: 0.7; }
.card-meta {
  display: flex; align-items: center; justify-content: space-between;
  gap: 12px; margin-bottom: 12px; flex-wrap: wrap;
}
.card-meta .left { display: flex; align-items: center; gap: 8px; flex-wrap: wrap; }
.day-badge {
  background: rgba(96,165,250,0.15); color: var(--accent);
  padding: 3px 10px; border-radius: 999px; font-size: 12px; font-weight: 600;
}
.pillar { color: var(--mut); font-size: 13px; text-transform: capitalize; }
.item-id { color: var(--mut); font-size: 12px; font-family: ui-monospace, monospace; }
.source-link { color: var(--accent); font-size: 13px; text-decoration: none; font-weight: 500; }
.draft-title { font-size: 19px; font-weight: 600; margin: 0 0 16px; color: var(--txt); }

/* LinkedIn preview */
.preview-shell {
  background: var(--bg); border: 1px solid var(--line); border-radius: 14px;
  padding: 14px; margin-bottom: 16px;
}
.preview-label { font-size: 11px; text-transform: uppercase; letter-spacing: 0.6px; color: var(--mut); margin-bottom: 10px; }
.ln-post {
  background: var(--ln-bg); color: var(--ln-txt); border: 1px solid var(--ln-line);
  border-radius: 10px; max-width: 680px; margin: 0 auto; overflow: hidden;
}
.ln-post.minimal { padding: 16px; }
.ln-body { font-size: 15px; line-height: 1.55; color: var(--ln-txt); white-space: pre-wrap; margin-bottom: 10px; }
.ln-hashtags { color: var(--ln-link); font-size: 14px; font-weight: 600; margin-bottom: 14px; }
.ln-hashtags span { margin-right: 6px; }
.ln-image {
  border-top: 1px solid var(--ln-line); width: 100%;
  aspect-ratio: 1.91 / 1; background: #f3f2ef; overflow: hidden;
}
.ln-image img { width: 100%; height: 100%; object-fit: cover; display: block; }

/* Image gallery */
.image-gallery {
  margin: 14px 0; border: 1px solid var(--line); border-radius: 12px; padding: 12px;
  background: var(--surface);
}
.gallery-label { font-size: 12px; color: var(--mut); margin-bottom: 8px; text-transform: uppercase; letter-spacing: 0.5px; }
.gallery-thumbs { display: flex; gap: 10px; flex-wrap: wrap; }
.gallery-thumb {
  width: 120px; height: 70px; border-radius: 8px; object-fit: cover; cursor: pointer;
  border: 2px solid transparent; background: var(--card);
}
.gallery-thumb:hover { border-color: var(--accent); }
.gallery-thumb.selected { border-color: var(--ok); }

/* Quality card */
.quality-card {
  background: var(--surface); border: 1px solid var(--line); border-radius: 12px;
  padding: 14px; margin-bottom: 14px;
}
.score-row { display: flex; justify-content: space-between; align-items: center; padding: 5px 0; font-size: 14px; }
.score { font-family: ui-monospace, SFMono-Regular, Menlo, Consolas, monospace; font-size: 13px; }
.bar { letter-spacing: 1px; }
.good { color: var(--ok); }
.warn { color: var(--warn); }
.bad { color: var(--bad); }
.action-line { margin-top: 10px; font-size: 13px; color: var(--mut); }
.issues { margin: 10px 0 0 18px; padding: 0; font-size: 13px; color: var(--warn); }

/* Actions */
.actions { display: flex; flex-wrap: wrap; gap: 8px; margin-bottom: 14px; }
.btn {
  background: var(--surface); color: var(--txt); border: 1px solid var(--line);
  padding: 9px 16px; border-radius: 9px; cursor: pointer; font-size: 14px; font-weight: 500;
  transition: transform 0.05s ease, opacity 0.15s ease;
}
.btn:hover { opacity: 0.85; transform: translateY(-1px); }
.btn.approve { background: rgba(34,197,94,0.15); color: var(--ok); border-color: rgba(34,197,94,0.35); }
.btn.edit { background: rgba(96,165,250,0.12); color: var(--accent); border-color: rgba(96,165,250,0.3); }
.btn.image { background: rgba(168,85,247,0.12); color: #c084fc; border-color: rgba(168,85,247,0.3); }
.btn.skip { background: rgba(239,68,68,0.1); color: var(--bad); border-color: rgba(239,68,68,0.3); }
.btn.reject { background: rgba(239,68,68,0.15); color: var(--bad); border-color: rgba(239,68,68,0.4); }
.btn.save { background: rgba(34,197,94,0.15); color: var(--ok); border-color: rgba(34,197,94,0.35); }
.btn.cancel { background: transparent; color: var(--mut); }

/* Edit panel */
.edit-panel {
  background: var(--surface); border: 1px solid var(--line); border-radius: 12px;
  padding: 14px; margin-bottom: 14px;
}
.edit-label { font-size: 12px; color: var(--mut); margin-bottom: 6px; text-transform: uppercase; letter-spacing: 0.5px; }
.edit-panel textarea {
  width: 100%; background: var(--bg); color: var(--txt); border: 1px solid var(--line);
  border-radius: 10px; padding: 12px; font-family: inherit; font-size: 15px;
  line-height: 1.5; resize: vertical;
}
.edit-actions { display: flex; gap: 8px; margin-top: 8px; }

/* Reject box */
.reject-box { display: none; margin-top: 14px; }
.reject-box.active { display: block; }

footer { border-top: 1px solid var(--line); margin-top: 32px; padding: 20px 0 48px; }
.note { color: var(--mut); font-size: 13px; }
code { font-family: ui-monospace, SFMono-Regular, Menlo, Consolas, monospace; background: var(--surface); padding: 2px 6px; border-radius: 5px; }
@media (max-width: 560px) {
  .site-header .wrap { flex-direction: column; align-items: flex-start; }
  .today { text-align: left; }
  .ln-post.minimal { padding: 12px; }
  .ln-body { font-size: 14px; }
  .draft-card { padding: 16px; }
}
'''


_JS = '''
async function api(path, payload) {
  const r = await fetch('/api' + path, {
    method: 'POST',
    headers: {'Content-Type': 'application/json'},
    body: JSON.stringify(payload)
  });
  return r.json();
}

async function approve(id) {
  const data = await api('/approve', {item_id: id});
  if (data.ok) {
    const card = document.querySelector(`article[data-item-id="${id}"]`);
    card.classList.add('approved');
    card.querySelector('.btn.approve').textContent = '✅ Approved';
  }
  alert(data.ok ? 'Approved — ready to publish' : 'Failed: ' + (data.error || 'unknown'));
}

async function skip(id) {
  if (!confirm('Skip this draft? It will be moved to the skipped folder.')) return;
  const data = await api('/skip', {item_id: id});
  if (data.ok) document.querySelector(`article[data-item-id="${id}"]`).remove();
  alert(data.ok ? 'Skipped' : 'Failed: ' + (data.error || 'unknown'));
}

function startEdit(id) {
  document.getElementById('edit-' + id).style.display = 'block';
  const preview = document.querySelector(`article[data-item-id="${id}"] .preview-shell`);
  if (preview) preview.style.display = 'none';
}

function cancelEdit(id) {
  document.getElementById('edit-' + id).style.display = 'none';
  const preview = document.querySelector(`article[data-item-id="${id}"] .preview-shell`);
  if (preview) preview.style.display = 'block';
}

async function saveEdit(id) {
  const text = document.getElementById('textarea-' + id).value;
  const data = await api('/edit', {item_id: id, linkedin_post: text});
  if (data.ok) {
    const postEl = document.getElementById('post-' + id);
    postEl.innerHTML = text.replace(/\n/g, '<br>');
    cancelEdit(id);
  }
  alert(data.ok ? 'Saved' : 'Failed: ' + (data.error || 'unknown'));
}

async function regenerateImage(id) {
  if (!confirm('This may wake and run your RunPod ComfyUI pod. Continue?')) return;
  const btn = event.target;
  btn.disabled = true;
  const originalText = btn.textContent;
  btn.textContent = '🔄 Running…';
  const data = await api('/regenerate-image', {item_id: id});
  btn.disabled = false;
  btn.textContent = originalText;
  if (data.ok && data.image_url) {
    const card = document.querySelector(`article[data-item-id="${id}"]`);
    let box = card.querySelector('.ln-image');
    const imgHtml = `<div class="ln-image"><img src="${data.image_url}" alt="" /></div>`;
    if (box) box.outerHTML = imgHtml;
    else {
      const hashtags = card.querySelector('.ln-hashtags');
      if (hashtags) hashtags.insertAdjacentHTML('afterend', imgHtml);
      else card.querySelector('.ln-post').insertAdjacentHTML('beforeend', imgHtml);
    }
  }
  alert(data.ok ? 'Image regenerated' : 'Failed: ' + (data.error || 'unknown'));
}
'''


if __name__ == "__main__":
    path = generate_dashboard()
    print(path)
