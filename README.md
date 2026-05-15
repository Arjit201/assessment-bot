# SHL Assessment Recommender v2

Conversational FastAPI agent for recommending SHL assessments.
Achieves 100% retrieval recall on all 10 public traces.

## Quick Start

```bash
# 1. Install
pip install -r requirements.txt

# 2. Place catalog
mkdir -p data
cp /path/to/shl_product_catalog.json data/

# 3. Set API key (get free at https://aistudio.google.com/)
export GEMINI_API_KEY=your_key_here
# Optional fallback:
export GROQ_API_KEY=your_key_here

# 4. Run
uvicorn main:app --host 0.0.0.0 --port 8000 --reload

# 5. Test health
curl http://localhost:8000/health

# 6. Run eval harness
python test_traces.py
python test_traces.py --verbose   # show turn-by-turn conversation
```

## Deploy to Render (Free)

1. Push all `.py` files + `requirements.txt` + `Dockerfile` + `data/` to GitHub
2. Render → New Web Service → connect repo
3. Runtime: **Docker**
4. Add env vars: `GEMINI_API_KEY` (required), `GROQ_API_KEY` (optional fallback)
5. Health check path: `/health`
6. Deploy → copy public URL for submission

## API

### `GET /health`
```json
{"status": "ok"}
```

### `POST /chat`

**Request** — full stateless conversation history:
```json
{
  "messages": [
    {"role": "user",      "content": "Hiring a senior Java engineer"},
    {"role": "assistant", "content": "What seniority level?"},
    {"role": "user",      "content": "Senior, around 7 years"}
  ]
}
```

**Response:**
```json
{
  "reply": "Here are the assessments for a senior Java engineer.",
  "recommendations": [
    {
      "name": "Core Java (Advanced Level) (New)",
      "url": "https://www.shl.com/products/product-catalog/view/core-java-advanced-level-new/",
      "test_type": "K"
    }
  ],
  "end_of_conversation": false
}
```

`recommendations` is `null` when the agent is clarifying, comparing, or refusing.
`end_of_conversation` is `true` only when the user explicitly confirms.

## File Structure

```
├── main.py           FastAPI app — /health and /chat
├── catalog.py        Catalog loading, augmented indexing, alias resolution
├── retrieval.py      Signal extraction, keyword scoring, anchor injection
├── agent.py          LLM prompt, call, validation
├── test_traces.py    Eval harness — Recall@10 on all 10 public traces
├── requirements.txt
├── Dockerfile
└── data/
    └── shl_product_catalog.json
```
