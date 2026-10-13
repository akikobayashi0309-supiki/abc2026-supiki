from datetime import datetime
from typing import Annotated

from fastapi import Depends, FastAPI
from pydantic import BaseModel, Field

from app.auth import User, get_current_user
from app.config import Settings, get_settings
from app.gemini import Gemini, get_gemini
from app.store import Store, get_store

app = FastAPI(title="api")

CurrentUser = Annotated[User, Depends(get_current_user)]


class GenerateRequest(BaseModel):
    prompt: str = Field(min_length=1, max_length=4000)


class Generation(BaseModel):
    id: str
    prompt: str
    output: str
    model: str
    createdAt: datetime


@app.get("/api/healthz")
def healthz() -> dict[str, str]:
    return {"status": "ok"}


@app.post("/api/generate")
def generate(
    body: GenerateRequest,
    user: CurrentUser,
    gemini: Annotated[Gemini, Depends(get_gemini)],
    store: Annotated[Store, Depends(get_store)],
    settings: Annotated[Settings, Depends(get_settings)],
) -> Generation:
    output = gemini.generate(body.prompt)
    saved = store.save_generation(user.uid, body.prompt, output, settings.gemini_model)
    return Generation(**saved)


@app.get("/api/generations")
def list_generations(
    user: CurrentUser,
    store: Annotated[Store, Depends(get_store)],
    settings: Annotated[Settings, Depends(get_settings)],
) -> list[Generation]:
    return [Generation(**doc) for doc in store.list_generations(user.uid, settings.history_limit)]
