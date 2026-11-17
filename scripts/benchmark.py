"""Sequential local HTTP-stack benchmark; disposable database, no external API calls."""
import statistics
import sys
import tempfile
import time
import uuid
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "backend"))
from fastapi.testclient import TestClient
from sierra.config import Settings
from sierra.main import create_app

with tempfile.TemporaryDirectory() as directory:
    app = create_app(Settings(database_url=f"sqlite:///{directory}/benchmark.db", anthropic_api_key=""))
    app.state.limiter.limit = 10000
    with TestClient(app) as client:
        client.get("/api/session")
        cases = ["Track #W001 for explorer01@example.com", "推荐一个适合徒步的防雨背包"]
        timings = []
        for index in range(100):
            started = time.perf_counter()
            response = client.post("/api/chat", json={"message": cases[index % 2], "request_id": str(uuid.uuid4())})
            response.raise_for_status()
            assert response.json()["grounded"]
            timings.append((time.perf_counter() - started) * 1000)
        ordered = sorted(timings)
        print({"requests": len(timings), "mode": "local, sequential, SQLite, TestClient",
               "p50_ms": round(statistics.median(timings), 2), "p95_ms": round(ordered[94], 2),
               "max_ms": round(max(timings), 2)})
