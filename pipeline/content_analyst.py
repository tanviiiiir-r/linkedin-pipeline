"""Daily content relevance + perfection analysis for queued drafts.

This module scores planned/queued content every day before publish. It never
rewrites or publishes automatically — it only produces a report with proposed
actions for operator approval.
"""
from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from datetime import date, datetime, timezone
from pathlib import Path

import requests

from config.calendar import DayPlan, day_plan
from config.settings import ANALYSIS_DIR, QUEUE_DIR, ensure_dirs
from pipeline.drafting import Draft, _parse_draft_markdown
from pipeline.llm_client import complete, is_available
from pipeline.storage import Item, load_item

logger = logging.getLogger(__name__)
ensure_dirs()


@dataclass
class AnalysisResult:
    item_id: str
    title: str
    source_url: str
    draft_path: Path | None
    relevance_score: int
    accuracy_score: int
    perfection_score: int
    issues: list[str]
    proposed_action: str  # keep, update_source, rewrite_draft, skip, replace_image
    notes: str


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _days_old(published_at: str | None) -> float:
    """Return days since published_at, or a large number if unknown."""
    if not published_at:
        return 999.0
    try:
        # Try ISO format first
        dt = datetime.fromisoformat(published_at.replace("Z", "+00:00"))
    except ValueError:
        # Fallback common formats
        dt = None
        for fmt in ("%Y-%m-%d", "%Y-%m-%dT%H:%M:%S", "%a, %d %b %Y %H:%M:%S %z"):
            try:
                dt = datetime.strptime(published_at, fmt)  # noqa: DTZ007
                if dt.tzinfo is None:
                    dt = dt.replace(tzinfo=timezone.utc)
                break
            except ValueError:
                dt = None
        if dt is None:
            return 999.0
    return (_now() - dt).total_seconds() / 86400.0


def link_health_check(url: str, timeout: int = 10) -> tuple[bool, str]:
    """Return (ok, note). HEAD first, then GET on 405/403."""
    if not url or not url.startswith("http"):
        return False, "No valid URL"
    try:
        resp = requests.head(url, timeout=timeout, allow_redirects=True)
        if resp.status_code in (405, 403, 501):
            resp = requests.get(url, timeout=timeout, stream=True)
        if resp.status_code >= 400:
            return False, f"HTTP {resp.status_code}"
        return True, f"HTTP {resp.status_code}"
    except requests.exceptions.Timeout:
        return False, "Timeout"
    except requests.RequestException as exc:
        return False, f"Error: {exc.__class__.__name__}"


def relevance_score(item: Item | None, day_plan: DayPlan, item_age_days: float) -> int:
    """Score 0-100 based on pillar fit, recency, and source bias."""
    score = 70
    if item is None:
        return 50
    # Pillar fit
    lens_terms = [t.strip().lower() for t in day_plan.lens.split(",")]
    text = f"{item.item_title} {item.summary}".lower()
    matches = sum(1 for term in lens_terms if term and term in text)
    score += min(20, matches * 4)
    # Source bias
    if any(sb.lower() in item.source_name.lower() for sb in day_plan.source_bias):
        score += 5
    # Recency penalty
    if item_age_days <= 1:
        score += 5
    elif item_age_days <= 2:
        pass
    elif item_age_days <= 7:
        score -= 10
    else:
        score -= 25
    return max(0, min(100, score))


def accuracy_score(item: Item | None) -> int:
    """Score 0-100 based on source link health."""
    if item is None:
        return 0
    ok, _ = link_health_check(item.item_url)
    return 95 if ok else 40


def _heuristic_perfection(draft: Draft, day_plan: DayPlan) -> tuple[int, list[str], str]:
    """Rule-based perfection score and notes."""
    issues: list[str] = []
    post = draft.linkedin_post or ""
    words = len(post.split())
    max_words = 260 if day_plan.post_type == "founder_signal" else 240
    if words > max_words:
        issues.append(f"LinkedIn post is {words} words (max {max_words})")
    elif words < 80:
        issues.append(f"LinkedIn post is only {words} words; may be too thin")
    # Hook check
    first_line = post.splitlines()[0].strip() if post else ""
    weak_hook_words = ["here is", "this is a", "today i", "just wanted"]
    if any(first_line.lower().startswith(w) for w in weak_hook_words):
        issues.append("Weak hook: starts with filler phrase")
    # Hashtag check
    if not draft.hashtags:
        issues.append("No hashtags")
    # CTA / question check
    has_question = "?" in post
    has_cta = any(w in post.lower() for w in ["what do you think", "share your", "drop a", "agree?", "would you"])
    if not has_question and not has_cta:
        issues.append("No question or discussion prompt")
    # Voice no-go words (example subset; expand via voice config)
    buzzwords = ["leverage", "synergy", "paradigm", "disrupt", "unlock"]
    found_buzz = [w for w in buzzwords if w in post.lower()]
    if found_buzz:
        issues.append(f"Buzzwords found: {', '.join(found_buzz)}")
    # Image fit
    if draft.image_path:
        issues.append("Image present; verify aspect ratio and no text")
    else:
        issues.append("No image; consider adding one for feed reach")

    score = max(0, 100 - len(issues) * 8)
    notes = "Rule-based check."
    return score, issues, notes


def _llm_perfection(draft: Draft, day_plan: DayPlan) -> tuple[int, list[str], str]:
    """Use LLM to score perfection; fall back to heuristic on failure."""
    if not is_available():
        return _heuristic_perfection(draft, day_plan)
    system = (
        "You are a LinkedIn content editor. Score the draft below on: hook, voice, "
        "length, CTA/discussion prompt, pillar fit, and hashtag use. "
        "Return ONLY valid JSON with keys: score (0-100), issues (list of short strings), notes (string)."
    )
    user = (
        f"Day plan: {day_plan.day_name} — {day_plan.post_type}: {day_plan.job}\n"
        f"Post ({len(draft.linkedin_post.split())} words):\n{draft.linkedin_post}\n\n"
        f"Hashtags: {' '.join(draft.hashtags)}\n"
        f"Image path: {draft.image_path or 'none'}"
    )
    try:
        resp = complete(user, system=system, temperature=0.2)
        # Some models wrap JSON in markdown code fences; strip them before parsing.
        raw = (resp.text or "").strip()
        if raw.startswith("```"):
            lines = raw.splitlines()
            lines = lines[1:]
            if lines and lines[-1].strip() == "```":
                lines = lines[:-1]
            raw = "\n".join(lines).strip()
        data = json.loads(raw or "{}")
        score = int(data.get("score", 70))
        issues = [str(i) for i in data.get("issues", [])]
        notes = data.get("notes", "")
        return max(0, min(100, score)), issues, notes
    except (json.JSONDecodeError, ValueError, TypeError, requests.exceptions.RequestException) as exc:
        logger.warning("LLM perfection analysis failed: %s", exc)
        return _heuristic_perfection(draft, day_plan)


def perfection_score(draft: Draft, day_plan: DayPlan, use_llm: bool = True) -> tuple[int, list[str], str]:
    if use_llm:
        return _llm_perfection(draft, day_plan)
    return _heuristic_perfection(draft, day_plan)


def load_drafts_from_queue(status: str | None = None) -> list[tuple[Draft, Path]]:
    """Load Draft objects saved as markdown in the queue directory."""
    drafts: list[tuple[Draft, Path]] = []
    if not QUEUE_DIR.exists():
        return drafts
    for path in sorted(QUEUE_DIR.glob("*.md"), reverse=True):
        try:
            draft = _parse_draft_markdown(path.read_text())
            if draft:
                drafts.append((draft, path))
        except OSError:
            logger.warning("Skipping unreadable draft %s", path)
    return drafts


def analyze_queued_items(for_date: date | None = None, use_llm: bool = True, limit: int = 10) -> list[AnalysisResult]:
    """Analyze queued drafts for a target date (default today)."""
    plan = day_plan(for_date)
    results: list[AnalysisResult] = []
    drafts = load_drafts_from_queue()[:limit]
    if not drafts:
        logger.info("No queued drafts to analyze")
        return results

    for draft, path in drafts:
        item = load_item(draft.source_url)
        item_age = _days_old(item.published_at if item else None)
        rel = relevance_score(item, plan, item_age)
        acc = accuracy_score(item)
        perf, issues, notes = perfection_score(draft, plan, use_llm=use_llm)

        # Proposed action
        if acc < 60:
            action = "update_source"
        elif rel < 60:
            action = "skip"
        elif perf < 60:
            action = "rewrite_draft"
        elif not draft.image_path:
            action = "replace_image"
        else:
            action = "keep"

        results.append(
            AnalysisResult(
                item_id=draft.item_id,
                title=draft.title,
                source_url=draft.source_url,
                draft_path=path,
                relevance_score=rel,
                accuracy_score=acc,
                perfection_score=perf,
                issues=issues,
                proposed_action=action,
                notes=notes,
            )
        )
    return results


def format_report(results: list[AnalysisResult], plan: DayPlan) -> str:
    lines = [
        f"# Content Analysis — {plan.day_name} ({plan.post_type}) — {_now().isoformat()}",
        "",
        f"**Day job:** {plan.job}",
        f"**Items analyzed:** {len(results)}",
        "",
        "| Title | Rel | Acc | Perf | Action | Issues |",
        "|---|---|---|---|---|---|",
    ]
    for r in results:
        issues = "; ".join(r.issues) or "—"
        title = r.title[:45]
        lines.append(f"| {title} | {r.relevance_score} | {r.accuracy_score} | {r.perfection_score} | {r.proposed_action} | {issues} |")
    lines.append("")
    lines.append("## Detailed findings")
    for r in results:
        lines.append(f"\n### {r.title}")
        lines.append(f"- Source: {r.source_url}")
        lines.append(f"- Scores: relevance={r.relevance_score}, accuracy={r.accuracy_score}, perfection={r.perfection_score}")
        lines.append(f"- Proposed action: **{r.proposed_action}**")
        lines.append(f"- Notes: {r.notes}")
        for issue in r.issues:
            lines.append(f"  - ⚠️ {issue}")
    lines.append("")
    lines.append("## Next step")
    lines.append("Operator review required. No automatic rewrites or publishes are performed.")
    return "\n".join(lines)


def save_report(report: str, for_date: date | None = None) -> Path:
    d = for_date or _now().date()
    ANALYSIS_DIR.mkdir(parents=True, exist_ok=True)
    path = ANALYSIS_DIR / f"{d.isoformat()}--analysis.md"
    path.write_text(report)
    logger.info("Saved analysis report: %s", path)
    return path


def run_analysis(for_date: date | None = None, use_llm: bool = True, limit: int = 10) -> Path:
    results = analyze_queued_items(for_date=for_date, use_llm=use_llm, limit=limit)
    plan = day_plan(for_date)
    report = format_report(results, plan)
    return save_report(report, for_date=for_date)


if __name__ == "__main__":
    p = run_analysis()
    print(p)
