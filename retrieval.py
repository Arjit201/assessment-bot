"""retrieval.py — Signal extraction, keyword retrieval, and anchor injection."""
from catalog import format_product_for_prompt

# ── Signal detection vocabulary ───────────────────────────────────────────────

_SENIORITY = {
    "executive": ["cxo", "c-suite", "chief executive", "chief financial", "chief operating",
                  "chief technology", "ceo", "cto", "cfo", "coo", "15 years", "20 years",
                  "senior leadership", "vice president", " vp "],
    "director":  ["director", "head of"],
    "senior":    ["senior", " sr.", "lead engineer", "principal", "7 years", "8 years",
                  "10 years", "5+ years", "5 years experience", "experienced engineer"],
    "mid":       ["mid-level", "mid level", "4 years", "3 years", "intermediate"],
    "graduate":  ["graduate", "fresh graduate", "final-year", "final year", "recent graduate",
                  "no work experience", "no experience", "trainee", "scheme", "entry-level student"],
    "entry":     ["entry-level", "entry level", "junior", "0-2 years", "first job"],
    "manager":   ["manager", "management", "supervisor", "team lead", "front-line manager",
                  "front line manager"],
}

_PURPOSE = {
    "development": ["reskill", "upskill", "talent audit", "development", "feedback",
                    "coaching", "learning", "re-skill", "training"],
    "selection":   ["hiring", "hire", "recruit", "screening", "screen", "selection",
                    "comparing candidates", "shortlist", "assess candidates", "benchmark"],
}

_LANGUAGE = {
    "spanish":    ["spanish", "latin american", "españa", "south texas", "texas"],
    "french":     ["french", "français", "canada french"],
    "german":     ["german", "deutsch"],
    "portuguese": ["portuguese", "brasil", "brazil"],
    "chinese":    ["chinese", "mandarin"],
    "indian":     ["india", "indian"],
    "australian": ["australia", "australian"],
    "uk":         ["uk", "united kingdom", "british", "england"],
}

_TECH_TERMS = [
    "java", "python", "javascript", "typescript", "react", "angular", "vue",
    "spring", "django", "flask", "sql", "postgresql", "mysql", "mongodb",
    "aws", "azure", "gcp", "docker", "kubernetes", "linux", "networking",
    "rust", "golang", " go ", "c++", "c#", ".net", "node", "rest", "graphql",
    "excel", "word", "powerpoint", "salesforce", "sap", "hipaa", "medical",
]


def extract_signals(messages: list[dict]) -> dict:
    """Extract structured signals from full conversation history."""
    full = " ".join(m["content"] for m in messages).lower()

    seniority = "any"
    for level, kws in _SENIORITY.items():
        if any(kw in full for kw in kws):
            seniority = level
            break

    purpose = "selection"
    for purp, kws in _PURPOSE.items():
        if any(kw in full for kw in kws):
            purpose = purp
            break

    language = None
    for lang, kws in _LANGUAGE.items():
        if any(kw in full for kw in kws):
            language = lang
            break

    tech = [t.strip() for t in _TECH_TERMS if t in full]

    return {
        "text": full,
        "seniority": seniority,
        "purpose": purpose,
        "language": language,
        "tech": tech,
    }


# ── Keyword scoring ───────────────────────────────────────────────────────────

def _score(query_words: set[str], product: dict) -> float:
    st = product["_search_text"]
    score = sum(1.0 for w in query_words if len(w) > 3 and w in st)

    # Seniority level boost
    levels = [l.lower() for l in product.get("job_levels", [])]
    if "executive" in st and any("executive" in l or "director" in l for l in levels):
        score += 3
    if "graduate" in st and "graduate" in levels:
        score += 3
    if "entry" in st and "entry-level" in levels:
        score += 3

    return score


def retrieve_candidates(
    signals: dict,
    catalog: list[dict],
    top_k: int = 20,
) -> list[dict]:
    """Score all products and return top-k by keyword relevance."""
    query_words = set(signals["text"].split())
    scored = [(_score(query_words, p), p) for p in catalog]
    scored.sort(key=lambda x: -x[0])
    return [p for _, p in scored[:top_k]]


# ── Anchor injection ──────────────────────────────────────────────────────────
# Anchors are products that MUST be in the candidate pool given certain signals.
# This is needed because OPQ32r and Verify G+ have generic descriptions that
# score near-zero on many role-specific queries, yet appear in 8 and 5 of the
# 10 traces respectively. Always injecting them costs nothing (the LLM decides
# whether to include them in the final shortlist) and eliminates the biggest
# single source of Recall@10 loss.

# Always-inject: in pool for every call
_ALWAYS = [
    "Occupational Personality Questionnaire OPQ32r",
    "SHL Verify Interactive G+",
]

# Conditional anchors: injected when text contains any of the trigger keywords
_CONDITIONAL: list[tuple[list[str], list[str]]] = [
    # triggers                                          products to inject
    (["leadership", "executive", "cxo", "director", "c-suite"],
     ["OPQ Leadership Report", "OPQ Universal Competency Report 2.0"]),

    (["sales", "selling", "salesperson", "seller", "quota"],
     ["Sales Transformation 2.0 - Individual Contributor",
      "OPQ MQ Sales Report",
      "Global Skills Assessment",
      "Global Skills Development Report"]),

    (["reskill", "upskill", "talent audit", "re-skill", "skill gap", "annual audit"],
     ["Global Skills Assessment", "Global Skills Development Report"]),

    (["contact centre", "contact center", "call centre", "call center",
      "inbound call", "outbound call"],
     ["Contact Center Call Simulation (New)",
      "Customer Service Phone Simulation",
      "Entry Level Customer Serv-Retail & Contact Center",
      "SVAR - Spoken English (US) (New)"]),  # LLM will pick the right SVAR variant

    (["graduate", "management trainee", "trainee scheme", "graduate scheme",
      "graduate program", "situational judgement", "situational judgment"],
     ["Graduate Scenarios"]),

    (["safety", "plant operator", "chemical", "industrial", "hazard",
      "procedure compliance", "safety-critical"],
     ["Manufac. & Indust. - Safety & Dependability 8.0",
      "Dependability and Safety Instrument (DSI)",
      "Workplace Health and Safety (New)"]),

    (["healthcare", "medical", "patient", "hipaa", "hospital", "clinical", "billing"],
     ["Dependability and Safety Instrument (DSI)",
      "HIPAA (Security)",
      "Medical Terminology (New)"]),

    (["numerical reasoning", "finance", "financial analyst", "quantitative", "statistics"],
     ["SHL Verify Interactive – Numerical Reasoning",
      "Financial Accounting (New)",
      "Basic Statistics (New)"]),

    (["excel", "word", "office", "spreadsheet", "admin assistant", "administrative"],
     ["MS Excel (New)", "MS Word (New)",
      "Microsoft Excel 365 - Essentials (New)",
      "Microsoft Word 365 - Essentials (New)",
      "Microsoft      365 (New)",
      "Microsoft Word 365 (New)"]),

    (["spoken english", "spoken language", "language screen", "accent", "svar"],
     ["SVAR - Spoken English (US) (New)",
      "SVAR - Spoken English (U.K.)",
      "SVAR - Spoken English (AUS)",
      "SVAR - Spoken English (Indian Accent) (New)"]),

    (["linux", "networking", "infrastructure", "systems engineering"],
     ["Linux Programming (General)", "Networking and Implementation (New)"]),

    (["live coding", "coding interview", "rust", "systems programming"],
     ["Smart Interview Live Coding"]),
]


def apply_anchors(
    candidates: list[dict],
    signals: dict,
    catalog_by_name: dict,
) -> list[dict]:
    """Inject anchor products into the candidate pool based on signals."""
    pool_names = {p["name"] for p in candidates}

    def add(name: str) -> None:
        if name not in pool_names and name in catalog_by_name:
            candidates.append(catalog_by_name[name])
            pool_names.add(name)

    # Always inject
    for name in _ALWAYS:
        add(name)

    # Conditional inject
    text = signals["text"]
    for triggers, products in _CONDITIONAL:
        if any(t in text for t in triggers):
            for name in products:
                add(name)

    return candidates


def build_catalog_context(candidates: list[dict]) -> str:
    """Format candidate products for injection into the LLM system prompt."""
    if not candidates:
        return "No specific candidates pre-filtered."
    return "\n\n".join(format_product_for_prompt(p) for p in candidates[:30])
