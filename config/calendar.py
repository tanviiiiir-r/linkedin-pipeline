"""7-day editorial calendar for LinkedIn content.

Each day maps to a post type, a scoring lens, prompt instructions, and a default
hashtag set. The pipeline uses this to pick the best signal of the day and draft
a post that fits the day's job.
"""
from dataclasses import dataclass
from datetime import date, datetime, timezone


@dataclass
class DayPlan:
    day_name: str
    post_type: str
    job: str
    lens: str
    prompt_role: str
    prompt_instructions: str
    source_bias: list[str]
    hashtag_set: list[str]


_DAY_PLANS: dict[str, DayPlan] = {
    "Monday": DayPlan(
        day_name="Monday",
        post_type="tool_drop",
        job="New tool/API/repo with a one-line builder use case",
        lens="tool, api, sdk, library, framework, plugin, release, launch, open source, github repo",
        prompt_role="You are a practical AI-tools curator for builders.",
        prompt_instructions=(
            "Write a LinkedIn post about a new tool/API/repo. Lead with the one-line use case. "
            "Explain what changed, why a builder should care, and one concrete thing to try. "
            "Keep it under 200 words, direct, no buzzwords."
        ),
        source_bias=["GitHub", "Product Hunt", "Hacker News", "Latent Space"],
        hashtag_set=["#AI", "#BuilderTools", "#MachineLearning"],
    ),
    "Tuesday": DayPlan(
        day_name="Tuesday",
        post_type="viral_explained",
        job="Translate a trending demo/launch/paper for builders",
        lens="demo, explained, new model, released, announced, watch, trending, viral, launch",
        prompt_role="You translate AI hype into builder meaning.",
        prompt_instructions=(
            "A trending AI signal just dropped. Explain what actually happened, strip the hype, "
            "and tell builders why it matters for their work. Keep it under 220 words."
        ),
        source_bias=["Hacker News", "The Decoder", "arXiv", "Two Minute Papers", "AI Explained"],
        hashtag_set=["#AI", "#TechTrends", "#Explainer"],
    ),
    "Wednesday": DayPlan(
        day_name="Wednesday",
        post_type="pattern_spotting",
        job="Connect 2–3 related signals into an emerging workflow",
        lens="pattern, workflow, shift, trend, move toward, convergence, architecture, orchestration",
        prompt_role="You spot patterns before they become obvious.",
        prompt_instructions=(
            "Look at 2-3 related signals and connect them into one emerging workflow or shift. "
            "Name the pattern, give evidence, and say what it enables next. Keep it under 240 words."
        ),
        source_bias=["Hacker News", "GitHub", "Reddit", "Interconnects"],
        hashtag_set=["#AI", "#PatternSpotting", "#EmergingTech"],
    ),
    "Thursday": DayPlan(
        day_name="Thursday",
        post_type="builder_memo",
        job="Practical trick: cost, latency, prompt, deployment",
        lens="how to, tutorial, build, deploy, cost, performance, latency, optimize, recipe, trick",
        prompt_role="You write short, practical memos for AI builders.",
        prompt_instructions=(
            "Write a builder memo: one practical trick, workflow, or lesson learned about building "
            "or deploying AI. Lead with the outcome, show the move, and end with a takeaway. "
            "Keep it under 200 words."
        ),
        source_bias=["Simon Willison", "Eugene Yan", "Chip Huyen", "LangChain", "Cloudflare"],
        hashtag_set=["#AI", "#BuilderMemo", "#DevTips"],
    ),
    "Friday": DayPlan(
        day_name="Friday",
        post_type="security_signal",
        job="AI security, red-team, vulnerability, safety eval",
        lens="vulnerability, attack, exploit, red team, red-teaming, prompt injection, jailbreak, "
             "adversarial, safety eval, cve, model security, agent security, sandbox, mitigation",
        prompt_role="You make AI security readable for builders.",
        prompt_instructions=(
            "Write a security signal post. What broke, how was it tested, and what should builders "
            "do about it? Be specific, not alarmist. Keep it under 220 words."
        ),
        source_bias=["PortSwigger", "Dark Reading", "BleepingComputer", "arXiv", "GitHub Security"],
        hashtag_set=["#AI", "#AISecurity", "#RedTeam"],
    ),
    "Saturday": DayPlan(
        day_name="Saturday",
        post_type="founder_signal",
        job="Signal that attracts founders: GTM, moat, pricing, wedge, market timing",
        lens="founder, startup, indie hacker, go-to-market, gtm, pricing, unit economics, moat, "
             "distribution, product-market fit, pmf, wedge, positioning, bootstrapped, traction, "
             "market timing, founder insight, runway, burn rate, mvp",
        prompt_role="You write founder signal posts that attract builders who are thinking about starting companies.",
        prompt_instructions=(
            "This post is for founders and indie hackers. Take a signal from the AI landscape "
            "and extract what it means for company-building: a wedge, a GTM shift, a pricing move, "
            "a moat change, or market timing. Ask a sharp question at the end to spark discussion. "
            "Keep it under 260 words."
        ),
        source_bias=["Indie Hackers", "Hacker News", "TechCrunch", "The Information", "Lenny's Newsletter"],
        hashtag_set=["#AI", "#FounderSignal", "#StartupBuilder", "#IndieHacker", "#AIMoat"],
    ),
    "Sunday": DayPlan(
        day_name="Sunday",
        post_type="tomorrow_in_ai",
        job="Prediction, question, or weekly synthesis",
        lens="prediction, future, next, what if, could, will change, outlook, synthesis, recap",
        prompt_role="You write forward-looking AI synthesis for builders.",
        prompt_instructions=(
            "Synthesize the week's signals into one prediction or sharp question about where AI is "
            "heading for builders. Don't summarize everything; pick the one trajectory that matters. "
            "Keep it under 240 words."
        ),
        source_bias=["The Batch", "Import AI", "Interconnects", "Simon Willison"],
        hashtag_set=["#AI", "#FutureOfAI", "#ThoughtLeadership"],
    ),
}


def day_plan(for_date: date | None = None) -> DayPlan:
    """Return the editorial plan for a given date (default today)."""
    d = for_date or datetime.now(timezone.utc).date()
    return _DAY_PLANS[d.strftime("%A")]


DAY_NAMES: dict[str, DayPlan] = _DAY_PLANS


def post_type_for_date(for_date: date | None = None) -> str:
    return day_plan(for_date).post_type
