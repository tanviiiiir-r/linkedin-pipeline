import sys
from pathlib import Path

repo = Path(__file__).resolve().parent.parent
if str(repo) not in sys.path:
    sys.path.insert(0, str(repo))

from datetime import datetime, timezone

from pipeline.drafting import Draft
from pipeline.verify import Verdict, verify_draft


def test_verify_approve_good_draft():
    draft = Draft(
        item_id="good123",
        pillar="builder_memo",
        title="How LLM agents leak secrets through tool use",
        source_url="https://example.com/agent-tool-leak",
        created_at=datetime.now(timezone.utc).isoformat(),
        linkedin_post="""Indirect prompt injection just got a lot more practical.

A new paper shows an attacker can exfiltrate data when an LLM agent calls a compromised tool. The model trusts the return, so the leak happens without the user noticing.

The detail I'd watch is the tool boundary: most agents assume tool outputs are safe, but they're just another input channel.

For builders, the move is to treat every tool call as hostile: validate outputs, scope permissions tightly, and log what the agent actually sends.

Read more: https://example.com/agent-tool-leak

#AgentSecurity #ToolUse #PromptInjection #SecureAI""",
        newsletter_section="""## How LLM agents leak secrets through tool use

**Source:** https://example.com/agent-tool-leak

**Signal strength:** Builder Memo — 80% confidence
**Topics:** agent-security, tool-use, prompt-injection

**The finding:** A new paper shows that indirect prompt injection can exfiltrate data when an agent calls a compromised tool.

**Builder takeaway:** Audit every tool your agent can call and assume the prompt context is hostile.

**Security / reliability angle:** Add timeouts, output validation, and least-privilege scopes to agent tool calls.

**Efficiency / cost angle:** Cheap sanity checks now prevent expensive incidents later.

**Why this matters now:** Tool-use agents are becoming the default interface pattern, and this paper shows that the trust boundary most teams ignore is exactly where the leak happens.""",
        short_pill="Agent tool leaks are the next XSS — verify every call.",
        forward_pill="If tool-use agents become standard, this attack surface defines the next 6 months of AI security work.",
        narrative_pill="A builder I follow flagged the agent tool leak paper. Here's why I paused: it maps cleanly onto every API an agent touches.",
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


def test_verify_reject_generic_template():
    draft = Draft(
        item_id="generic123",
        pillar="builder_memo",
        title="Some AI thing happened",
        source_url="https://example.com/ai-thing",
        created_at=datetime.now(timezone.utc).isoformat(),
        linkedin_post="""Why builders should care: this is the kind of signal that shifts how we design, deploy, and secure AI systems. Watch it, experiment with it, and share what breaks.

Read more: https://example.com/ai-thing

#AI #MachineLearning""",
        newsletter_section="Generic newsletter.",
        short_pill="",
        forward_pill="",
        narrative_pill="",
        hashtags=["#AI", "#MachineLearning"],
    )
    result = verify_draft(draft)
    assert result.verdict in (Verdict.REJECT, Verdict.UNCERTAIN), f"expected REJECT/UNCERTAIN, got {result.verdict}"
    assert any("generic" in r.lower() or "templated" in r.lower() or "Why builders" in r for r in result.reasons)
    print("test_verify_reject_generic_template passed")


def test_verify_reject_fabricated_experience():
    draft = Draft(
        item_id="fabricated123",
        pillar="tool_drop",
        title="New tool",
        source_url="https://example.com/tool",
        created_at=datetime.now(timezone.utc).isoformat(),
        linkedin_post="""I tested this new tool over the weekend and my team shipped it to production. We deployed it across three services.

Read more: https://example.com/tool

#AI""",
        newsletter_section="Tool notes.",
        short_pill="",
        forward_pill="",
        narrative_pill="",
        hashtags=["#AI"],
    )
    result = verify_draft(draft)
    assert result.verdict in (Verdict.REJECT, Verdict.UNCERTAIN), f"expected REJECT/UNCERTAIN, got {result.verdict}"
    assert any("fabricated" in r.lower() or "first-person" in r.lower() or "experience" in r.lower() for r in result.reasons)
    print("test_verify_reject_fabricated_experience passed")


def test_verify_detects_weak_pov():
    draft = Draft(
        item_id="weakpov123",
        pillar="viral_explained",
        title="A model was released",
        source_url="https://example.com/model",
        created_at=datetime.now(timezone.utc).isoformat(),
        linkedin_post="""A model was released. It has new features. It is available on GitHub.

Read more: https://example.com/model

#AI #GitHub""",
        newsletter_section="Model released.",
        short_pill="",
        forward_pill="",
        narrative_pill="",
        hashtags=["#AI", "#GitHub"],
    )
    result = verify_draft(draft)
    assert not result.checks.get("has_point_of_view", result.checks.get("has_pov", False))
    assert any("summary" in r.lower() or "interpretation" in r.lower() for r in result.reasons)
    print("test_verify_detects_weak_pov passed")


if __name__ == "__main__":
    test_verify_approve_good_draft()
    test_verify_reject_ai_sounding()
    test_verify_reject_missing_link()
    test_verify_reject_generic_template()
    test_verify_reject_fabricated_experience()
    test_verify_detects_weak_pov()
    print("verify tests passed")
