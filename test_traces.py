"""
test_traces.py — Eval harness for all 10 public conversation traces.

Measures Recall@10 and schema compliance against a local or deployed endpoint.

Usage:
    # Start server first:
    #   uvicorn main:app --host 0.0.0.0 --port 8000
    python test_traces.py
    python test_traces.py --url https://your-deployed-service.onrender.com
"""
import argparse
import asyncio
import json

import httpx

# ── Ground truth shortlists ───────────────────────────────────────────────────
# Derived from C1–C10 traces, with catalog-canonical names.
# The evaluator uses the SAME names; mismatches here = Recall miss.

TRACES = [
    {
        "id": "C1",
        "name": "Senior Leadership — OPQ + Reports",
        "opener": "We need a solution for senior leadership.",
        "facts": [
            "The pool consists of CXOs and director-level positions — people with more than 15 years of experience.",
            "Selection — comparing candidates against a leadership benchmark.",
            "Perfect, that's what we need.",
        ],
        "expected": [
            "Occupational Personality Questionnaire OPQ32r",
            "OPQ Universal Competency Report 2.0",
            "OPQ Leadership Report",
        ],
    },
    {
        "id": "C2",
        "name": "Senior Rust Engineer — Infra",
        "opener": "I'm hiring a senior Rust engineer for high-performance networking infrastructure. What assessments should I use?",
        "facts": [
            "Yes, go ahead. Should I also add a cognitive test for this level?",
            "That works. Thanks.",
        ],
        "expected": [
            "Smart Interview Live Coding",
            "Linux Programming (General)",
            "Networking and Implementation (New)",
            "SHL Verify Interactive G+",
            "Occupational Personality Questionnaire OPQ32r",
        ],
    },
    {
        "id": "C3",
        "name": "Entry-Level Contact Centre — English US",
        "opener": "We're screening 500 entry-level contact centre agents. Inbound calls, customer service focus. What should we use?",
        "facts": [
            "English.",
            "US.",
            "Perfect — new simulation for volume, old solution for finalists. Confirmed.",
        ],
        "expected": [
            "SVAR - Spoken English (US) (New)",
            "Contact Center Call Simulation (New)",
            "Entry Level Customer Serv-Retail & Contact Center",
            "Customer Service Phone Simulation",
        ],
    },
    {
        "id": "C4",
        "name": "Graduate Financial Analysts",
        "opener": "Hiring graduate financial analysts — final-year students, no work experience. We need numerical reasoning and a finance knowledge test.",
        "facts": [
            "Good. Can you also add a situational judgement element — work-context decision making for graduates?",
            "That covers it. Numerical + Graduate Scenarios as first filter, domain tests for shortlisted candidates.",
        ],
        "expected": [
            "SHL Verify Interactive – Numerical Reasoning",
            "Financial Accounting (New)",
            "Basic Statistics (New)",
            "Graduate Scenarios",
            "Occupational Personality Questionnaire OPQ32r",
        ],
    },
    {
        "id": "C5",
        "name": "Sales Org Reskilling",
        "opener": "As part of our restructuring and annual talent audit, we need to re-skill our Sales organization. What solutions do you recommend?",
        "facts": [
            "Clear. We'll use OPQ for everyone and add MQ only where we want motivators in the Sales Report; keeping the five solutions as our audit stack.",
        ],
        "expected": [
            "Global Skills Assessment",
            "Global Skills Development Report",
            "Occupational Personality Questionnaire OPQ32r",
            "OPQ MQ Sales Report",
            "Sales Transformation 2.0 - Individual Contributor",
        ],
    },
    {
        "id": "C6",
        "name": "Chemical Plant Operators — Safety Critical",
        "opener": "We're hiring plant operators for a chemical facility. Safety is absolute top priority — reliability, procedure compliance, never cutting corners. What do you recommend?",
        "facts": [
            "We're industrial. The 8.0 bundle is the right fit. Confirmed.",
        ],
        "expected": [
            "Manufac. & Indust. - Safety & Dependability 8.0",
            "Workplace Health and Safety (New)",
        ],
    },
    {
        "id": "C7",
        "name": "Bilingual Healthcare Admin — South Texas",
        "opener": "We're hiring bilingual healthcare admin staff in South Texas — they handle patient records and need to be assessed in Spanish. HIPAA compliance is critical. What assessments work?",
        "facts": [
            "They're functionally bilingual — English fluent for written work. Go with the hybrid.",
            "Understood. Keep the shortlist as-is.",
        ],
        "expected": [
            "HIPAA (Security)",
            "Medical Terminology (New)",
            "Microsoft Word 365 - Essentials (New)",
            "Dependability and Safety Instrument (DSI)",
            "Occupational Personality Questionnaire OPQ32r",
        ],
    },
    {
        "id": "C8",
        "name": "Admin Assistants — Excel + Word",
        "opener": "I need to quickly screen admin assistants for Excel and Word daily.",
        "facts": [
            "In that case, I am OK with adding a simulation — we want to capture the capabilities.",
            "That's good.",
        ],
        "expected": [
            "Microsoft      365 (New)",   # corrupted Excel 365 name in catalog
            "Microsoft Word 365 (New)",
            "MS Excel (New)",
            "MS Word (New)",
            "Occupational Personality Questionnaire OPQ32r",
        ],
    },
    {
        "id": "C9",
        "name": "Senior Full-Stack Java Engineer",
        "opener": (
            "Here's the JD for an engineer we need to fill. "
            '"Senior Full-Stack Engineer — 5+ years across Core Java, Spring, REST API design, '
            "Angular, SQL/relational databases, AWS deployment, and Docker. Will own end-to-end "
            'microservice delivery, contribute to architectural decisions, and mentor mid-level engineers."'
        ),
        "facts": [
            "Backend-leaning. Day-one priorities are Core Java and Spring; SQL is constant. Angular is occasional — they'd review frontend PRs but not own features.",
            "Senior IC. They lead design on their own services but don't manage other engineers directly.",
            "Add AWS and Docker. Drop REST — the API design signal will already come through in Spring and the live interview.",
            "Keep Verify G+. Locking it in.",
        ],
        "expected": [
            "Core Java (Advanced Level) (New)",
            "Spring (New)",
            "SQL (New)",
            "Amazon Web Services (AWS) Development (New)",
            "Docker (New)",
            "SHL Verify Interactive G+",
            "Occupational Personality Questionnaire OPQ32r",
        ],
    },
    {
        "id": "C10",
        "name": "Graduate Management Trainee Scheme",
        "opener": "We run a graduate management trainee scheme. We need a full battery — cognitive, personality, and situational judgement. All recent graduates.",
        "facts": [
            "Drop the OPQ. Final list: Verify G+ and Graduate Scenarios.",
        ],
        "expected": [
            "SHL Verify Interactive G+",
            "Graduate Scenarios",
        ],
    },
]


# ── Scoring ───────────────────────────────────────────────────────────────────

def recall_at_10(predicted: list[str], expected: list[str]) -> float:
    if not expected:
        return 1.0
    hits = sum(1 for e in expected if e in set(predicted))
    return hits / len(expected)


def schema_ok(resp: dict) -> tuple[bool, str]:
    """Check response schema compliance."""
    if "reply" not in resp:
        return False, "missing 'reply'"
    if "end_of_conversation" not in resp:
        return False, "missing 'end_of_conversation'"
    if "recommendations" not in resp:
        return False, "missing 'recommendations'"
    recs = resp["recommendations"]
    if recs is not None:
        if not isinstance(recs, list):
            return False, "'recommendations' not a list"
        if len(recs) > 10:
            return False, f"recommendations length {len(recs)} > 10"
        for r in recs:
            for field in ("name", "url", "test_type"):
                if field not in r:
                    return False, f"recommendation missing '{field}'"
    return True, "ok"


# ── Simulator ─────────────────────────────────────────────────────────────────

async def run_trace(
    trace: dict,
    base_url: str,
    client: httpx.AsyncClient,
    verbose: bool = False,
) -> dict:
    messages = [{"role": "user", "content": trace["opener"]}]
    facts = list(trace["facts"])
    final_recs: list[str] = []
    schema_errors: list[str] = []
    turns_used = 0
    max_turns = 8

    while turns_used < max_turns:
        try:
            r = await client.post(
                f"{base_url}/chat",
                json={"messages": messages},
                timeout=30.0,
            )
            r.raise_for_status()
            resp = r.json()
        except Exception as e:
            print(f"    [HTTP ERROR] {e}")
            break

        ok, err = schema_ok(resp)
        if not ok:
            schema_errors.append(f"turn {turns_used+1}: {err}")

        reply = resp.get("reply", "")
        recs = resp.get("recommendations") or []
        eoc = resp.get("end_of_conversation", False)

        if verbose:
            print(f"    A[{turns_used+1}]: {reply[:80]}{'…' if len(reply)>80 else ''}")
            if recs:
                print(f"         recs={[r['name'][:30] for r in recs]}")

        messages.append({"role": "assistant", "content": reply})
        turns_used += 1

        if recs:
            final_recs = [r["name"] for r in recs]

        if eoc:
            break

        if turns_used >= max_turns:
            break

        # Next user turn: feed next fact, or confirm if facts exhausted
        if facts:
            user_msg = facts.pop(0)
        elif final_recs:
            user_msg = "That works, confirmed."
        else:
            user_msg = "No preference — please proceed with your best recommendation."

        if verbose:
            print(f"    U[{turns_used+1}]: {user_msg[:80]}")

        messages.append({"role": "user", "content": user_msg})
        turns_used += 1

    score = recall_at_10(final_recs, trace["expected"])
    return {
        "id": trace["id"],
        "name": trace["name"],
        "turns": turns_used,
        "recall": score,
        "got": final_recs,
        "expected": trace["expected"],
        "missing": [e for e in trace["expected"] if e not in set(final_recs)],
        "extra": [g for g in final_recs if g not in set(trace["expected"])],
        "schema_errors": schema_errors,
    }


# ── Main ──────────────────────────────────────────────────────────────────────

async def main(base_url: str, verbose: bool = False) -> None:
    print(f"\n{'═'*62}")
    print(f"  SHL Recommender — Evaluation Harness")
    print(f"  Target: {base_url}")
    print(f"{'═'*62}\n")

    async with httpx.AsyncClient() as client:
        # Health check
        try:
            h = await client.get(f"{base_url}/health", timeout=15.0)
            assert h.json().get("status") == "ok"
            print("✓ Health check passed\n")
        except Exception as e:
            print(f"✗ Health check FAILED: {e}\n  Is the server running?\n")
            return

        results = []
        for trace in TRACES:
            if verbose:
                print(f"{'─'*50}")
                print(f"  {trace['id']}: {trace['name']}")
            r = await run_trace(trace, base_url, client, verbose=verbose)
            results.append(r)

            symbol = "✓" if r["recall"] >= 1.0 else ("~" if r["recall"] >= 0.5 else "✗")
            print(
                f"{symbol} {r['id']} {r['name'][:40]:<40} "
                f"Recall={r['recall']:.2f}  Turns={r['turns']}"
            )
            if r["missing"]:
                print(f"    MISSING : {r['missing']}")
            if r["schema_errors"]:
                print(f"    SCHEMA  : {r['schema_errors']}")
            if verbose and r["extra"]:
                print(f"    EXTRA   : {r['extra']}")

    # Summary
    mean_recall = sum(r["recall"] for r in results) / len(results)
    schema_pass = sum(1 for r in results if not r["schema_errors"])
    print(f"\n{'═'*62}")
    print(f"  Mean Recall@10 : {mean_recall:.3f}")
    print(f"  Schema clean   : {schema_pass}/{len(results)}")
    print(f"\n  Per-trace:")
    for r in results:
        bar = "█" * round(r["recall"] * 10) + "░" * (10 - round(r["recall"] * 10))
        print(f"  [{bar}] {r['recall']:.2f}  {r['id']} {r['name']}")
    print(f"{'═'*62}\n")

    with open("eval_results.json", "w") as f:
        json.dump({"mean_recall": mean_recall, "traces": results}, f, indent=2)
    print("Results saved → eval_results.json")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--url", default="http://localhost:8000")
    parser.add_argument("--verbose", "-v", action="store_true")
    args = parser.parse_args()
    asyncio.run(main(args.url, args.verbose))
