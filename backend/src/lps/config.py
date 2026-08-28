import os
from pathlib import Path

from dotenv import load_dotenv

# Root of the project (pyproject.toml lives here)
PROJECT_ROOT = Path(__file__).resolve().parents[2]

# Load environment variables from .env file
load_dotenv(PROJECT_ROOT / ".env")

# Data directories
DATA_DIR = PROJECT_ROOT / "data"
ORACLE_DIR = DATA_DIR / "oracle"
LEAGUEPEDIA_DIR = DATA_DIR / "leaguepedia"
INFO_DIR = PROJECT_ROOT / "info"

# Leaguepedia credentials (from .env file or environment variables)
LP_USERNAME = os.getenv("LP_USERNAME", "")
LP_PASSWORD = os.getenv("LP_PASSWORD", "")
