from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


class ChatRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    message: str = Field(min_length=1, max_length=3000)
    request_id: str = Field(min_length=8, max_length=64, pattern=r"^[a-zA-Z0-9_-]+$")


class LoginRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    email: str = Field(min_length=3, max_length=254)
    password: str = Field(min_length=1, max_length=200)


class Plan(BaseModel):
    model_config = ConfigDict(extra="forbid")
    intents: list[Literal["lookup", "cancel", "return", "recommend", "coupon", "handoff", "policy", "greeting", "scope"]] = Field(min_length=1, max_length=4)
    search_query: str = Field(default="", max_length=600)


class Evidence(BaseModel):
    id: str
    kind: Literal["order", "product", "policy", "coupon", "ticket", "event", "clock"]
    label: str
    facts: dict


class Result(BaseModel):
    workflow: str
    status: str
    text: str
    evidence: list[Evidence] = Field(default_factory=list)
    data: dict = Field(default_factory=dict)
    actions: list[dict] = Field(default_factory=list)


class Reply(BaseModel):
    request_id: str
    text: str
    results: list[Result]
    grounded: bool
    latency_ms: float
    planner: str
    memory: dict
