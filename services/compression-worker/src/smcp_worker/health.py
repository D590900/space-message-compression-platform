from fastapi import FastAPI

app = FastAPI(title="SMCP compression worker health", docs_url=None, redoc_url=None)


@app.get("/health/live")
def live() -> dict[str, str]:
    return {"status": "ok"}
