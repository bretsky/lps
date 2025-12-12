from pathlib import Path

# Root of the project (pyproject.toml lives here)
PROJECT_ROOT = Path(__file__).resolve().parents[2]

# Data directories
DATA_DIR = PROJECT_ROOT / "data"
ORACLE_DIR = DATA_DIR / "oracle"
