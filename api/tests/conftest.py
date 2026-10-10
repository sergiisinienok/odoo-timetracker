import os
from pathlib import Path

from dotenv import load_dotenv

# override=True: this shell may already have a stale, empty value exported
# for a variable that was blank in .env at some earlier point (oh-my-zsh's
# dotenv plugin auto-sources .env on every `cd` into the repo — see
# CLAUDE.md's "Running the app" section). Without override, load_dotenv
# would leave that stale value in place instead of the current .env.
load_dotenv(Path(__file__).resolve().parents[2] / ".env", override=True)

# .env's DATABASE_URL points at the "db" hostname, which only resolves
# inside the docker-compose network. Tests run on the host (docker-compose.yml
# publishes db's port for exactly this) — swap in localhost.
os.environ["DATABASE_URL"] = f"postgresql+psycopg://tti:{os.environ['POSTGRES_PASSWORD']}@localhost:5432/tti"
