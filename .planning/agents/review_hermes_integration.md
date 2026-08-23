# Hermes Integration Review Agent — LinkedIn Pipeline

## Scope
Review MCP tools, auth, and operational flow from the perspective of an agent driving the pipeline.

## Checklist
1. Are MCP tool names descriptive? Are descriptions useful for an LLM?
2. Are tool return schemas consistent and parseable?
3. Is the human-in-the-loop approval gate unambiguous in tool descriptions?
4. Are dry-run vs real publish semantics clear to the agent?
5. Does the agent have enough tools to run collect→score→draft→approve→publish end-to-end?
6. Are error messages actionable for an LLM (e.g. "set LINKEDIN_CLIENT_ID")?
7. Is youtube_to_draft discoverable and well-described?

## Output format
Markdown report with suggested tool/UX improvements.
