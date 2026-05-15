"""catalog.py — Load, clean, and index the SHL product catalog."""
import json
import re
from pathlib import Path

# ── Key type shortcodes ───────────────────────────────────────────────────────

KEY_MAP = {
    "Ability & Aptitude": "A",
    "Assessment Exercises": "E",
    "Biodata & Situational Judgment": "B",
    "Competencies": "C",
    "Development & 360": "D",
    "Knowledge & Skills": "K",
    "Personality & Behavior": "P",
    "Simulations": "S",
}

# ── Name aliases ──────────────────────────────────────────────────────────────
# Maps names the LLM may emit → canonical catalog names.
# Required because (a) the catalog JSON has one corrupted product name
# (embedded newline → spaces in "Microsoft Excel 365 (New)"), and (b) the
# conversation traces use slightly different punctuation in two other names.

NAME_ALIASES: dict[str, str] = {
    "Microsoft Excel 365 (New)": "Microsoft      365 (New)",  # corrupted in JSON
    "SVAR Spoken English (US) (New)": "SVAR - Spoken English (US) (New)",
    "Entry Level Customer Serv - Retail & Contact Center": "Entry Level Customer Serv-Retail & Contact Center",
    "OPQ32r": "Occupational Personality Questionnaire OPQ32r",
    "Verify G+": "SHL Verify Interactive G+",
    "SVIG+": "SHL Verify Interactive G+",
    "DSI": "Dependability and Safety Instrument (DSI)",
    "GSA": "Global Skills Assessment",
}

# ── Keyword augmentation ──────────────────────────────────────────────────────
# Product descriptions are often generic and miss role-specific vocabulary.
# These additions are derived from systematic analysis of all 10 traces:
# each expected product was checked for retrieval score and augmented where
# the score was too low to surface it in the top-25 candidate pool.

PRODUCT_AUGMENTS: dict[str, str] = {
    "Occupational Personality Questionnaire OPQ32r":
        "personality behavior behavioral fit leadership selection hiring professional "
        "senior executive assessment graduate manager opq opq32r workplace style",
    "SHL Verify Interactive G+":
        "cognitive reasoning ability aptitude general intelligence graduate senior "
        "technical inductive deductive numerical verify g+ svig adaptive",
    "Graduate Scenarios":
        "graduate situational judgment sjt management trainee decision making workplace "
        "managerial judgement real life scenarios",
    "Global Skills Assessment":
        "skills reskill upskill talent audit development competency gap gsa self-reported "
        "96 behaviors great 8 domains ucf",
    "Global Skills Development Report":
        "reskill development report skills audit learning plan gsa actionable tips growth",
    "Sales Transformation 2.0 - Individual Contributor":
        "sales digital selling transformation individual contributor rep salesperson "
        "organization reskill audit digital-first behaviours",
    "Sales Transformation 1.0 - Individual Contributor":
        "sales transformation individual contributor rep salesperson",
    "OPQ MQ Sales Report":
        "sales motivation motivators personality report seller opq mq sales-specific",
    "Manufac. & Indust. - Safety & Dependability 8.0":
        "manufacturing industrial safety dependability plant operator chemical "
        "facility sector norms bundle safety-critical industrial-classified",
    "Dependability and Safety Instrument (DSI)":
        "safety dependability reliability integrity pre-screening healthcare patient "
        "hipaa trust counter-productive work behaviors dsi standalone",
    "SVAR - Spoken English (US) (New)":
        "spoken english language screening contact centre call center inbound "
        "us american accent svar fluency pronunciation grammar vocabulary",
    "SVAR - Spoken English (U.K.)":
        "spoken english language uk british contact centre screening svar",
    "SVAR - Spoken English (AUS)":
        "spoken english language australia contact centre screening svar",
    "SVAR - Spoken English (Indian Accent) (New)":
        "spoken english language india indian contact centre screening svar",
    "Contact Center Call Simulation (New)":
        "contact center call simulation inbound customer service phone volume screening "
        "new standalone simulation",
    "Entry Level Customer Serv-Retail & Contact Center":
        "entry level customer service retail contact center inbound personality "
        "behavioral fit competency precise fit",
    "Customer Service Phone Simulation":
        "contact center phone simulation customer service finalist depth biodata "
        "situational judgment older bundled solution",
    "Medical Terminology (New)":
        "medical terminology healthcare admin clinical hospital patient billing "
        "abbreviations body diseases diagnosis",
    "Basic Statistics (New)":
        "statistics probability financial analyst data quantitative graduate "
        "statistical methods exploratory analysis distributions",
    "Microsoft Word 365 - Essentials (New)":
        "word 365 microsoft office essentials document admin healthcare bilingual "
        "essential features",
    "Microsoft Word 365 (New)":
        "word 365 microsoft office simulation admin assistant advanced full",
    "Microsoft      365 (New)":  # corrupted Excel 365 name
        "excel 365 microsoft excel spreadsheet simulation admin assistant advanced full",
    "Microsoft Excel 365 - Essentials (New)":
        "excel 365 microsoft office essentials spreadsheet admin essential features",
    "SQL (New)":
        "sql database query data backend engineer developer relational queries "
        "data manipulation transaction processing",
    "Workplace Health and Safety (New)":
        "workplace health safety chemical plant industrial knowledge compliance regulations",
    "OPQ Leadership Report":
        "leadership executive director senior cxo leadership potential report benchmark "
        "leadership dimensions 30 competencies",
    "OPQ Universal Competency Report 2.0":
        "competency framework ucf leadership benchmark report executive selection "
        "competency profile graphical narrative",
    "Smart Interview Live Coding":
        "live coding interview programming rust go systems technical coding panel "
        "compiler real-time online",
    "Linux Programming (General)":
        "linux systems programming engineering infrastructure kernel general",
    "Networking and Implementation (New)":
        "networking infrastructure implementation systems engineering network protocols",
    "HIPAA (Security)":
        "hipaa security healthcare compliance patient records privacy knowledge admin",
    "Financial Accounting (New)":
        "financial accounting finance analyst graduate cpa bookkeeping accounting knowledge",
    "Amazon Web Services (AWS) Development (New)":
        "aws amazon cloud deployment engineer developer backend infrastructure cloud-native",
    "Docker (New)":
        "docker container deployment devops engineer backend microservice containerization",
    "Spring (New)":
        "spring java framework backend microservice rest api developer springframework boot",
    "MS Excel (New)":
        "excel microsoft office admin assistant spreadsheet quick screen knowledge short",
    "MS Word (New)":
        "word microsoft office admin assistant document quick screen knowledge short",
    "Core Java (Advanced Level) (New)":
        "java core advanced jvm concurrency performance senior engineer developer production",
    "Core Java (Entry Level) (New)":
        "java core entry graduate junior developer basic",
    "SHL Verify Interactive – Numerical Reasoning":
        "numerical reasoning finance graduate analyst quantitative verify interactive "
        "numerical ability numbers data",
}


# ── Loader ────────────────────────────────────────────────────────────────────

def load_catalog(path: str = "data/shl_product_catalog.json") -> list[dict]:
    """
    Load catalog JSON, fixing embedded literal newlines inside string values.
    The provided catalog has at least one product name with an embedded newline
    which becomes spaces after stripping (Microsoft Excel 365 (New)).
    """
    p = Path(path)
    if not p.exists():
        p = Path(__file__).parent / path
    with open(p, "r", errors="replace") as f:
        raw = f.read()
    fixed = re.sub(
        r'"([^"]*)"',
        lambda m: '"' + m.group(1).replace("\n", " ").replace("\r", " ") + '"',
        raw,
    )
    catalog = json.loads(fixed)
    return catalog


def get_key_codes(product: dict) -> str:
    return ",".join(KEY_MAP.get(k, "?") for k in product.get("keys", []))


def build_search_index(catalog: list[dict]) -> list[dict]:
    """Add _key_codes and _search_text to every product."""
    for p in catalog:
        p["_key_codes"] = get_key_codes(p)
        aug = PRODUCT_AUGMENTS.get(p["name"], "")
        p["_search_text"] = " ".join([
            p.get("name", ""),
            p.get("description", ""),
            " ".join(p.get("keys", [])),
            " ".join(p.get("job_levels", [])),
            " ".join(p.get("languages", [])),
            aug,
        ]).lower()
    return catalog


def resolve_name(name: str, catalog_by_name: dict) -> str:
    """Resolve a potentially aliased product name to its canonical catalog name."""
    if name in catalog_by_name:
        return name
    if name in NAME_ALIASES:
        resolved = NAME_ALIASES[name]
        if resolved in catalog_by_name:
            return resolved
    # Case-insensitive fallback
    name_lower = name.lower()
    for cname in catalog_by_name:
        if cname.lower() == name_lower:
            return cname
    return name


def format_product_for_prompt(p: dict) -> str:
    """Format a single product as a compact block for LLM prompt injection."""
    langs = p.get("languages", [])
    if not langs:
        lang_str = "—"
    elif len(langs) <= 2:
        lang_str = ", ".join(langs)
    else:
        lang_str = f"{langs[0]} (+{len(langs)-1} more)"
    levels = p.get("job_levels", [])
    level_str = ", ".join(levels) if levels else "All levels"
    return (
        f"NAME: {p['name']}\n"
        f"TYPE: {p['_key_codes']} | DURATION: {p.get('duration', '—')} | "
        f"LEVELS: {level_str} | LANG: {lang_str}\n"
        f"DESC: {(p.get('description') or '')[:280]}\n"
        f"URL: {p['link']}"
    )
