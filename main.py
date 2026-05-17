"""main.py — FastAPI service: GET /health  POST /chat"""
import os
from contextlib import asynccontextmanager
from typing import Optional

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

from catalog import load_catalog, build_search_index
from retrieval import extract_signals, retrieve_candidates, apply_anchors, build_catalog_context, is_context_sufficient
from agent import build_prompt, call_llm, validate_response

# ── Global state (populated at startup) ──────────────────────────────────────

_catalog: list[dict] = []
_catalog_by_name: dict[str, dict] = {}
_catalog_by_url: dict[str, dict] = {}
_valid_urls: set[str] = set()


@asynccontextmanager
async def lifespan(app: FastAPI):
    global _catalog, _catalog_by_name, _catalog_by_url, _valid_urls

    print("[startup] Loading SHL catalog …")
    _catalog = build_search_index(load_catalog())
    _catalog_by_name = {p["name"]: p for p in _catalog}
    _catalog_by_url  = {p["link"]: p for p in _catalog}
    _valid_urls      = set(_catalog_by_url.keys())
    print(f"[startup] Catalog ready: {len(_catalog)} products, {len(_valid_urls)} URLs")
    yield
    print("[shutdown] Goodbye.")


app = FastAPI(
    title="SHL Assessment Recommender",
    version="2.0.0",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)


# ── Pydantic models ───────────────────────────────────────────────────────────

class Message(BaseModel):
    role: str
    content: str


class ChatRequest(BaseModel):
    messages: list[Message]


class Recommendation(BaseModel):
    name: str
    url: str
    test_type: str


class ChatResponse(BaseModel):
    reply: str
    recommendations: Optional[list[Recommendation]] = None
    end_of_conversation: bool = False


# ── Endpoints ─────────────────────────────────────────────────────────────────

@app.get("/health")
def health():
    return {"status": "ok"}


@app.post("/chat", response_model=ChatResponse)
async def chat(req: ChatRequest):
    # ── 1. Sanitise messages ──────────────────────────────────────────────────
    messages: list[dict] = []
    for m in req.messages:
        role = m.role.strip().lower()
        content = m.content.strip()
        if role in ("user", "assistant") and content:
            messages.append({"role": role, "content": content})

    if not messages:
        raise HTTPException(status_code=400, detail="No valid messages provided.")

    # Enforce the 8-turn cap defensively (evaluator cap is 8 total turns)
    if len(messages) > 8:
        messages = messages[-8:]

    # ── 2. Extract signals from full conversation ────────────────────────────
    signals = extract_signals(messages)

    # ── 3. Retrieve relevant catalog candidates ───────────────────────────────
    candidates = retrieve_candidates(signals, _catalog, top_k=20)
    candidates = apply_anchors(candidates, signals, _catalog_by_name)

    # ── 3b. Compute context sufficiency and prepend as hard directive ─────────
    sufficient = is_context_sufficient(signals, messages)
    status_header = (
        "CONTEXT STATUS: SUFFICIENT — you have enough context, recommend now.\n\n"
        if sufficient else
        "CONTEXT STATUS: INSUFFICIENT — ask exactly ONE clarifying question, "
        "return recommendations: null. Do not recommend yet.\n\n"
    )
    catalog_context = status_header + build_catalog_context(candidates)

    # ── 4. Build prompt and call LLM ─────────────────────────────────────────
    prompt = build_prompt(messages, catalog_context)

    try:
        raw = await call_llm(prompt)
    except Exception as e:
        print(f"[chat] LLM error: {e}")
        return ChatResponse(
            reply="I'm having connection trouble right now. Please try again.",
            recommendations=None,
            end_of_conversation=False,
        )

    # ── 5. Validate and return ────────────────────────────────────────────────
    result = validate_response(raw, _valid_urls, _catalog_by_name)

    recs: Optional[list[Recommendation]] = None
    if result["recommendations"]:
        recs = [
            Recommendation(
                name=r["name"],
                url=r["url"],
                test_type=r["test_type"],
            )
            for r in result["recommendations"]
        ]

    return ChatResponse(
        reply=result["reply"],
        recommendations=recs,
        end_of_conversation=result["end_of_conversation"],
    )


# ── Dev entry-point ───────────────────────────────────────────────────────────

if __name__ == "__main__":
    import uvicorn
    uvicorn.run("main:app", host="0.0.0.0", port=8000, reload=True)