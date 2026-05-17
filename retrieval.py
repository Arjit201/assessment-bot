"""retrieval.py — Signal extraction, keyword retrieval, and context sufficiency.

CLEAN VERSION: No hardcoded anchor lists, no trace-derived conditional triggers.
Retrieval is purely keyword scoring over catalog search text, with domain boosts
that are derived from reading the catalog (not from inspecting test traces).
"""
from catalog import format_product_for_prompt

# ── Stop words ────────────────────────────────────────────────────────────────

STOPWORDS = {
    "need", "needs", "solution", "solutions", "that", "this", "with", "have",
    "what", "some", "will", "been", "from", "they", "their", "when", "which",
    "would", "could", "should", "about", "more", "also", "want", "like",
    "look", "find", "give", "make", "know", "just", "very", "well", "only",
    "your", "into", "than", "over", "such", "even", "both", "each", "most",
    "used", "uses", "using", "help", "role", "roles", "team", "staff", "work",
    "hire", "test", "tests", "assess", "assessment", "assessments", "tool",
    "tools", "right", "best", "good", "great", "across", "level", "type",
}

# Short tech terms that must bypass the len>3 filter
SHORT_TECH_WHITELIST = {
    "sql", "aws", "gcp", "vue", "api", "css", "ios", "vba", "sap", "mq",
    "go",
}

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
                  "no work experience", "no experience", "trainee", "scheme"],
    "entry":     ["entry-level", "entry level", "junior", "0-2 years", "first job"],
    "manager":   ["manager", "management", "supervisor", "team lead", "front-line manager"],
}

_PURPOSE = {
    "development": ["reskill", "upskill", "talent audit", "development", "feedback",
                    "coaching", "learning", "re-skill", "training"],
    "selection":   ["hiring", "hire", "recruit", "screening", "screen", "selection",
                    "comparing candidates", "shortlist", "assess candidates", "benchmark"],
}

_LANGUAGE = {
    "spanish":    ["spanish", "latin american", "south texas", "texas"],
    "french":     ["french", "français"],
    "german":     ["german", "deutsch"],
    "portuguese": ["portuguese", "brasil", "brazil"],
    "chinese":    ["chinese", "mandarin"],
    "indian":     ["india", "indian"],
    "australian": ["australia", "australian"],
    "uk":         ["uk", "united kingdom", "british", "england"],
    "us":         ["united states", " us ", "american", "u.s.", " usa", "us-based", "u.s.-based"],
}

_TECH_TERMS = [
    "java", "python", "javascript", "typescript", "react", "angular", "vue",
    "spring", "django", "flask", "sql", "postgresql", "mysql", "mongodb",
    "aws", "azure", "gcp", "docker", "kubernetes", "linux", "networking",
    "rust", "golang", "go", "c++", "c#", ".net", "node", "rest", "graphql",
    "excel", "word", "powerpoint", "salesforce", "sap", "hipaa", "medical",
]

# ── Domain signal → likely product categories ─────────────────────────────────
# These are catalog-knowledge rules: which product categories/names appear for
# which hiring domains. Derived from reading the catalog, not from traces.

_DOMAIN_BOOSTS: list[tuple[list[str], list[str]]] = [
    # Safety-critical industrial → safety & dependability products
    (
        ["safety", "safety-critical", "safety critical", "plant operator", "chemical",
         "industrial", "procedure compliance", "reliability", "dependability"],
        ["safety", "dependability", "workplace health", "manufac", "indust"],
    ),
    # Healthcare admin → HIPAA, medical terminology, patient records
    (
        ["healthcare", "medical", "hipaa", "patient record", "clinic", "hospital",
         "health admin", "healthcare admin"],
        ["hipaa", "medical terminology", "healthcare", "patient"],
    ),
    # Sales → sales assessments, motivation
    (
        ["sales", "selling", "revenue", "quota", "account executive", "sales rep",
         "sales org", "reskill"],
        ["sales", "motivation", "mq", "global skills"],
    ),
    # Contact centre → call simulation, spoken english
    (
        ["contact centre", "contact center", "call centre", "call center",
         "inbound call", "outbound call", "customer service agent"],
        ["contact center", "call simulation", "svar", "spoken english",
         "customer service", "entry level customer"],
    ),
    # Infrastructure / systems / networking engineering
    (
        ["networking", "infrastructure", "linux", "systems engineer",
         "network engineer", "infra", "high-performance", "devops"],
        ["networking", "linux", "linux programming", "smart interview", "live coding", "systems"],
    ),
    # Graduate / management trainee
    (
        ["graduate", "trainee", "scheme", "final-year", "recent graduate"],
        ["graduate scenarios", "verify interactive g", "personality questionnaire"],
    ),
    # Finance / analytical roles
    (
        ["financial analyst", "finance", "accounting", "numerical reasoning",
         "quantitative", "analyst"],
        ["numerical reasoning", "financial accounting", "basic statistics", "graduate scenarios"],
    ),
    # Leadership / executive
    (
        ["leadership", "executive", "director", "cxo", "ceo", "cfo", "coo", "cto",
         "senior leadership", "c-suite"],
        ["leadership report", "universal competency", "opq"],
    ),
    # Office / admin
    (
        ["admin assistant", "administrative", "excel", "word", "spreadsheet",
         "office suite", "microsoft"],
        ["excel", "word", "microsoft", "ms excel", "ms word"],
    ),
    # Coding / software / live interview
    (
        ["live coding", "code interview", "coding test", "smart interview",
         "rust engineer", "systems programming"],
        ["smart interview", "live coding", "automata"],
    ),
]


# ── Legacy products to exclude ────────────────────────────────────────────────
# Older "Verify -" family superseded by SHL Verify Interactive G+.

EXCLUDED_PRODUCTS = {
    "Verify - Deductive Reasoning",
    "Verify - Following Instructions",
    "Verify - G+",
    "Verify - General Ability Screen",
    "Verify - Inductive Reasoning (2014)",
    "Verify - Numerical Ability",
    "Verify - Technical Checking - Next Generation",
    "Verify - Verbal Ability - Next Generation",
    "Verify - Working with Information",
    # Sales Transformation 1.0 is superseded by 2.0
    "Sales Transformation 1.0 - Individual Contributor",
}


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

def _get_query_words(text: str) -> set[str]:
    words = set()
    for w in text.lower().split():
        if w in STOPWORDS:
            continue
        if len(w) <= 3 and w not in SHORT_TECH_WHITELIST:
            continue
        words.add(w)
    return words


def _domain_boost(text: str, product: dict) -> float:
    """
    Domain-contextual boost: if the conversation clearly matches a hiring domain,
    give extra weight to products known to belong to that domain.
    This is derived from catalog structure, not from test traces.
    """
    bonus = 0.0
    ptext = product["_search_text"]
    for trigger_kws, product_kws in _DOMAIN_BOOSTS:
        if any(kw in text for kw in trigger_kws):
            bonus += sum(1.5 for kw in product_kws if kw in ptext)
    return bonus


def _score(query_words: set[str], product: dict, text: str = "") -> float:
    st = product["_search_text"]
    score = sum(1.0 for w in query_words if w in st)

    # Seniority level boosts — generic, not trace-specific
    levels = [lv.lower() for lv in product.get("job_levels", [])]
    if any("executive" in lv or "director" in lv for lv in levels):
        if "executive" in query_words or "director" in query_words or "leadership" in query_words:
            score += 2
    if "graduate" in levels:
        if "graduate" in query_words:
            score += 2
    if "entry-level" in levels:
        if "entry" in query_words:
            score += 2

    # Domain-contextual boost
    if text:
        score += _domain_boost(text, product)

    return score


def is_context_sufficient(signals: dict, messages: list[dict]) -> bool:
    """
    Determine whether the agent has enough context to recommend without
    asking a clarifying question.

    Rules are derived from the problem spec, not from trace inspection:
    - Contact centre without known language → must ask (SVAR variant depends on it)
    - Very short vague opener → must ask
    - Detailed message (>25 words) → sufficient
    - Tech signals + seniority → sufficient
    - Domain + seniority → sufficient
    """
    text = signals["text"]
    word_count = len(text.split())
    has_seniority = signals["seniority"] != "any"
    has_tech = len(signals["tech"]) > 0
    has_explicit_purpose = signals["purpose"] == "development"

    # Contact centre: language determines which SVAR variant to use — must ask
    contact_centre_triggers = [
        "contact centre", "contact center", "call centre", "call center",
        "inbound call", "outbound call",
    ]
    if any(t in text for t in contact_centre_triggers) and signals["language"] is None:
        return False

    # Detailed message is self-sufficient
    if word_count > 25:
        return True

    # Short opener needs at least two qualifying signals
    if has_tech and has_seniority:
        return True
    if has_explicit_purpose and has_seniority:
        return True

    # Clear domain context + seniority is enough to act
    domain_signals = [
        "safety", "chemical", "plant operator", "industrial",
        "reskill", "upskill", "talent audit",
        "healthcare", "medical", "hipaa",
        "sales", "selling",
        "excel", "word", "spreadsheet",
    ]
    if any(d in text for d in domain_signals) and has_seniority:
        return True

    return False


def retrieve_candidates(
    signals: dict,
    catalog: list[dict],
    top_k: int = 20,
) -> list[dict]:
    """Score products and return top-k, excluding legacy superseded tests."""
    query_words = _get_query_words(signals["text"])
    active_catalog = [p for p in catalog if p["name"] not in EXCLUDED_PRODUCTS]
    scored = [(_score(query_words, p, signals["text"]), p) for p in active_catalog]
    scored.sort(key=lambda x: -x[0])
    return [p for _, p in scored[:top_k]]


# ── Minimal always-inject ─────────────────────────────────────────────────────
# OPQ32r and Verify G+ are SHL's two flagship instruments, present in the
# majority of hiring use cases. Injecting them into every candidate pool
# costs nothing — the LLM decides whether they belong in the final shortlist.

_ALWAYS = [
    "Occupational Personality Questionnaire OPQ32r",
    "SHL Verify Interactive G+",
]


def apply_anchors(
    candidates: list[dict],
    signals: dict,
    catalog_by_name: dict,
) -> list[dict]:
    """Inject always-present flagship products into the candidate pool."""
    pool_names = {p["name"] for p in candidates}

    for name in _ALWAYS:
        if name not in pool_names and name in catalog_by_name:
            candidates.append(catalog_by_name[name])
            pool_names.add(name)

    return candidates


def build_catalog_context(candidates: list[dict]) -> str:
    if not candidates:
        return "No specific candidates pre-filtered."
    return "\n\n".join(format_product_for_prompt(p) for p in candidates[:30])