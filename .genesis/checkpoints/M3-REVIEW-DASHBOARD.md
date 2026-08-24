# Review — Review Dashboard V2 (codex/review-dashboard-v2)

**Scope:** Polished LinkedIn draft review dashboard (`pipeline/review_dashboard.py`).
**Reviewer:** L1 review agent
**Date:** 2026-08-24

## Findings

### [P1] XSS risk in inline HTML via unescaped post body formatting helper
- **File:** `pipeline/review_dashboard.py:103`
- **Line:** `re_sub_bullets` inserts literal `\1\2 ` back-references into already-escaped HTML and uses a regex on raw HTML text.
- **Risk:** Although `html.escape()` is applied before the regex, the regex then re-rewrites text containing `&lt;br /&gt;`. If a post contains a bullet marker after an escaped `&lt;br /&gt;`, the substitution pattern uses back-references that could produce malformed HTML. More importantly, the helper is placed *after* escaping, so any HTML tags intentionally in the post are escaped — safe. However, the regex operates on escaped text and the replacement string is static, so no injection. Downgrade to P2.
- **Action:** Move `re_sub_bullets` before `html.escape`, or remove it entirely and style bullets with CSS. Keep escaping as the single source of truth.

### [P2] No rate limiting on image regeneration endpoint
- **File:** `pipeline/review_server.py:240-270`
- **Risk:** An accidental double-click or refresh can wake/keep the RunPod pod running and consume credits.
- **Action:** Add a client-side debounce on the regenerate button and/or server-side cooldown per `item_id`.

### [P2] Static file serving lacks additional hardening
- **File:** `pipeline/review_server.py:60-85`
- **Risk:** Path traversal check exists (`safe_root`), but `do_GET` does not reject requests with `..` early, and `Path.resolve()` can be bypassed on some filesystems with symlinks.
- **Action:** Add explicit `..` rejection and require files to be regular files (`is_file()`).

### [P2] Dashboard does not refresh automatically after action
- **File:** `pipeline/review_dashboard.py` / `assets/app.js`
- **Risk:** After approve/skip/edit, the card state changes but the quality panel and proposed action are stale. Operator may act on stale scores.
- **Action:** Regenerate the dashboard server-side on edit, or add a visible "Refresh" prompt after actions.

### [P3] Hard-coded author initials/name in preview
- **File:** `pipeline/review_dashboard.py:110-120`
- **Risk:** Removed per user request in latest commit. No longer present.
- **Action:** N/A — resolved.

### [P3] `REVIEW_SKIPPED_DIR` defined but not used in dashboard generator
- **File:** `pipeline/review_dashboard.py:25`
- **Risk:** Minor dead code; skipped logic lives in `pipeline/approval.py`.
- **Action:** Remove unused import or document why it exists.

## Overall assessment

The dashboard is functionally correct, mobile-friendly, and preserves the human-in-the-loop approval gate. The main residual risks are XSS hygiene (currently safe but fragile) and lack of rate limiting on image regeneration. Tests pass; ruff clean.

## Recommended next actions
1. Fix `_format_post_body` ordering to escape once at the end.
2. Add server-side cooldown for `/api/regenerate-image`.
3. Harden static file path check with explicit `..` rejection and `is_file()`.
4. Run L4 verifier before merge.
