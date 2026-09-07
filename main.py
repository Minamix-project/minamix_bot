import sys
from pathlib import Path

# Sur certains hébergeurs (ex. panel type Pterodactyl/KataBump), le CWD ou la
# façon dont `python main.py` est lancé empêche de résoudre le paquet `src`.
_ROOT = Path(__file__).resolve().parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from src.bot import run_bot  # noqa: E402

if __name__ == "__main__":
    run_bot()
