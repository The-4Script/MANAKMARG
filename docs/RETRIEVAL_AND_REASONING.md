# Retrieval and reasoning

## Query understanding — `reasoning/intents.py`

Transparent rules produce a `QueryUnderstanding`:

* **Intents** by cue phrases in English and Hindi, in priority order: gap analysis, hallmarking, laboratories, upcoming
  QCOs, tests, certification process, compulsory status, applicable standard; product compliance when product words or
  an IS number remain; otherwise a general question.
* **Identifiers**: IS designations (a bare number is read as an IS number only in a lab or standard context), AHC
  recognition numbers (`CRO/RAHC/R-110002`), S.O. numbers.
* **Places**: states and UTs (names, capitalised abbreviations such as UP or MP, Hindi names); districts and cities from
  a gazetteer built from official records (hallmarking districts with aliases, laboratory cities). A district shared by
  two states leaves the state open.
* **Product words**: what remains after removing cue words, identifiers, places and stop words.

Text normalisation keeps letters, digits and combining marks of every script, so Devanagari words stay whole.

## Retrieval — `search/`

| Layer | Role |
|---|---|
| `resolvers.py` | Deterministic IS resolution with explicit kinds (see [COMPLIANCE_LOGIC](COMPLIANCE_LOGIC.md)). |
| `fts_search.py` | FTS5 BM25 per table with column weights. User text becomes quoted terms (no FTS syntax injection); light plural folding and prefix terms; records containing all terms rank before records containing any. |
| `vectors.py` | Corpus-trained LSA: TF-IDF over words (1–2-grams) and character 3–5-grams, TruncatedSVD (256 dimensions) for corpora of 200+ documents, cosine similarity. Indexes for listings, standards and FAQs are saved under `data/indexes/`. |
| `synonyms.json` | Curated matching aids (e.g. *bartan / बर्तन → stainless steel utensils*, *pankha / पंखा → ceiling fans*). Shown as "matched via synonym"; never evidence. |
| `hybrid.py` | Candidate listings from identifiers, BM25 and vectors; score = 0.30·BM25 (normalised) + 0.20·cosine + 0.35·token coverage + 0.10·exact name + 0.05·listing prior (+1 when linked to a named standard). Vector-only neighbours sharing no query word are discarded. |

Scores only order candidates. The **token coverage** (share of the user's product words found in the official product
name, category or product category) is reported and feeds the applicability label thresholds.

## Reasoning services — `reasoning/`

| Service | Output |
|---|---|
| `applicability.assess` | Label, compulsory effect, listings with standards, orders and quoted status basis, candidates, identifiers, caveats |
| `journey.build_journey` | Eight evidence-backed steps and next actions |
| `labs.find_labs` | LIMS scope matches with status, location match, tests and exclusions |
| `hallmarking.check_district`, `find_ahcs` | District coverage with Gazette cross-check; AHCs with computed operability and reasons |
| `assistant.answer` | Headline, status, sections of cited items, caveats, next actions, links and follow-ups in EN or HI |

## Evidence — `reasoning/evidence.py`

Each record used becomes `Evidence {id, kind, title, snippet ≤ 300 chars, source_id, source_name, authority, url,
locator, retrieved_at, page, clause, record_id}`; the same record cited twice keeps one id. Items from MANAK MARG's
cross-checks carry authority `derived`. Responses include a per-source roll-up with retrieval dates and as-of labels.
API and reasoning tests assert that every cited id resolves to an evidence item.

## Wording and language — `reasoning/i18n.py`

Answers are composed from EN/HI templates filled with fields from the records. IS numbers, S.O./G.S.R. numbers,
recognition numbers, clauses and ISO dates are inserted verbatim. The UI strings and domain wording (steps, caveats,
notes, next actions) are also bilingual.

## Optional LLM

The design reserves an optional Claude narrative behind guardrails (identifier whitelist from the evidence, citations
limited to provided evidence ids, fallback to templates). It is not enabled in this build; the product is complete
without it and never lets an LLM decide requirements or status.
