"""Build a source ZIP without credentials, databases or dependencies."""
from pathlib import Path
from zipfile import ZIP_DEFLATED, ZipFile
import os

ROOT = Path(__file__).resolve().parents[1]
EXCLUDE = {".git", ".venv", "node_modules", "__pycache__", ".pytest_cache", ".ruff_cache", "dist", "artifacts", "test-results", "playwright-report", "private"}
destination = ROOT / "artifacts" / "sierra-mvp.zip"
destination.parent.mkdir(exist_ok=True)
with ZipFile(destination, "w", ZIP_DEFLATED) as archive:
    for directory, directories, filenames in os.walk(ROOT):
        directories[:] = sorted(d for d in directories if d not in EXCLUDE and not d.endswith(".egg-info"))
        for filename in sorted(filenames):
            path = Path(directory) / filename
            if path.is_symlink():
                continue
            if path.name == ".env" or path.name.startswith(".env.") and path.name != ".env.example":
                continue
            if path.suffix in {".db", ".pyc"} or ".db-" in path.name or path.name == ".DS_Store":
                continue
            archive.write(path, Path("sierra-mvp") / path.relative_to(ROOT))
print(destination)
