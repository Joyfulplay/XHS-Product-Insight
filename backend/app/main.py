from fastapi import FastAPI

app = FastAPI(title="XHS Product Insight API")


@app.get("/")
def read_root() -> dict:
    return {
        "project": "XHS-Product-Insight",
        "status": "initialized",
        "message": "Backend API entry point is ready.",
    }
