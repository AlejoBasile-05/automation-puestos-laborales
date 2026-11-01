"""Package-relative resolvers for data files shipped with JobRadar.

Prompt templates live inside the package (``src/jobradar/prompts``) so the CLI
works no matter which directory the process was started from.
"""

from pathlib import Path

PACKAGE_DIR = Path(__file__).resolve().parent
PROMPTS_DIR = PACKAGE_DIR / "prompts"


def prompt_path(name: str) -> Path:
    """Return the absolute path of a packaged prompt template."""
    return PROMPTS_DIR / name
