"""Generate a polished review dashboard for LinkedIn drafts.

The dashboard renders each draft inside a LinkedIn-style post preview so the
operator sees exactly how the post will look in the feed before approving.
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




def _progress_bar(score: int) -> str:
    pct = max(0, min(100, score))
    return f'<span class="progress"><div style="width:{pct}%"></div></span>'


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
        issues_html = f"      <ul class=\"issues\">\n{issues_html}\n      </ul>"

    initials = "".join(w[0] for w in (draft.pillar or "draft").replace("_", " ").split()[:2]).upper()[:2]
    now = datetime.now(timezone.utc).strftime("%b %d • Just now")

    linkedin_preview = f'''
    <div class="ln-post">
      <div class="ln-author">
        <div class="ln-avatar">{initials}</div>
        <div class="ln-author-info">
          <div class="ln-name">You</div>
          <div class="ln-headline">Creator • {html.escape(draft.pillar.replace("_", " ").title())}</div>
          <div class="ln-time">{now}</div>
        </div>
        <div class="ln-more">⋯</div>
      </div>
      <div class="ln-body" id="post-{html.escape(draft.item_id)}">{body_html}</div>
      <div class="ln-hashtags">{hashtags}</div>
{_link_preview(draft, image_rel)}
      <div class="ln-reactions">
        <div class="ln-reaction-btn"><span>👍</span> Like</div>
        <div class="ln-reaction-btn"><span>💬</span> Comment</div>
        <div class="ln-reaction-btn"><span>🔄</span> Repost</div>
        <div class="ln-reaction-btn"><span>✉️</span> Send</div>
      </div>
    </div>'''

    return f'''
    <article class="draft-card" data-item-id="{html.escape(draft.item_id)}" data-pillar="{html.escape(draft.pillar)}">
      <div class="card-meta">
        <div class="left">
          <span class="day-badge">{html.escape(plan.day_name)}</span>
          <span class="pillar">{html.escape(draft.pillar.replace("_", " ").title())}</span>
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
          <span class="score {_score_color(rel_score)}">{rel_score}/100 {_progress_bar(rel_score)}</span>
        </div>
        <div class="score-row">
          <span>Accuracy</span>
          <span class="score {_score_color(acc_score)}">{acc_score}/100 {_progress_bar(acc_score)}</span>
        </div>
        <div class="score-row">
          <span>Perfection</span>
          <span class="score {_score_color(perf_score)}">{perf_score}/100 {_progress_bar(perf_score)}</span>
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
def _render_media(draft: Draft, image_rel: str | None) -> str:
    if image_rel:
        return f"""      <div class=\"ln-image\">
        <img src=\"images/{html.escape(Path(image_rel).name)}\" alt=\"\" loading=\"lazy\" />
      </div>"""
    from urllib.parse import urlparse
    try:
        domain = urlparse(draft.source_url).netloc.replace("www.", "")
    except ValueError as exc:
        logger.warning("Could not parse source URL for link preview: %s", exc)
        domain = "Source"
    if not domain:
        domain = "Source"
    return f"""      <a class=\"ln-link-card\" href=\"{html.escape(draft.source_url)}\" target=\"_blank\" rel=\"noopener\">
        <div class=\"ln-link-preview\">
          <div class=\"ln-link-thumb\">🔗</div>
          <div class=\"ln-link-info\">
            <div class=\"ln-link-title\">{html.escape(draft.title[:90])}</div>
            <div class=\"ln-link-domain\">{html.escape(domain)}</div>
          </div>
        </div>
      </a>"""


def _bar(score: int) -> str:
    """Kept for backward compatibility; progress bars now use CSS."""
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
    plan = day_plan()

    index_path = REVIEW_DIR / "index.html"
    index_path.write_text(_HTML_TEMPLATE.format(
        generated_at=datetime.now(timezone.utc).isoformat(),
        count=len(cards),
        day=html.escape(plan.day_name),
        pillar=html.escape(plan.post_type.replace('_', ' ').title()),
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
      </div>
    </div>
  </header>

  <nav class="site-nav">
    <div class="wrap">
      <div class="tabs">
        <button class="tab active" disabled>LinkedIn</button>
      </div>
      <div class="stats">
        <span class="count">{count} pending</span>
        <span class="generated">Generated {generated_at}</span>
      </div>
    </div>
  </nav>

  <main class="wrap">
{body}
  </main>

  <footer class="wrap">
    <p class="note">No post is published from this screen. Approve here, then run <code>python run.py publish --dry-run</code>.</p>
  </footer>

  <script src="assets/app.js"></script>
</body>
</html>'''


_CSS = '''
:root {{
  --bg: #f3f2ef;
  --surface: #ffffff;
  --card: #ffffff;
  --line: #e0e0e0;
  --txt: #1f1f1f;
  --mut: #666666;
  --ok: #057a55;
  --warn: #b45309;
  --bad: #b42318;
  --accent: #0a66c2;
  --accent-soft: #e2f0fe;
  --ln-bg: #ffffff;
  --ln-txt: #1f1f1f;
  --ln-muted: #666666;
  --ln-link: #0a66c2;
  --ln-line: #e0e0e0;
  --ln-hover: #f3f2ef;
  --ln-name: #1f1f1f;
  --ln-headline: #666666;
  --ln-time: #666666;
  --reaction: #666666;
  --shadow: 0 1px 2px rgba(0,0,0,0.08), 0 4px 12px rgba(0,0,0,0.05);
}}
* {{ box-sizing: border-box; }}
html {{ scroll-behavior: smooth; }}
body {{
  margin: 0;
  font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, Helvetica, Arial, sans-serif;
  background: var(--bg);
  color: var(--txt);
  line-height: 1.5;
}}
.wrap {{
  max-width: 720px;
  margin: 0 auto;
  padding: 0 18px;
}}
.site-header {{
  border-bottom: 1px solid var(--ln-line);
  background: var(--surface);
  box-shadow: 0 1px 2px rgba(0,0,0,0.04);
}}
.site-header .wrap {{
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 16px;
  padding-top: 18px;
  padding-bottom: 18px;
}}
.brand {{
  display: flex;
  align-items: center;
  gap: 12px;
}}
.logo {{
  width: 42px;
  height: 42px;
  border-radius: 10px;
  background: var(--accent);
  color: #fff;
  display: flex;
  align-items: center;
  justify-content: center;
  font-size: 20px;
}}
h1 {{
  margin: 0;
  font-size: 18px;
  font-weight: 700;
  letter-spacing: -0.2px;
}}
.sub {{
  color: var(--mut);
  font-size: 13px;
  margin-top: 2px;
}}
.today {{
  text-align: right;
}}
.today .day {{
  font-size: 14px;
  font-weight: 600;
  color: var(--accent);
}}
.today .pillar {{
  font-size: 13px;
  color: var(--mut);
  text-transform: capitalize;
}}
.site-nav {{
  background: var(--surface);
  border-bottom: 1px solid var(--ln-line);
  position: sticky;
  top: 0;
  z-index: 20;
  box-shadow: 0 1px 2px rgba(0,0,0,0.04);
}}
.site-nav .wrap {{
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 16px;
  padding-top: 10px;
  padding-bottom: 10px;
}}
.tabs {{
  display: flex;
  gap: 8px;
}}
.tab {{
  background: transparent;
  border: 1px solid var(--ln-line);
  color: var(--mut);
  padding: 7px 14px;
  border-radius: 999px;
  font-size: 13px;
  font-weight: 500;
}}
.tab.active {{
  background: var(--accent-soft);
  color: var(--accent);
  border-color: var(--accent);
}}
.stats {{
  display: flex;
  align-items: center;
  gap: 16px;
  color: var(--mut);
  font-size: 13px;
}}
.stats .count {{
  background: var(--accent-soft);
  color: var(--accent);
  padding: 4px 10px;
  border-radius: 999px;
  font-weight: 600;
}}
.generated {{
  font-family: ui-monospace, SFMono-Regular, Menlo, Consolas, monospace;
  font-size: 12px;
}}
.draft-card {{
  background: var(--card);
  border: 1px solid var(--ln-line);
  border-radius: 12px;
  box-shadow: var(--shadow);
  padding: 20px;
  margin: 18px 0;
  transition: opacity 0.2s ease;
}}
.draft-card.approved {{
  border-color: var(--ok);
  opacity: 0.72;
}}
.card-meta {{
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
  margin-bottom: 14px;
  flex-wrap: wrap;
}}
.card-meta .left {{
  display: flex;
  align-items: center;
  gap: 8px;
  flex-wrap: wrap;
}}
.day-badge {{
  background: var(--accent-soft);
  color: var(--accent);
  padding: 3px 10px;
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
.source-link {{
  color: var(--accent);
  font-size: 13px;
  text-decoration: none;
  font-weight: 600;
}}
.draft-title {{
  font-size: 16px;
  font-weight: 700;
  margin: 0 0 14px;
  color: var(--txt);
}}
.preview-shell {{
  background: var(--bg);
  border: 1px solid var(--ln-line);
  border-radius: 12px;
  padding: 14px;
  margin-bottom: 16px;
}}
.preview-label {{
  font-size: 11px;
  text-transform: uppercase;
  letter-spacing: 0.6px;
  color: var(--mut);
  margin-bottom: 10px;
  font-weight: 600;
}}
.ln-post {{
  background: var(--ln-bg);
  color: var(--ln-txt);
  border: 1px solid var(--ln-line);
  border-radius: 10px;
  max-width: 680px;
  margin: 0 auto;
  overflow: hidden;
  box-shadow: 0 1px 1px rgba(0,0,0,0.04);
}}
.ln-author {{
  display: flex;
  align-items: center;
  gap: 10px;
  padding: 14px 16px 10px;
}}
.ln-avatar {{
  width: 48px;
  height: 48px;
  border-radius: 50%;
  background: linear-gradient(135deg, #0a66c2, #378fe9);
  color: #fff;
  display: flex;
  align-items: center;
  justify-content: center;
  font-size: 18px;
  font-weight: 700;
  flex-shrink: 0;
}}
.ln-author-info {{
  flex: 1;
  min-width: 0;
}}
.ln-name {{
  font-size: 15px;
  font-weight: 600;
  color: var(--ln-name);
  line-height: 1.3;
}}
.ln-headline {{
  font-size: 13px;
  color: var(--ln-headline);
  line-height: 1.35;
}}
.ln-time {{
  font-size: 12px;
  color: var(--ln-time);
}}
.ln-more {{
  margin-left: auto;
  color: var(--ln-muted);
  font-size: 18px;
  line-height: 1;
}}
.ln-body {{
  font-size: 15px;
  line-height: 1.55;
  color: var(--ln-txt);
  white-space: pre-wrap;
  padding: 0 16px 12px;
}}
.ln-hashtags {{
  color: var(--ln-link);
  font-size: 14px;
  font-weight: 600;
  padding: 0 16px 12px;
}}
.ln-hashtags span {{
  margin-right: 6px;
}}
.ln-image {{
  border-top: 1px solid var(--ln-line);
  width: 100%;
  aspect-ratio: 1.91 / 1;
  background: #f3f2ef;
  overflow: hidden;
}}
.ln-image img {{
  width: 100%;
  height: 100%;
  object-fit: cover;
  display: block;
}}
.ln-link-card {{
  display: block;
  border-top: 1px solid var(--ln-line);
  text-decoration: none;
  color: inherit;
}}
.ln-link-card:hover {{
  background: var(--ln-hover);
}}
.ln-link-placeholder {{
  min-height: 140px;
  background: #f3f2ef;
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  gap: 8px;
  text-align: center;
  padding: 20px;
}}
.ln-link-icon {{
  font-size: 28px;
}}
.ln-link-title {{
  font-size: 15px;
  font-weight: 600;
  color: var(--ln-txt);
  max-width: 90%;
}}
.ln-link-domain {{
  border-top: 1px solid var(--ln-line);
  padding: 10px 16px;
  font-size: 12px;
  color: var(--ln-muted);
}}
.ln-reactions {{
  display: flex;
  align-items: center;
  justify-content: space-between;
  border-top: 1px solid var(--ln-line);
  padding: 8px 16px;
  color: var(--reaction);
  font-size: 14px;
  font-weight: 600;
}}
.ln-reaction-btn {{
  display: flex;
  align-items: center;
  gap: 6px;
  flex: 1;
  justify-content: center;
  padding: 8px 0;
  cursor: default;
}}
.ln-reaction-btn span {{
  font-size: 18px;
}}
.quality-card {{
  background: #f9fafb;
  border: 1px solid var(--ln-line);
  border-radius: 10px;
  padding: 14px;
  margin-bottom: 14px;
}}
.score-row {{
  display: flex;
  justify-content: space-between;
  align-items: center;
  padding: 6px 0;
  font-size: 14px;
}}
.score {{
  font-family: ui-monospace, SFMono-Regular, Menlo, Consolas, monospace;
  font-size: 13px;
  display: flex;
  align-items: center;
  gap: 8px;
}}
.progress {{
  width: 96px;
  height: 7px;
  background: #e5e7eb;
  border-radius: 999px;
  overflow: hidden;
}}
.progress > div {{
  height: 100%;
  border-radius: 999px;
  transition: width 0.3s ease;
}}
.good .progress > div {{ background: var(--ok); }}
.warn .progress > div {{ background: var(--warn); }}
.bad .progress > div {{ background: var(--bad); }}
.good {{ color: var(--ok); }}
.warn {{ color: var(--warn); }}
.bad {{ color: var(--bad); }}
.action-line {{
  margin-top: 10px;
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
}}
.btn {{
  background: var(--surface);
  color: var(--txt);
  border: 1px solid var(--ln-line);
  padding: 9px 16px;
  border-radius: 8px;
  cursor: pointer;
  font-size: 14px;
  font-weight: 600;
  transition: transform 0.05s ease, opacity 0.15s ease, background 0.15s ease;
}}
.btn:hover {{ opacity: 0.9; transform: translateY(-1px); }}
.btn.approve {{ background: #dcfce7; color: var(--ok); border-color: #86efac; }}
.btn.edit {{ background: var(--accent-soft); color: var(--accent); border-color: #bfdbfe; }}
.btn.image {{ background: #f3e8ff; color: #7e22ce; border-color: #d8b4fe; }}
.btn.skip {{ background: #fee2e2; color: var(--bad); border-color: #fecaca; }}
.btn.save {{ background: #dcfce7; color: var(--ok); border-color: #86efac; }}
.btn.cancel {{ background: transparent; color: var(--mut); }}
.edit-box {{
  margin-top: 14px;
}}
.edit-box textarea {{
  width: 100%;
  background: var(--surface);
  color: var(--txt);
  border: 1px solid var(--ln-line);
  border-radius: 10px;
  padding: 12px;
  font-family: inherit;
  font-size: 15px;
  line-height: 1.5;
  resize: vertical;
}}
.edit-actions {{
  display: flex;
  gap: 8px;
  margin-top: 8px;
}}
.empty {{
  text-align: center;
  padding: 60px 20px;
  color: var(--mut);
}}
.empty-icon {{
  font-size: 48px;
  margin-bottom: 12px;
}}
footer {{
  border-top: 1px solid var(--ln-line);
  margin-top: 32px;
  padding: 20px 0 48px;
}}
.note {{
  color: var(--mut);
  font-size: 13px;
}}
code {{
  font-family: ui-monospace, SFMono-Regular, Menlo, Consolas, monospace;
  background: #f3f2ef;
  padding: 2px 6px;
  border-radius: 5px;
}}
.toast-container {{
  position: fixed;
  top: 18px;
  right: 18px;
  z-index: 50;
  display: flex;
  flex-direction: column;
  gap: 10px;
}}
.toast {{
  background: var(--surface);
  border: 1px solid var(--ln-line);
  border-left: 4px solid var(--accent);
  border-radius: 8px;
  padding: 12px 16px;
  box-shadow: var(--shadow);
  font-size: 14px;
  font-weight: 500;
  max-width: 320px;
  animation: toastIn 0.2s ease;
}}
.toast.ok {{ border-left-color: var(--ok); color: var(--ok); }}
.toast.err {{ border-left-color: var(--bad); color: var(--bad); }}
@keyframes toastIn {{
  from {{ opacity: 0; transform: translateX(12px); }}
  to {{ opacity: 1; transform: translateX(0); }}
}}
@media (max-width: 560px) {{
  .site-header .wrap {{ flex-direction: column; align-items: flex-start; }}
  .today {{ text-align: left; }}
  .site-nav .wrap {{ flex-direction: column; align-items: flex-start; gap: 10px; }}
  .ln-body {{ font-size: 14px; }}
  .draft-card {{ padding: 16px; }}
  .ln-reactions {{ font-size: 13px; }}
}}
'''


_JS = '''
const toastContainer = document.createElement('div');
toastContainer.className = 'toast-container';
document.body.appendChild(toastContainer);

function showToast(message, ok=true) {{
  const t = document.createElement('div');
  t.className = `toast ${{ok ? 'ok' : 'err'}}`;
  t.textContent = message;
  toastContainer.appendChild(t);
  setTimeout(() => t.remove(), 3000);
}}

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
  if (data.ok) {{
    const card = document.querySelector(`article[data-item-id="${{id}}"]`);
    card.classList.add('approved');
    const btn = card.querySelector('.btn.approve');
    btn.textContent = '✅ Approved';
    btn.disabled = true;
  }}
  showToast(data.ok ? 'Approved — ready to publish' : 'Failed: ' + (data.error || 'unknown'), data.ok);
}}

async function skip(id) {{
  if (!confirm('Skip this draft? It will be moved to the skipped folder.')) return;
  const data = await api('/skip', {{item_id: id}});
  if (data.ok) document.querySelector(`article[data-item-id="${{id}}"]`).remove();
  showToast(data.ok ? 'Skipped' : 'Failed: ' + (data.error || 'unknown'), data.ok);
}}

function startEdit(id) {{
  document.getElementById('edit-' + id).style.display = 'block';
  const preview = document.querySelector(`article[data-item-id="${{id}}"] .preview-shell`);
  if (preview) preview.style.display = 'none';
}}

function cancelEdit(id) {{
  document.getElementById('edit-' + id).style.display = 'none';
  const preview = document.querySelector(`article[data-item-id="${{id}}"] .preview-shell`);
  if (preview) preview.style.display = 'block';
}}

async function saveEdit(id) {{
  const text = document.getElementById('textarea-' + id).value;
  const data = await api('/edit', {{item_id: id, linkedin_post: text}});
  if (data.ok) {{
    const postEl = document.getElementById('post-' + id);
    postEl.innerHTML = text.replace(/
/g, '<br>');
    cancelEdit(id);
  }}
  showToast(data.ok ? 'Saved' : 'Failed: ' + (data.error || 'unknown'), data.ok);
}}

async function regenerateImage(id) {{
  if (!confirm('This may wake and run your RunPod ComfyUI pod. Continue?')) return;
  const btn = event.target;
  btn.disabled = true;
  const originalText = btn.textContent;
  btn.textContent = '🔄 Running…';
  const data = await api('/regenerate-image', {{item_id: id}});
  btn.disabled = false;
  btn.textContent = originalText;
  if (data.ok && data.image_url) {{
    const card = document.querySelector(`article[data-item-id="${{id}}"]`);
    let box = card.querySelector('.ln-image');
    const imgHtml = `<div class="ln-image"><img src="${{data.image_url}}" alt="" /></div>`;
    if (box) box.outerHTML = imgHtml;
    else {{
      const hashtags = card.querySelector('.ln-hashtags');
      if (hashtags) hashtags.insertAdjacentHTML('afterend', imgHtml);
      else card.querySelector('.ln-post').insertAdjacentHTML('beforeend', imgHtml);
    }}
  }}
  showToast(data.ok ? 'Image regenerated' : 'Failed: ' + (data.error || 'unknown'), data.ok);
}}
'''


if __name__ == "__main__":
    path = generate_dashboard()
    print(path)
