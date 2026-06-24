from fastapi import FastAPI
from pydantic import BaseModel

app = FastAPI(title="Cortex License Server")


class ValidateRequest(BaseModel):
    license_key: str
    machine_id: str


@app.post("/validate")
def validate(req: ValidateRequest):
    return {"valid": True, "expires": "2099-12-31"}


@app.get("/health")
def health():
    return {"status": "ok"}
