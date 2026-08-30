"""Generate a polished review dashboard for LinkedIn drafts.

The dashboard renders each draft inside a LinkedIn-style post preview so the
operator sees exactly how the post will look in the feed before approving.
"""
from __future__ import annotations

import html
import logging
from pathlib import Path

from config.calendar import day_plan
from config.settings import QUEUE_DIR, REVIEW_DIR, ensure_dirs
from pipeline.approval import list_pending

logger = logging.getLogger(__name__)

REVIEW_IMAGES_DIR = REVIEW_DIR / "images"
REVIEW_SKIPPED_DIR = QUEUE_DIR / "skipped"


def _asset_path(name: str) -> Path:
    return REVIEW_DIR / "assets" / name


def _ensure_assets() -> None:
    (_css := _asset_path("style.css")).parent.mkdir(parents=True, exist_ok=True)
    _css.write_text(_CSS)
    (_js := _asset_path("app.js")).write_text(_JS)


def _detect_image_extension(path: Path) -> str:
    """Return the real file extension based on image content, not the filename."""
    try:
        from PIL import Image
        with Image.open(path) as im:
            fmt = im.format
            if fmt == "JPEG":
                return ".jpg"
            if fmt == "PNG":
                return ".png"
            if fmt == "WEBP":
                return ".webp"
            if fmt == "GIF":
                return ".gif"
    except (OSError, ImportError, ValueError):
        logger.debug("Could not detect image format for %s", path)
    return path.suffix.lower() or ".png"


def _normalize_image(src: Path, dest: Path) -> Path | None:
    """Copy an image to dest, converting to JPEG if dest extension is .jpg."""
    try:
        from PIL import Image
        with Image.open(src) as im:
            ext = dest.suffix.lower()
            if ext == ".jpg" or ext == ".jpeg":
                rgb = im.convert("RGB")
                rgb.save(dest, "JPEG", quality=90)
            else:
                im.save(dest, im.format or "PNG")
        return dest
    except Exception:
        logger.exception("Failed to normalize image %s to %s", src, dest)
    return None


def _copy_image_for_review(image_path: str, item_id: str) -> str | None:
    if not image_path:
        return None
    src = Path(image_path)
    if not src.exists():
        return None
    ext = _detect_image_extension(src)
    dest = REVIEW_IMAGES_DIR / f"{item_id}{ext}"
    dest.parent.mkdir(parents=True, exist_ok=True)
    try:
        if _normalize_image(src, dest):
            return str(dest.relative_to(REVIEW_DIR))
    except OSError:
        logger.exception("Failed to copy image %s to review dir", src)
    return None


def _score_color(score: int) -> str:
    if score >= 80:
        return "good"
    if score >= 60:
        return "warn"
    return "bad"


def _bar(score: int) -> str:
    filled = round(score / 10)
    empty = 10 - filled
    return "█" * filled + "░" * empty


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
                ext = _detect_image_extension(cand_path)
                dest = REVIEW_IMAGES_DIR / (rel.stem + ext)
            except ValueError:
                ext = _detect_image_extension(cand_path)
                dest = REVIEW_IMAGES_DIR / f"{draft.item_id}_cand_{len(list(REVIEW_IMAGES_DIR.glob(f'{draft.item_id}*')))}{ext}"
            try:
                _normalize_image(cand_path, dest)
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
  <link rel="stylesheet" href="assets/style.css?v=3" />
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

  <main class="wrap">
    <div class="tabs">
      <button class="tab active" data-tab="pending" onclick="switchTab('pending')">⏳ Queued</button>
      <button class="tab" data-tab="approved" onclick="switchTab('approved')">✅ Approved</button>
      <button class="tab" data-tab="rejected" onclick="switchTab('rejected')">🗑 Rejected</button>
    </div>
    <div id="app">
      <div class="loading">Loading drafts…</div>
    </div>
  </main>

  <footer class="wrap">
    <p class="note">No post is published from this screen. Approve here, then run <code>python run.py publish --dry-run</code>.</p>
  </footer>

  <script src="assets/app.js?v=3"></script>
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

.tabs {
  display: flex; gap: 8px; margin: 18px 0;
  border-bottom: 1px solid var(--line); padding-bottom: 8px;
}
.tab {
  background: transparent; color: var(--mut); border: none;
  padding: 8px 14px; border-radius: 8px; cursor: pointer; font-size: 14px;
}
.tab.active { background: var(--surface); color: var(--txt); }
.tab:hover { color: var(--txt); }

.loading { text-align: center; padding: 80px 20px; color: var(--mut); }
.empty { text-align: center; padding: 80px 20px; color: var(--mut); }
.empty-icon { font-size: 48px; margin-bottom: 12px; }

.status-banner {
  background: var(--surface); border: 1px solid var(--line); border-radius: 10px;
  padding: 12px 16px; margin-bottom: 16px; font-size: 14px; color: var(--mut);
}
.status-banner.running { border-color: var(--accent); color: var(--accent); }
.status-banner.success { border-color: var(--ok); color: var(--ok); }
.status-banner.error { border-color: var(--bad); color: var(--bad); }

/* Draft card */
.draft-card {
  background: var(--card); border: 1px solid var(--line); border-radius: 16px;
  padding: 20px; margin: 18px 0;
}
.draft-card.approved { border-color: var(--ok); opacity: 0.9; }
.draft-card.rejected { border-color: var(--bad); opacity: 0.8; }
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
.approved-at { color: var(--ok); font-size: 12px; }
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
.ln-link-card {
  display: block; border-top: 1px solid var(--ln-line); text-decoration: none; color: var(--ln-txt);
  background: var(--ln-hover);
}
.ln-link-placeholder {
  display: flex; align-items: center; gap: 12px; padding: 14px;
}
.ln-link-icon { font-size: 20px; }
.ln-link-title { font-size: 14px; font-weight: 600; }
.ln-link-domain { font-size: 12px; color: var(--ln-muted); padding: 0 14px 14px; }

/* Candidate images */
.candidate-row { margin: 14px 0; }
.candidate-label { font-size: 12px; color: var(--mut); margin-bottom: 8px; text-transform: uppercase; letter-spacing: 0.5px; }
.candidate-thumbs { display: flex; gap: 10px; flex-wrap: wrap; }
.candidate-thumb {
  position: relative; width: 120px; height: 70px; border-radius: 8px; overflow: hidden;
  border: 2px solid transparent; cursor: pointer; background: var(--surface);
}
.candidate-thumb.active { border-color: var(--ok); }
.candidate-thumb img { width: 100%; height: 100%; object-fit: cover; display: block; }
.candidate-thumb input { position: absolute; opacity: 0; }

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
.btn:hover:not(:disabled) { opacity: 0.85; transform: translateY(-1px); }
.btn:disabled { opacity: 0.5; cursor: not-allowed; }
.btn.approve { background: rgba(34,197,94,0.15); color: var(--ok); border-color: rgba(34,197,94,0.35); }
.btn.edit { background: rgba(96,165,250,0.12); color: var(--accent); border-color: rgba(96,165,250,0.3); }
.btn.image { background: rgba(168,85,247,0.12); color: #c084fc; border-color: rgba(168,85,247,0.3); }
.btn.skip { background: rgba(239,68,68,0.1); color: var(--bad); border-color: rgba(239,68,68,0.3); }
.btn.reject { background: rgba(239,68,68,0.15); color: var(--bad); border-color: rgba(239,68,68,0.4); }
.btn.save { background: rgba(34,197,94,0.15); color: var(--ok); border-color: rgba(34,197,94,0.35); }
.btn.cancel { background: transparent; color: var(--mut); }

/* Edit / Agent edit panels */
.edit-panel, .agent-panel, .reject-panel {
  background: var(--surface); border: 1px solid var(--line); border-radius: 12px;
  padding: 14px; margin-bottom: 14px;
}
.edit-label { font-size: 12px; color: var(--mut); margin-bottom: 6px; text-transform: uppercase; letter-spacing: 0.5px; }
.edit-panel textarea, .agent-panel textarea, .reject-panel textarea {
  width: 100%; background: var(--bg); color: var(--txt); border: 1px solid var(--line);
  border-radius: 10px; padding: 12px; font-family: inherit; font-size: 15px;
  line-height: 1.5; resize: vertical;
}
.edit-actions { display: flex; gap: 8px; margin-top: 8px; }

/* Spinner */
.spinner {
  display: inline-block; width: 14px; height: 14px; border: 2px solid rgba(255,255,255,0.3);
  border-top-color: var(--accent); border-radius: 50%; animation: spin 0.8s linear infinite;
  margin-right: 6px; vertical-align: middle;
}
@keyframes spin { to { transform: rotate(360deg); } }

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


_JS = '''(function() {
  "use strict";

  let currentTab = "pending";

  async function getApi(path) {
    const r = await fetch('/api' + path);
    if (!r.ok) throw new Error('HTTP ' + r.status);
    return r.json();
  }

  async function postApi(path, payload) {
    const r = await fetch('/api' + path, {
      method: 'POST',
      headers: {'Content-Type': 'application/json'},
      body: JSON.stringify(payload)
    });
    const data = await r.json().catch(() => ({}));
    if (!r.ok) throw new Error(data.error || 'HTTP ' + r.status);
    return data;
  }

  function scoreColor(score) {
    if (score >= 80) return 'good';
    if (score >= 60) return 'warn';
    return 'bad';
  }

  function scoreBar(score) {
    const filled = Math.round(score / 10);
    return '█'.repeat(filled) + '░'.repeat(10 - filled);
  }

  function activeImageUrl(draft) {
    if (draft.image_url) return draft.image_url.replace(/^\\//, '');
    const m = (draft.image_path || '').match(/(\\.[^.\\/]+)$/);
    const ext = m ? m[1] : '.jpg';
    return 'images/' + draft.item_id + ext;
  }

  function setStatus(html, type) {
    const app = document.getElementById('app');
    let banner = app.querySelector('.status-banner');
    if (!banner) {
      banner = document.createElement('div');
      banner.className = 'status-banner';
      app.insertBefore(banner, app.firstChild);
    }
    banner.className = 'status-banner ' + (type || '');
    banner.innerHTML = html;
  }

  function clearStatus() {
    const app = document.getElementById('app');
    const banner = app.querySelector('.status-banner');
    if (banner) banner.remove();
  }

  function renderCandidates(draft) {
    const candidates = (draft.image_candidates || []).filter(c => c.startsWith('images/'));
    if (!candidates.length) return null;
    const wrap = document.createElement('div');
    wrap.className = 'candidate-row';
    const label = document.createElement('div');
    label.className = 'candidate-label';
    label.textContent = 'Choose image';
    wrap.appendChild(label);
    const thumbs = document.createElement('div');
    thumbs.className = 'candidate-thumbs';
    const active = activeImageUrl(draft);
    candidates.forEach(c => {
      const lbl = document.createElement('label');
      lbl.className = 'candidate-thumb' + (c === active ? ' active' : '');
      lbl.title = c;
      const input = document.createElement('input');
      input.type = 'radio';
      input.name = 'img-' + draft.item_id;
      input.value = c;
      if (c === active) input.checked = true;
      input.onchange = () => selectImage(draft.item_id, c);
      const img = document.createElement('img');
      img.src = c;
      img.alt = '';
      img.loading = 'lazy';
      lbl.appendChild(input);
      lbl.appendChild(img);
      thumbs.appendChild(lbl);
    });
    wrap.appendChild(thumbs);
    return wrap;
  }

  function renderDraft(draft) {
    const a = draft.analysis || {};
    const rel = a.relevance_score || 0;
    const acc = a.accuracy_score || 0;
    const perf = a.perfection_score || 0;

    const article = document.createElement('article');
    article.className = 'draft-card';
    if (draft.status === 'approved') article.classList.add('approved');
    if (draft.status === 'rejected') article.classList.add('rejected');
    article.dataset.itemId = draft.item_id;
    article.dataset.pillar = draft.pillar;

    // meta
    const meta = document.createElement('div');
    meta.className = 'card-meta';
    const left = document.createElement('div');
    left.className = 'left';
    const dayBadge = document.createElement('span');
    dayBadge.className = 'day-badge';
    dayBadge.textContent = draft.day || 'Today';
    const pillar = document.createElement('span');
    pillar.className = 'pillar';
    pillar.textContent = (draft.pillar || '').replace(/_/g, ' ').replace(/\\b\\w/g, m => m.toUpperCase());
    const itemId = document.createElement('span');
    itemId.className = 'item-id';
    itemId.textContent = '#' + draft.item_id.slice(0, 8);
    left.append(dayBadge, pillar, itemId);
    if (draft.approved_at) {
      const approvedAt = document.createElement('span');
      approvedAt.className = 'approved-at';
      approvedAt.textContent = 'Approved ' + formatDate(draft.approved_at);
      left.appendChild(approvedAt);
    }
    const source = document.createElement('a');
    source.className = 'source-link';
    source.href = draft.source_url;
    source.target = '_blank';
    source.rel = 'noopener';
    source.textContent = 'Source →';
    meta.append(left, source);

    // title
    const h2 = document.createElement('h2');
    h2.className = 'draft-title';
    h2.textContent = draft.title || '(untitled)';

    // preview
    const previewShell = document.createElement('div');
    previewShell.className = 'preview-shell';
    const previewLabel = document.createElement('div');
    previewLabel.className = 'preview-label';
    previewLabel.textContent = 'LinkedIn preview';
    const lnPost = document.createElement('div');
    lnPost.className = 'ln-post minimal';
    const body = document.createElement('div');
    body.className = 'ln-body';
    body.id = 'post-' + draft.item_id;
    body.innerHTML = (draft.linkedin_post || '').replace(/\\n/g, '<br>');
    const hashtags = document.createElement('div');
    hashtags.className = 'ln-hashtags';
    hashtags.textContent = (draft.hashtags || []).join(' ');

    lnPost.append(body, hashtags);
    const imgUrl = activeImageUrl(draft);
    if (imgUrl) {
      const imgBox = document.createElement('div');
      imgBox.className = 'ln-image';
      const img = document.createElement('img');
      img.src = imgUrl;
      img.alt = '';
      img.loading = 'lazy';
      imgBox.appendChild(img);
      lnPost.appendChild(imgBox);
    } else {
      let domain = 'Source';
      try { domain = new URL(draft.source_url).hostname.replace(/^www\\./, ''); } catch (e) {}
      const linkCard = document.createElement('a');
      linkCard.className = 'ln-link-card';
      linkCard.href = draft.source_url;
      linkCard.target = '_blank';
      linkCard.rel = 'noopener';
      linkCard.innerHTML = `
        <div class="ln-link-placeholder"><div class="ln-link-icon">🔗</div><div class="ln-link-title">${(draft.title || '').slice(0,90)}</div></div>
        <div class="ln-link-domain">${domain}</div>`;
      lnPost.appendChild(linkCard);
    }
    previewShell.append(previewLabel, lnPost);

    // candidates
    const candidatesEl = renderCandidates(draft);

    // quality card (only for pending)
    let quality = null;
    if (draft.status === 'pending') {
      quality = document.createElement('div');
      quality.className = 'quality-card';
      [
        {label: 'Relevance', score: rel},
        {label: 'Accuracy', score: acc},
        {label: 'Perfection', score: perf}
      ].forEach(({label, score}) => {
        const row = document.createElement('div');
        row.className = 'score-row';
        const lab = document.createElement('span');
        lab.textContent = label;
        const val = document.createElement('span');
        val.className = 'score ' + scoreColor(score);
        val.innerHTML = score + '/100 <span class="bar">' + scoreBar(score) + '</span>';
        row.append(lab, val);
        quality.appendChild(row);
      });
      const actionLine = document.createElement('div');
      actionLine.className = 'action-line';
      actionLine.innerHTML = 'Proposed action: <strong>' + (a.proposed_action || '—') + '</strong>';
      quality.appendChild(actionLine);
      (a.issues || []).forEach(issue => {
        const ul = quality.querySelector('ul.issues') || document.createElement('ul');
        ul.className = 'issues';
        const li = document.createElement('li');
        li.textContent = issue;
        ul.appendChild(li);
        quality.appendChild(ul);
      });
    }

    // actions
    const actions = document.createElement('div');
    actions.className = 'actions';
    const btn = (cls, text, onClick) => {
      const b = document.createElement('button');
      b.className = 'btn ' + cls;
      b.textContent = text;
      b.onclick = onClick;
      return b;
    };

    if (draft.status === 'pending') {
      actions.append(
        btn('approve', '✅ Approve', () => approve(draft.item_id)),
        btn('edit', '✏️ Edit', () => startEdit(draft.item_id)),
        btn('image', '🤖 Agent edit', () => startAgentEdit(draft.item_id)),
        btn('image', '🔄 Regenerate image', () => regenerateImage(draft.item_id)),
        btn('reject', '🗑 Reject', () => startReject(draft.item_id)),
        btn('skip', '⏭ Skip', () => skip(draft.item_id))
      );
    } else if (draft.status === 'approved') {
      actions.append(
        btn('edit', '✏️ Edit', () => startEdit(draft.item_id)),
        btn('image', '🔄 Regenerate image', () => regenerateImage(draft.item_id))
      );
    } else if (draft.status === 'rejected') {
      actions.append(
        btn('approve', '✅ Approve', () => approve(draft.item_id)),
        btn('skip', '🗑 Delete', () => skip(draft.item_id))
      );
    }

    // edit box
    const editBox = document.createElement('div');
    editBox.className = 'edit-panel';
    editBox.id = 'edit-' + draft.item_id;
    editBox.style.display = 'none';
    const editLabel = document.createElement('div');
    editLabel.className = 'edit-label';
    editLabel.textContent = 'Edit LinkedIn post';
    const textarea = document.createElement('textarea');
    textarea.id = 'textarea-' + draft.item_id;
    textarea.rows = 12;
    textarea.value = draft.linkedin_post || '';
    const editActions = document.createElement('div');
    editActions.className = 'edit-actions';
    editActions.append(
      btn('save', '💾 Save', () => saveEdit(draft.item_id)),
      btn('cancel', 'Cancel', () => cancelEdit(draft.item_id))
    );
    editBox.append(editLabel, textarea, editActions);

    // agent edit box
    const agentBox = document.createElement('div');
    agentBox.className = 'agent-panel';
    agentBox.id = 'agent-' + draft.item_id;
    agentBox.style.display = 'none';
    const agentLabel = document.createElement('div');
    agentLabel.className = 'edit-label';
    agentLabel.textContent = 'Tell the AI how to rewrite this';
    const agentInput = document.createElement('textarea');
    agentInput.id = 'agent-input-' + draft.item_id;
    agentInput.rows = 3;
    agentInput.placeholder = 'e.g. Make it shorter, more technical, add a stronger CTA...';
    const agentActions = document.createElement('div');
    agentActions.className = 'edit-actions';
    agentActions.append(
      btn('save', '✨ Rewrite', () => agentEdit(draft.item_id)),
      btn('cancel', 'Cancel', () => cancelAgentEdit(draft.item_id))
    );
    agentBox.append(agentLabel, agentInput, agentActions);

    // reject box
    const rejectBox = document.createElement('div');
    rejectBox.className = 'reject-panel';
    rejectBox.id = 'reject-' + draft.item_id;
    rejectBox.style.display = 'none';
    const rejectLabel = document.createElement('div');
    rejectLabel.className = 'edit-label';
    rejectLabel.textContent = 'Why are you rejecting? (optional)';
    const rejectInput = document.createElement('textarea');
    rejectInput.id = 'reject-input-' + draft.item_id;
    rejectInput.rows = 3;
    rejectInput.placeholder = 'e.g. Too generic, source is weak, duplicate...';
    const rejectActions = document.createElement('div');
    rejectActions.className = 'edit-actions';
    rejectActions.append(
      btn('reject', '🗑 Confirm reject', () => rejectDraft(draft.item_id)),
      btn('cancel', 'Cancel', () => cancelReject(draft.item_id))
    );
    rejectBox.append(rejectLabel, rejectInput, rejectActions);

    article.append(meta, h2, previewShell, candidatesEl, quality, actions, editBox, agentBox, rejectBox);
    return article;
  }

  function renderEmpty(tab) {
    const article = document.createElement('article');
    article.className = 'draft-card empty';
    const messages = {
      pending: '<div class="empty-icon">📭</div><h2>No pending drafts</h2><p>Run <code>python run.py draft-today --with-image</code> to create one for review.</p>',
      approved: '<div class="empty-icon">✅</div><h2>No approved drafts</h2><p>Approve drafts from the Queued tab to see them here.</p>',
      rejected: '<div class="empty-icon">🗑</div><h2>No rejected drafts</h2><p>Rejected drafts older than 7 days are automatically cleared.</p>'
    };
    article.innerHTML = messages[tab] || messages.pending;
    return article;
  }

  function formatDate(iso) {
    if (!iso) return '';
    try {
      const d = new Date(iso);
      return d.toLocaleString();
    } catch (e) { return iso; }
  }

  async function loadDrafts() {
    const app = document.getElementById('app');
    app.innerHTML = '<div class="loading">Loading drafts…</div>';
    try {
      const data = await getApi('/drafts?status=' + currentTab);
      if (!data.ok) throw new Error(data.error || 'Failed to load drafts');
      const drafts = data.drafts || [];
      const counter = document.getElementById('counter');
      if (counter) counter.textContent = drafts.length + ' / ' + data.total;
      app.innerHTML = '';
      if (!drafts.length) {
        app.appendChild(renderEmpty(currentTab));
        return;
      }
      drafts.forEach(d => app.appendChild(renderDraft(d)));
    } catch (err) {
      app.innerHTML = '';
      const article = document.createElement('article');
      article.className = 'draft-card empty';
      article.innerHTML = '<div class="empty-icon">⚠️</div><h2>Could not load drafts</h2><p>' + err.message + '</p>';
      app.appendChild(article);
      console.error(err);
    }
  }

  function switchTab(tab) {
    currentTab = tab;
    document.querySelectorAll('.tab').forEach(t => t.classList.toggle('active', t.dataset.tab === tab));
    loadDrafts();
  }

  async function approve(id) {
    try {
      setStatus('<span class="spinner"></span> Approving…', 'running');
      const data = await postApi('/approve', {item_id: id});
      if (data.ok) {
        if (currentTab === 'pending') {
          document.querySelector(`article[data-item-id="${id}"]`).remove();
        } else {
          await loadDrafts();
        }
      }
      setStatus('Approved — ready to publish', 'success');
      setTimeout(clearStatus, 2000);
    } catch (err) {
      setStatus('Failed: ' + err.message, 'error');
    }
  }

  async function skip(id) {
    if (!confirm('Skip this draft?')) return;
    try {
      setStatus('<span class="spinner"></span> Skipping…', 'running');
      const data = await postApi('/skip', {item_id: id});
      if (data.ok) {
        const card = document.querySelector(`article[data-item-id="${id}"]`);
        if (card) card.remove();
      }
      setStatus('Skipped', 'success');
      setTimeout(clearStatus, 2000);
    } catch (err) {
      setStatus('Failed: ' + err.message, 'error');
    }
  }

  async function rejectDraft(id) {
    const feedback = document.getElementById('reject-input-' + id).value.trim();
    try {
      setStatus('<span class="spinner"></span> Rejecting…', 'running');
      const data = await postApi('/reject', {item_id: id, feedback});
      if (data.ok) {
        const card = document.querySelector(`article[data-item-id="${id}"]`);
        if (card) card.remove();
      }
      setStatus('Rejected', 'success');
      setTimeout(clearStatus, 2000);
    } catch (err) {
      setStatus('Failed: ' + err.message, 'error');
    }
  }

  async function selectImage(id, candidate) {
    try {
      setStatus('<span class="spinner"></span> Selecting image…', 'running');
      await postApi('/select-image', {item_id: id, candidate});
      await loadDrafts();
      setStatus('Image selected', 'success');
      setTimeout(clearStatus, 2000);
    } catch (err) {
      setStatus('Failed: ' + err.message, 'error');
    }
  }

  function startEdit(id) {
    document.getElementById('edit-' + id).style.display = 'block';
    document.getElementById('agent-' + id).style.display = 'none';
    document.getElementById('reject-' + id).style.display = 'none';
  }

  function cancelEdit(id) {
    document.getElementById('edit-' + id).style.display = 'none';
  }

  async function saveEdit(id) {
    const text = document.getElementById('textarea-' + id).value;
    try {
      setStatus('<span class="spinner"></span> Saving edit…', 'running');
      await postApi('/edit', {item_id: id, linkedin_post: text});
      document.getElementById('post-' + id).innerHTML = (text || '').replace(/\\n/g, '<br>');
      cancelEdit(id);
      setStatus('Edit saved', 'success');
      setTimeout(clearStatus, 2000);
    } catch (err) {
      setStatus('Failed: ' + err.message, 'error');
    }
  }

  function startAgentEdit(id) {
    document.getElementById('agent-' + id).style.display = 'block';
    document.getElementById('edit-' + id).style.display = 'none';
    document.getElementById('reject-' + id).style.display = 'none';
  }

  function cancelAgentEdit(id) {
    document.getElementById('agent-' + id).style.display = 'none';
  }

  async function agentEdit(id) {
    const instruction = document.getElementById('agent-input-' + id).value.trim();
    if (!instruction) return alert('Enter an instruction first');
    const btn = document.querySelector(`#agent-${id} .btn.save`);
    if (btn) { btn.disabled = true; btn.innerHTML = '<span class="spinner"></span> Rewriting…'; }
    try {
      const data = await postApi('/agent-edit', {item_id: id, instruction});
      document.getElementById('post-' + id).innerHTML = (data.linkedin_post || '').replace(/\\n/g, '<br>');
      cancelAgentEdit(id);
      setStatus('AI rewrite complete', 'success');
      setTimeout(clearStatus, 2000);
    } catch (err) {
      setStatus('Failed: ' + err.message, 'error');
    } finally {
      if (btn) { btn.disabled = false; btn.textContent = '✨ Rewrite'; }
    }
  }

  function startReject(id) {
    document.getElementById('reject-' + id).style.display = 'block';
    document.getElementById('edit-' + id).style.display = 'none';
    document.getElementById('agent-' + id).style.display = 'none';
  }

  function cancelReject(id) {
    document.getElementById('reject-' + id).style.display = 'none';
  }

  async function regenerateImage(id) {
    if (!confirm('This may wake and run your RunPod ComfyUI pod. Continue?')) return;
    const card = document.querySelector(`article[data-item-id="${id}"]`);
    const btn = card.querySelector('.btn.image');
    const originalText = btn.textContent;
    btn.disabled = true;
    btn.innerHTML = '<span class="spinner"></span> Running on RunPod…';
    try {
      const data = await postApi('/regenerate-image', {item_id: id});
      if (data.ok) {
        const imgBox = card.querySelector('.ln-image img');
        if (imgBox) {
          imgBox.src = data.image_url + '?t=' + Date.now();
        } else {
          await loadDrafts();
        }
      }
      setStatus('Image regenerated', 'success');
      setTimeout(clearStatus, 2000);
    } catch (err) {
      setStatus('Failed: ' + err.message, 'error');
    } finally {
      btn.disabled = false;
      btn.textContent = originalText;
    }
  }

  window.switchTab = switchTab;
  window.approve = approve;
  window.skip = skip;
  window.rejectDraft = rejectDraft;
  window.selectImage = selectImage;
  window.startEdit = startEdit;
  window.cancelEdit = cancelEdit;
  window.saveEdit = saveEdit;
  window.startAgentEdit = startAgentEdit;
  window.cancelAgentEdit = cancelAgentEdit;
  window.agentEdit = agentEdit;
  window.startReject = startReject;
  window.cancelReject = cancelReject;
  window.regenerateImage = regenerateImage;

  document.addEventListener('DOMContentLoaded', loadDrafts);
})();
'''


if __name__ == "__main__":
    path = generate_dashboard()
    print(path)
