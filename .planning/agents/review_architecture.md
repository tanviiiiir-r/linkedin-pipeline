# Architecture / Maintainability Review Agent — LinkedIn Pipeline

## Scope
Review working tree changes and existing architecture for maintainability, testability, and alignment with Python industry standards.

## Checklist
1. Are modules loosely coupled? Are there circular imports?
2. Is configuration centralized? Are env vars loaded eagerly vs lazily?
3. Are functions small and single-purpose? Are there overly broad try/except blocks?
4. Is there adequate test coverage? Are tests deterministic and isolated?
5. Type hints, docstrings, linting (ruff) — any issues?
6. Is the MCP server using FastMCP correctly? Tool registration order, names, schemas.
7. Does youtube_to_draft integrate cleanly with the rest of the pipeline?
8. Are there duplicate helpers across modules?

## Output format
Markdown report with concrete refactor suggestions and priority.
