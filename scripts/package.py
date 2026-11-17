"""Archive the current committed source, rejecting private or generated paths."""
from pathlib import Path
import subprocess

ROOT = Path(__file__).resolve().parents[1]
EXCLUDE = {".git", ".venv", "node_modules", "__pycache__", ".pytest_cache", ".ruff_cache", "dist", "artifacts", "test-results", "playwright-report", "private"}
destination = ROOT / "artifacts" / "sierra-mvp.zip"
destination.parent.mkdir(exist_ok=True)
names = subprocess.check_output(["git", "ls-tree", "-r", "--name-only", "HEAD"], cwd=ROOT, text=True).splitlines()
for name in names:
    path = Path(name)
    private = path.name == ".env" or path.name.startswith(".env.") and path.name != ".env.example"
    generated = bool(set(path.parts) & EXCLUDE) or path.suffix in {".db", ".pyc"} or ".db-" in path.name
    if private or generated:
        raise SystemExit(f"Refusing to package private/generated tracked path: {name}")
subprocess.run(["git", "archive", "--format=zip", "--prefix=sierra-mvp/", "HEAD", "-o", str(destination)], cwd=ROOT, check=True)
print(destination)
