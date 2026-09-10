FROM ghcr.io/astral-sh/uv:0.11.26-python3.12-trixie-slim

ENV PYTHONUNBUFFERED=1 \
    PATH="/app/.venv/bin:$PATH"

WORKDIR /app

COPY pyproject.toml uv.lock README.md LICENSE ./
RUN uv sync --frozen --no-dev --no-install-project

COPY src ./src
RUN uv sync --frozen --no-dev

RUN useradd --create-home --uid 10001 cgv-push-bot \
    && mkdir -p /app/data \
    && chown -R cgv-push-bot:cgv-push-bot /app/data

USER cgv-push-bot

CMD ["python", "-m", "cgv_push_bot"]
