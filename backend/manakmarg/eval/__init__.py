"""Question-understanding evaluation against the real database (`python -m manakmarg eval-queries`).

``queries.json`` holds questions in the ways people actually ask them — Hindi, Hinglish, other Indian languages,
speech-to-text slips, plain English and off-topic text — with the flow each must reach and the IS numbers an answer
must name. Run it after changing understanding, routing, the lexicon or ranking; add a case whenever a misread
phrasing is reported, so it can never regress unnoticed. Cases marked ``needs_model`` are scored only with a Groq key
(``--with-model``); without one they are reported as skipped.
"""

import json
from dataclasses import dataclass
from datetime import date
from pathlib import Path

from sqlalchemy.engine import Connection

from manakmarg.core.config import Settings

QUERIES_PATH = Path(__file__).with_name("queries.json")


@dataclass(frozen=True)
class CaseResult:
    query: str
    passed: bool
    skipped: bool
    route: str | None
    expected_route: str
    headline: str
    problem: str | None


def load_cases(path: Path = QUERIES_PATH) -> list[dict]:
    return json.loads(path.read_text(encoding="utf-8"))["cases"]


def _answer_text(response) -> str:
    first = response.sections[0].items if response.sections else ()
    return " ".join([response.headline, *(item.text for item in first)])


def run_eval(conn: Connection, settings: Settings, *, with_model: bool, today: date | None = None, cases: list[dict] | None = None) -> list[CaseResult]:
    from manakmarg.reasoning.assistant import answer
    from manakmarg.reasoning.intents import Gazetteer

    local = settings.model_copy(update={"groq_api_key": settings.groq_api_key if with_model else None})
    gazetteer = Gazetteer.load(conn)
    results = []
    for case in cases if cases is not None else load_cases():
        query, expected_route = case["query"], case["route"]
        if case.get("needs_model") and not (with_model and settings.groq_api_key):
            results.append(CaseResult(query, False, True, None, expected_route, "", "needs --with-model and a Groq key"))
            continue
        response = answer(conn, query, lang="auto", today=today, gazetteer=gazetteer, settings=local)
        problem = None
        if response.route.category != expected_route:
            problem = f"route {response.route.category!r} ({response.route.reason}), expected {expected_route!r}"
        elif case.get("any_is") and not any(f"IS {number}" in _answer_text(response) for number in case["any_is"]):
            problem = f"none of {', '.join('IS ' + number for number in case['any_is'])} in the answer"
        results.append(CaseResult(query, problem is None, False, response.route.category, expected_route, response.headline, problem))
    return results


def summary(results: list[CaseResult]) -> dict:
    scored = [result for result in results if not result.skipped]
    passed = sum(result.passed for result in scored)
    return {
        "passed": passed,
        "scored": len(scored),
        "skipped": len(results) - len(scored),
        "accuracy": round(passed / len(scored), 3) if scored else None,
        "failures": [{"query": r.query, "problem": r.problem, "headline": r.headline[:200]} for r in scored if not r.passed],
    }
