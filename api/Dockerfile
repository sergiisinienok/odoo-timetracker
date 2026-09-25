# Build context is the repo root (see docker-compose.yml) so this image can
# also copy odoo_profile.json — the single source of truth for Odoo facts,
# see CLAUDE.md ground rule 2.

FROM python@sha256:caaf356f40667c496d405780745b9ac25771c189a51dfcc42430d531ea09f8a2

# python:3.14-slim, pinned by digest — see docs/implementation-plan.md Appendix E.
# The digest is the multi-architecture *index*, not one platform's image, so the
# same pin builds on an arm64 laptop and an amd64 server (docs/deploy-staging.md).

RUN pip install --no-cache-dir uv==0.12.16

WORKDIR /app

COPY api/pyproject.toml api/uv.lock ./
RUN uv sync --frozen --no-install-project

COPY api/src ./src
COPY api/alembic ./alembic
COPY api/alembic.ini ./
COPY api/tests ./tests
RUN uv sync --frozen

COPY odoo_profile.json /app/odoo_profile.json
ENV ODOO_PROFILE_PATH=/app/odoo_profile.json
ENV PATH="/app/.venv/bin:${PATH}"

EXPOSE 8000

CMD ["uvicorn", "tti.main:app", "--app-dir", "src", "--host", "0.0.0.0", "--port", "8000"]
