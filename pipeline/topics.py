"""Topic extraction and taxonomy tagging for pipeline items.

Uses a keyword-driven taxonomy aligned with the user's SOURCE-MAP.md, with
source-specific boosts and lightweight anti-noise filtering.
"""
import re
from collections import Counter

# Taxonomy from SOURCE-MAP.md
TAXONOMY = {
    "AI Builder": [
        "ai-agents", "llm-apps", "rag", "mcp", "tool-use", "agent-memory",
        "agent-orchestration", "coding-agents", "ai-devtools", "open-source-ai",
    ],
    "AI Research": [
        "new-model", "reasoning", "multimodal", "reinforcement-learning",
        "post-training", "synthetic-data", "evaluation", "model-architecture", "ai-science",
    ],
    "AI Security": [
        "prompt-injection", "indirect-prompt-injection", "agent-security", "model-security",
        "data-exfiltration", "tool-security", "identity-access", "sandboxing",
        "ai-red-teaming", "model-evaluation", "supply-chain-security",
    ],
    "AI Efficiency": [
        "inference", "quantization", "distillation", "caching", "speculative-decoding",
        "latency", "gpu", "accelerators", "model-routing", "cost-optimization",
    ],
    "AI Systems": [
        "ai-infrastructure", "observability", "deployment", "mlops", "llmops",
        "distributed-systems", "databases", "vector-databases", "cloud", "reliability",
    ],
}

# Flat topic keywords: topic -> list of signals
_TOPIC_KEYWORDS: dict[str, list[str]] = {
    # AI Builder
    "ai-agents": ["agent", "agents", "agentic", "autonomous agent", "ai agent"],
    "llm-apps": ["llm app", "chatbot", "application", "product", "launch"],
    "rag": ["rag", "retrieval augmented", "retrieval-augmented"],
    "mcp": ["mcp", "model context protocol"],
    "tool-use": ["tool use", "function calling", "tools", "api call"],
    "agent-memory": ["agent memory", "memory for agents", "long-term memory"],
    "agent-orchestration": ["orchestrat", "multi-agent", "swarm", "workflow"],
    "coding-agents": ["coding agent", "code generation", "devin", "cursor", "copilot"],
    "ai-devtools": ["devtool", "developer tool", "sdk", "library", "framework"],
    "open-source-ai": ["open source", "open-source model", "weights", "huggingface"],

    # AI Research
    "new-model": ["new model", "released", "announced", "llm", "announces"],
    "reasoning": ["reasoning", "chain of thought", "cot", "inference-time compute"],
    "multimodal": ["multimodal", "vision model", "audio model", "image generation"],
    "reinforcement-learning": ["reinforcement learning", "rlhf", "rl", "reward model"],
    "post-training": ["post-training", "fine-tune", "sft", "instruction tuning"],
    "synthetic-data": ["synthetic data", "data generation", "augmentation"],
    "evaluation": ["benchmark", "evaluation", "eval", "leaderboard"],
    "model-architecture": ["transformer", "mamba", "mixture of experts", "moe", "architecture"],
    "ai-science": ["ai for science", "protein", "drug discovery", "weather"],

    # AI Security
    "prompt-injection": ["prompt injection", "jailbreak", "adversarial prompt"],
    "indirect-prompt-injection": ["indirect prompt injection", "data poisoning", "embedded instruction"],
    "agent-security": ["agent security", "ai agent security", "agent sandbox"],
    "model-security": ["model extraction", "model theft", "membership inference"],
    "data-exfiltration": ["exfiltration", "data leak", "pii leak"],
    "tool-security": ["tool security", "function call security", "plugin security"],
    "identity-access": ["identity", "access control", "permissions", "oauth"],
    "sandboxing": ["sandbox", "isolation", "containment"],
    "ai-red-teaming": ["red team", "red-teaming", "adversarial evaluation"],
    "model-evaluation": ["ai safety", "safety eval", "alignment eval"],
    "supply-chain-security": ["supply chain", "model supply chain", "dependency", "huggingface malicious"],

    # AI Efficiency
    "inference": ["inference", "serving", "throughput"],
    "quantization": ["quantization", "quantized", "int8", "fp16", "gguf"],
    "distillation": ["distillation", "distilled", "student model"],
    "caching": ["kv cache", "cache", "prefix caching"],
    "speculative-decoding": ["speculative decoding", "draft model"],
    "latency": ["latency", "time to first token", "ttft"],
    "gpu": ["gpu", "cuda", "nvidia", "a100", "h100"],
    "accelerators": ["tpu", "npu", "asic", "edge device", "hardware accelerator"],
    "model-routing": ["model routing", "router", "cascade", "fall-back model"],
    "cost-optimization": ["cost", "pricing", "cheaper", "efficient", "optimization"],

    # AI Systems
    "ai-infrastructure": ["infrastructure", "orchestration", "kubernetes", "k8s"],
    "observability": ["observability", "monitoring", "tracing", "llm observability"],
    "deployment": ["deployment", "production", "serving infrastructure"],
    "mlops": ["mlops", "pipeline", "feature store"],
    "llmops": ["llmops", "prompt management", "prompt versioning"],
    "distributed-systems": ["distributed", "ray", "horovod", "multi-node"],
    "databases": ["database", "sql", "nosql", "data platform"],
    "vector-databases": ["vector database", "vector store", "embedding store"],
    "cloud": ["cloud", "aws", "azure", "gcp", "google cloud"],
    "reliability": ["reliability", "failover", "resilience", "sla"],
}


def _preprocess(text: str) -> str:
    text = re.sub(r"[^a-zA-Z0-9\- ]+", " ", text)
    text = re.sub(r"\s+", " ", text)
    return text.lower()


def extract_topics(text: str, top_n: int = 5, min_hits: int = 1) -> list[str]:
    """Return top matching topics from the taxonomy for the given text."""
    text = _preprocess(text)
    topic_hits: Counter[str] = Counter()

    for topic, signals in _TOPIC_KEYWORDS.items():
        for signal in signals:
            # Count whole-word-ish matches
            count = len(re.findall(r"\b" + re.escape(signal) + r"\b", text))
            if count:
                topic_hits[topic] += count

    # Boost multi-word exact phrases
    for topic, signals in _TOPIC_KEYWORDS.items():
        for signal in signals:
            if " " in signal and signal in text:
                topic_hits[topic] += 2

    # Return topics with at least min_hits, sorted by hit count
    results = [(t, c) for t, c in topic_hits.items() if c >= min_hits]
    results.sort(key=lambda x: (-x[1], x[0]))
    return [t for t, _ in results[:top_n]]


def primary_topic(topics: list[str]) -> str | None:
    return topics[0] if topics else None


def hashtags_from_topics(topics: list[str]) -> list[str]:
    """Convert topics into a compact, non-generic hashtag set."""
    tags: list[str] = []
    for t in topics[:4]:
        # Create readable hashtags
        clean = "".join(w.capitalize() for w in t.replace("-", " ").split())
        tag = f"#{clean}"
        if tag not in tags:
            tags.append(tag)
    # Always add one broad tag if we have room
    if len(tags) < 5:
        tags.append("#SecureAI")
    return tags


if __name__ == "__main__":
    sample = (
        "New paper shows quantized LLM agents can be compromised via indirect prompt injection "
        "when tool use is enabled. We evaluated latency, KV cache efficiency, and cloud deployment risks."
    )
    print("Topics:", extract_topics(sample))
    print("Hashtags:", hashtags_from_topics(extract_topics(sample)))
