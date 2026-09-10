# CGV PUSH BOT repository working agreements

## Project scope

- This repository provides a Discord application for CGV movie schedule alerts.
- Keep `cgv_push_bot.cgv` usable as an independent in-process library. Do not couple that package to
  Discord, SQLAlchemy, a scheduler, a database, environment variables, or notification logic.
- Keep transport, persistence, alert orchestration, and Discord presentation in their respective
  `cgv`, `db`, `alerts`, and `discord_ui` packages.

## Architecture

- Production code lives under `src/cgv_push_bot/`; tests mirror it under `tests/`.
- Keep CGV transport details, response parsing, normalized models, and public client interfaces in
  separate modules as they are introduced.
- Prevent CGV-specific cookies, encrypted identifiers, XML shapes, and headers from leaking through
  public interfaces unless they are explicitly part of a low-level API.
- Prefer explicit typed models and narrow public exports. Avoid wildcard imports and process-wide
  mutable state.
- No module may perform network access, create database or HTTP sessions, read environment variables,
  run migrations, or connect to Discord merely because it was imported.

## HTTP and security

- Use an owned HTTP session and cookie jar; never commit cookies, tokens, captured responses containing
  credentials, or personal browser data.
- Set finite timeouts and handle HTTP status failures explicitly. Do not disable TLS verification.
- Keep request headers minimal and document any header or bootstrap request that CGV actually requires.
- Tests must mock external network access. Do not send requests to CGV from the default test suite.
- Redact cookies, tokens, and sensitive headers from logs and exceptions.

## Development workflow

- Use Python 3.12 or later and manage environments and dependencies exclusively with `uv`.
- Add runtime dependencies to `[project].dependencies` and development-only tools to
  `[dependency-groups].dev` in `pyproject.toml`.
- After changes, run the smallest relevant test first, followed by:

  ```bash
  uv run ruff check .
  uv run ruff format --check .
  uv run pyright
  uv run pytest
  uv build
  ```

- Update `uv.lock` whenever dependency metadata changes.
- Add tests for changed behavior and review the final diff for secrets, captured data, generated files,
  and unrelated changes before committing.

## Git conventions

- Keep commits focused and use concise imperative commit messages.
- Do not commit virtual environments, local environment files, AI tool state or captured CGV payloads.
- `AGENTS.md` is the intentionally tracked exception among agent-related files because it defines the
  repository's collaboration and verification rules.
