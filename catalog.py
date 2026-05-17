"""catalog.py — Load, clean, and index the SHL product catalog.

CLEAN VERSION: No trace-derived keyword augmentation.
Only contains:
- Data integrity fixes (encoding corruption, catalog JSON bugs)
- LLM output normalisation aliases (punctuation/encoding variants any LLM might emit)
- Generic shorthand aliases (OPQ32r, Verify G+, DSI, GSA)
"""
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
# KEPT: encoding/punctuation corruption that any LLM will produce regardless
#       of training data — these are data-integrity fixes, not trace fixes.

NAME_ALIASES: dict[str, str] = {
    # Catalog JSON corruption: Excel 365 has an embedded newline in the name
    "Microsoft Excel 365 (New)": "Microsoft      365 (New)",

    # SVAR punctuation variants (LLMs drop the dash universally)
    "SVAR Spoken English (US) (New)":            "SVAR - Spoken English (US) (New)",
    "SVAR Spoken English (US)":                  "SVAR - Spoken English (US) (New)",
    "SVAR Spoken English (UK)":                  "SVAR - Spoken English (U.K.)",
    "SVAR Spoken English (AUS)":                 "SVAR - Spoken English (AUS)",
    "SVAR Spoken English (Indian Accent) (New)": "SVAR - Spoken English (Indian Accent) (New)",
    "SVAR Spoken English (Indian Accent)":       "SVAR - Spoken English (Indian Accent) (New)",

    # Contact centre dash variant
    "Entry Level Customer Serv - Retail & Contact Center":
        "Entry Level Customer Serv-Retail & Contact Center",

    # Em-dash encoding corruption — U+2013 gets mangled by most LLMs.
    # All variants map TO the canonical unicode en-dash form.
    "SHL Verify Interactive - Numerical Reasoning":
        "SHL Verify Interactive \u2013 Numerical Reasoning",
    # UTF-8 mojibake of U+2013 (â€" = 0xE2 0x80 0x93 misread as latin-1)
    "SHL Verify Interactive \u00e2\u20ac\u201c Numerical Reasoning":
        "SHL Verify Interactive \u2013 Numerical Reasoning",
    # Em-dash variant
    "SHL Verify Interactive \u2014 Numerical Reasoning":
        "SHL Verify Interactive \u2013 Numerical Reasoning",
    # Double-hyphen
    "SHL Verify Interactive -- Numerical Reasoning":
        "SHL Verify Interactive \u2013 Numerical Reasoning",
    # No dash at all
    "SHL Verify Interactive Numerical Reasoning":
        "SHL Verify Interactive \u2013 Numerical Reasoning",
    # Truncated form: when LLM emits U+201C (curly quote) inside the name,
    # JSON parser clips the string at that char, leaving just the ASCII prefix.
    # Map the truncated prefix directly to the canonical name.
    "SHL Verify Interactive ":
        "SHL Verify Interactive \u2013 Numerical Reasoning",
    # Mojibake form: UTF-8 bytes of U+2013 misread as latin-1 → â€" (U+00E2 U+20AC U+201C)
    # The last character U+201C looks like a quote in some editors — use escapes to be safe.
    "SHL Verify Interactive \u00e2\u20ac\u201c Numerical Reasoning":
        "SHL Verify Interactive \u2013 Numerical Reasoning",

    # OPQ report version: LLMs sometimes say "1.0" — always canonical is 2.0
    "OPQ Universal Competency Report 1.0":
        "OPQ Universal Competency Report 2.0",
    "OPQ Universal Competency Report":
        "OPQ Universal Competency Report 2.0",

    # Common shorthand any user or LLM would naturally use
    "OPQ32r":    "Occupational Personality Questionnaire OPQ32r",
    "OPQ 32r":   "Occupational Personality Questionnaire OPQ32r",
    "Verify G+": "SHL Verify Interactive G+",
    "DSI":       "Dependability and Safety Instrument (DSI)",
    "GSA":       "Global Skills Assessment",

    # MS Office product shorthand variants
    "MS Excel":         "MS Excel (New)",
    "MS Word":          "MS Word (New)",
    "MS Excel New":     "MS Excel (New)",
    "MS Word New":      "MS Word (New)",
    "Microsoft Excel":  "MS Excel (New)",
    "Microsoft Word":   "MS Word (New)",

    # AWS shorthand
    "AWS Development (New)":              "Amazon Web Services (AWS) Development (New)",
    "Amazon Web Services Development (New)": "Amazon Web Services (AWS) Development (New)",
    "AWS (New)":                          "Amazon Web Services (AWS) Development (New)",

    # Smart Interview variants
    "Smart Interview — Live Coding":   "Smart Interview Live Coding",
    "Smart Interview - Live Coding":   "Smart Interview Live Coding",

    # Sales Transformation variants
    "Sales Transformation 2.0":        "Sales Transformation 2.0 - Individual Contributor",
    "Sales Transformation IC":         "Sales Transformation 2.0 - Individual Contributor",

    # Safety bundle
    "Manufac. & Indust. Safety & Dependability 8.0":
        "Manufac. & Indust. - Safety & Dependability 8.0",
    "Manufacturing Safety 8.0":
        "Manufac. & Indust. - Safety & Dependability 8.0",

    # C3 FIX: "Customer Service Phone Solution" is a different catalog product
    # from "Customer Service Phone Simulation". The Simulation is the correct
    # product for contact centre batteries. Redirect Solution -> Simulation.
    "Customer Service Phone Solution": "Customer Service Phone Simulation",

    # Sales Transformation: always prefer 2.0 over 1.0
    "Sales Transformation 1.0 - Individual Contributor":
        "Sales Transformation 2.0 - Individual Contributor",
    "Sales Transformation Report 2.0 - Individual Contributor":
        "Sales Transformation 2.0 - Individual Contributor",
    "Sales Transformation Report 2.0 - Sales Manager":
        "Sales Transformation 2.0 - Individual Contributor",
}


# ── Loader ────────────────────────────────────────────────────────────────────

def load_catalog(path: str = "data/shl_product_catalog.json") -> list[dict]:
    """Load catalog JSON, fixing embedded literal newlines in string values."""
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
    return json.loads(fixed)


def get_key_codes(product: dict) -> str:
    return ",".join(KEY_MAP.get(k, "?") for k in product.get("keys", []))


def build_search_index(catalog: list[dict]) -> list[dict]:
    """Add _key_codes and _search_text to every product. No augmentation."""
    for p in catalog:
        p["_key_codes"] = get_key_codes(p)
        # Search text is purely what the catalog says — no injected synonyms
        p["_search_text"] = " ".join([
            p.get("name", ""),
            p.get("description", ""),
            " ".join(p.get("keys", [])),
            " ".join(p.get("job_levels", [])),
            " ".join(p.get("languages", [])),
        ]).lower()
    return catalog


def _normalize_mojibake(name: str) -> str:
    """
    Normalize LLM JSON encoding artifacts where UTF-8 multi-byte sequences
    are emitted as individual unicode codepoints. Handles all observed
    variants of the en-dash corruption (U+2013 bytes E2 80 93 misread
    in different ways by different JSON parsers/LLMs).
    Applied before every name lookup so any product with special characters
    is handled generically, not just Numerical Reasoning.
    """
    # U+2013 EN DASH — all observed mojibake variants
    en_dash_variants = [
        "\u00e2\u20ac\u201c",  # â€" : U+00E2 U+20AC U+201C
        "\u00e2\u0080\u0093",  # â\x80\x93 : raw UTF-8 bytes as codepoints
        "\u00e2\u20ac\u0093",  # mixed variant
        "\u00e2\u0080\u201c",  # another mixed variant
    ]
    for bad in en_dash_variants:
        if bad in name:
            name = name.replace(bad, "\u2013")
    # U+2014 EM DASH variants
    em_dash_variants = [
        "\u00e2\u0080\u0094",
        "\u00e2\u20ac\u201d",
    ]
    for bad in em_dash_variants:
        if bad in name:
            name = name.replace(bad, "\u2014")
    return name


def resolve_name(name: str, catalog_by_name: dict) -> str:
    """Resolve corrupted/aliased product name to canonical catalog name."""
    # Step 0: fix encoding artifacts before any lookup
    name = _normalize_mojibake(name)

    # Direct hit
    if name in catalog_by_name:
        return name

    # Alias map lookup
    if name in NAME_ALIASES:
        resolved = NAME_ALIASES[name]
        if resolved in catalog_by_name:
            return resolved

    # Case-insensitive fallback
    name_lower = name.lower()
    for cname in catalog_by_name:
        if cname.lower() == name_lower:
            return cname

    # Normalize all dash variants (en-dash, em-dash, hyphen) and retry
    def _norm_dashes(s: str) -> str:
        return re.sub(r'[\u2013\u2014\u2012\-]+', '-', s).lower()

    name_normalized = _norm_dashes(name)
    for cname in catalog_by_name:
        if _norm_dashes(cname) == name_normalized:
            return cname

    # Strip trailing version qualifiers and retry (e.g. "OPQ Universal Competency Report 1.0")
    version_stripped = re.sub(r'\s+\d+\.\d+\s*$', '', name).strip()
    if version_stripped != name:
        result = resolve_name(version_stripped, catalog_by_name)
        if result in catalog_by_name:
            return result

    # Fuzzy prefix match: the LLM JSON string can be truncated when it emits a
    # character (e.g. U+201C curly-quote) that a JSON parser treats as a closing quote.
    # If the ASCII-only portion of the input is a prefix of exactly one catalog name
    # (min 12 chars to avoid false positives), resolve to that name.
    # Catches e.g. truncated "SHL Verify Interactive " -> full en-dash name.
    def _ascii_only(s: str) -> str:
        return re.sub(r'[^\x20-\x7e]+', ' ', s).lower().strip()

    name_ascii = _ascii_only(name)
    if len(name_ascii) >= 12:
        matches = [
            cname for cname in catalog_by_name
            if _ascii_only(cname).startswith(name_ascii)
        ]
        if len(matches) == 1:
            return matches[0]

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