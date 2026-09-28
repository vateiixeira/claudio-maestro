from fastapi import FastAPI

app = FastAPI(title="Vini7 Vibing")


@app.get("/api/health")
def health() -> dict[str, str]:
    return {"status": "ok"}
