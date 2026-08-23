# Security Review Agent — LinkedIn Pipeline

## Scope
Review the working tree changes (mcp_server.py, pipeline/llm_client.py, pipeline/youtube_draft.py, tests/conftest.py, tests/test_youtube_draft.py) and the repo overall for security flaws.

## Checklist
1. Secrets handling: Are any secrets logged, printed, or committed? Is .env.example safe?
2. Token encryption: Is Fernet used correctly? Is salt constant acceptable?
3. MCP server: Is there auth? Is it bound safely? Are dangerous tools exposed without guardrails?
4. LLM client: Are API keys sent to the right base URL? Is timeout/HTTPS handled?
5. YouTube draft: Are URLs validated? Is fetched content sanitized before DB storage?
6. SQL injection: Is parameterized SQL used everywhere?
7. OS command injection: Any user input passed to subprocess/shell?
8. Supply chain: Are pinned dependency versions safe? Any unnecessary broad imports?
9. Privacy: Is user data (LinkedIn tokens) protected at rest and in transit?

## Output format
Return a short Markdown report: Critical/High/Medium/Low issues with file paths and concrete remediation.
