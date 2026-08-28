import os
import tempfile
from pathlib import Path

database_path = Path(tempfile.gettempdir()) / "openroboops-tests.db"
database_path.unlink(missing_ok=True)
os.environ["OPENROBOOPS_DATABASE_URL"] = f"sqlite+aiosqlite:///{database_path}"
os.environ["OPENROBOOPS_COOKIE_SECURE"] = "false"
os.environ["OPENROBOOPS_SEED_SIMULATOR"] = "true"
