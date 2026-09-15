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
* **Product words**: what remains after removing cue words, identifiers, places and stop words (including Hindi and
  Hinglish function words such as *के लिए, कौन सा, mujhe, batao*).
* **Hindi / Hinglish aliases** (`normalize/aliases.py`): known domain words and Devanagari city names are replaced by
  the English record terms before the rules run (*स्टेनलेस स्टील के बर्तन → stainless steel utensils*,
  *हॉलमार्किंग / हालमार्किंग → hallmarking*, *जयपुर → Jaipur*, *लाइसेंस → licence*). Only listed entities are replaced;
  the question is never translated, and aliased places are still resolved against the official lists.
* **Invalid identifiers**: an IS number that mixes digits with the letters O/I/l (*IS 2O62*) is recorded as invalid and
  never read as a shorter standard (*IS 2*).
* **Unrecognised places**: an explicitly named place (*in Timbuktu*, *Gotham district*) that no list resolves is kept,
  so the answer can say it was not recognised instead of silently searching everywhere.

Text normalisation keeps letters, digits and combining marks of every script, so Devanagari words stay whole.

## Routing — `reasoning/routing.py`

`route_query` sends each question to exactly one answer flow; the first rule that applies wins and the route, with
its reason, is returned in the API response:

| Route | When |
|---|---|
| `invalid_identifier` | a malformed IS number and no valid one |
| `ahc` / `hallmarking` | an AHC recognition number, or hallmarking cues (centre/assaying words → `ahc`) |
| `gap_analysis` | *datasheet, compare my, check my specification …* |
| `upcoming_qco` | *upcoming, new QCOs …* |
| `lab_testing` | laboratory cues, or testing words with an IS number and a place (unless it is a multi-part product question) |
| `scheme_i` / `scheme_ii` / `scheme_iv` / `scheme_x` | a named scheme (*Scheme IV, ISI mark scheme, registration scheme*) |
| `certification` | licence/process cues without a product |
| `unknown_location` | an unrecognised place and nothing else to answer |
| `product_standard` | an IS number; words found in the listed-product vocabulary; or a standard/status/tests question about other product words |
| `qco_mandatory` | compulsory-certification cues without a product (answered from the official overview page) |
| `general` | other BIS questions, or any question whose every word appears in an official FAQ |
| `out_of_scope` | everything else — no record is used |

Because process, scheme and general questions never reach product search, they cannot show unrelated standards. When a
product has no compulsory listing, a published standard is shown only if its title contains every product word.

## Retrieval — `search/`

| Layer | Role |
|---|---|
| `resolvers.py` | Deterministic IS resolution with explicit kinds (see [COMPLIANCE_LOGIC](COMPLIANCE_LOGIC.md)). |
| `fts_search.py` | FTS5 BM25 per table with column weights. User text becomes quoted terms (no FTS syntax injection); light plural folding and prefix terms; records containing all terms rank before records containing any. |
| `vectors.py` | Corpus-trained LSA: TF-IDF over words (1–2-grams) and character 3–5-grams, TruncatedSVD (256 dimensions) for corpora of 200+ documents, cosine similarity. Indexes for listings, standards and FAQs are saved under `data/indexes/`. |
| `synonyms.json` | Curated matching aids (e.g. *bartan / बर्तन → stainless steel utensils*, *pankha / पंखा → ceiling fans*). Shown as "matched via synonym"; never evidence. |
| `hybrid.py` | Candidate listings from identifiers, BM25 and vectors; score = 0.30·BM25 (normalised) + 0.20·cosine + 0.35·token coverage + 0.10·exact name + 0.05·listing prior + 0.30·standard-title match (+1 when linked to a named standard). The standard-title match applies when the subject of a cited standard's title (the part before its first " - ") is exactly the user's product phrase — *structural steel* → IS 2062 "Structural Steel - Part 1 - …" rather than the narrower "Structural Steel (Ordinary Quality)". Vector-only neighbours sharing no query word are discarded. |

**Entity constraints** (from the benchmark in September 2026: *PVC pipes* led with "PVC sandal", *copper wire* with PVC
insulated cables). When query understanding names a product and/or a material, each candidate listing is checked:

| Flag | Meaning | Effect |
|---|---|---|
| `product_mismatch` | the named product is neither in the listing name nor reached through a synonym for it | not offered as a listing |
| `product_as_modifier` | the product word only modifies another noun (*Chain **Pipe** Wrenches*) | not offered |
| `material_conflict` | the listing names a different material and not the requested one | not offered |
| `accessory_of_product` | the product appears only in the "for …" clause (*Rubber Gaskets for Pressure Cookers*) | ranked lower |

Literal query words also outrank curated-synonym expansions (weight 0.2). When every candidate is excluded, the answer
says that no compulsory listing matched instead of presenting a material-only match.

**HSN lookup** (`search/hsn.py`) is separate from BIS retrieval: exact code → the codes filed under it; product words →
FTS5 over the verbatim descriptions, keeping only descriptions that contain every word and ranking the words in the
user's order and shorter, more specific descriptions first. HSN results appear in their own section and never change a
BIS headline, status or caveat.

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
