# Build context is the repo root (see docker-compose.yml) so this image can
# also copy odoo_profile.json — the single source of truth for Odoo facts,
# see CLAUDE.md ground rule 2.

FROM python@sha256:67994a05c712036dbfc4385b4bceafc0ce20df950f54b9ea355582c153bf6157

# python:3.14-slim, pinned by digest — see docs/implementation-plan.md Appendix E.

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
