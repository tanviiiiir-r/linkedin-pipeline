import sys
from pathlib import Path

repo = Path(__file__).resolve().parent.parent
if str(repo) not in sys.path:
    sys.path.insert(0, str(repo))

from pipeline.drafting import Draft
from pipeline.verify import VerifyResult, Verdict, format_verdict, verify_draft
from datetime import datetime, timezone


def test_verify_approve_good_draft():
    draft = Draft(
        item_id="good123",
        pillar="builder_memo",
        title="How LLM agents leak secrets through tool use",
        source_url="https://example.com/agent-tool-leak",
        created_at=datetime.now(timezone.utc).isoformat(),
        linkedin_post="""Builder memo: How LLM agents leak secrets through tool use

What changed: A new paper shows that indirect prompt injection can exfiltrate data when an agent calls a compromised tool.

Why builders should care: this is the kind of signal that shifts how we design, deploy, and secure AI systems.

Read more: https://example.com/agent-tool-leak

#AgentSecurity #ToolUse #PromptInjection #SecureAI""",
        newsletter_section="## How LLM agents leak secrets through tool use\n\n**Source:** https://example.com/agent-tool-leak\n\n**What changed:** A new paper shows that indirect prompt injection can exfiltrate data when an agent calls a compromised tool.\n\n**Builder takeaway:** Audit every tool your agent can call.\n\n**Security angle:** Add timeouts and least-privilege scopes.\n\n**Efficiency angle:** Cheap sanity checks prevent expensive incidents.",
        short_pill="Agent tool leaks are the next XSS.",
        forward_pill="Tool-use agents will define the next 6 months of AI security.",
        narrative_pill="A builder flagged this paper. It maps to every API an agent touches.",
        hashtags=["#AgentSecurity", "#ToolUse", "#PromptInjection", "#SecureAI"],
    )
    result = verify_draft(draft)
    assert result.verdict == Verdict.APPROVE, f"expected APPROVE, got {result.verdict}"
    assert result.score >= 80
    print("test_verify_approve_good_draft passed")


def test_verify_reject_ai_sounding():
    draft = Draft(
        item_id="bad123",
        pillar="tool_drop",
        title="Revolutionary AI Tool Unleashes the Power of Seamless Innovation",
        source_url="https://example.com/tool",
        created_at=datetime.now(timezone.utc).isoformat(),
        linkedin_post="""In today's fast-paced world, this game-changer leverages AI to revolutionize the industry. Unlock the potential of seamless innovation. Key takeaway: navigate the complexities with this powered-by-AI solution.

Read more: https://example.com/tool

#AI #Technology""",
        newsletter_section="This is a revolutionary AI-driven tool.",
        short_pill="",
        forward_pill="",
        narrative_pill="",
        hashtags=["#AI", "#Technology"],
    )
    result = verify_draft(draft)
    assert result.verdict == Verdict.REJECT, f"expected REJECT, got {result.verdict}"
    assert result.score < 55
    print("test_verify_reject_ai_sounding passed")


def test_verify_reject_missing_link():
    draft = Draft(
        item_id="nolink123",
        pillar="builder_memo",
        title="Important security finding",
        source_url="https://example.com/security",
        created_at=datetime.now(timezone.utc).isoformat(),
        linkedin_post="Important security finding today. #SecureAI",
        newsletter_section="Some notes.",
        short_pill="",
        forward_pill="",
        narrative_pill="",
        hashtags=["#SecureAI"],
    )
    result = verify_draft(draft)
    assert result.verdict in (Verdict.REJECT, Verdict.UNCERTAIN), f"expected REJECT/UNCERTAIN, got {result.verdict}"
    print("test_verify_reject_missing_link passed")


if __name__ == "__main__":
    test_verify_approve_good_draft()
    test_verify_reject_ai_sounding()
    test_verify_reject_missing_link()
    print("verify tests passed")
