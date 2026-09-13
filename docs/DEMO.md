# Demo guide

Start the server (`python -m manakmarg serve`) and open http://127.0.0.1:8000. The Navigator shows four demo cards.
Results below were verified on the ingestion of 13 Sep 2026; counts change as official listings change.

## 1. Manufacturer compliance journey — stainless steel utensils

1. Open **Compliance Journey** with "stainless steel utensils" (or say *"steel ke bartan"* in the Assistant — the curated
   synonym is shown).
2. Show: *Stainless Steel Cookware* — **Likely applicable**, **Compulsory (listed)** under Scheme I; the product
   choices to confirm.
3. Step 2: **IS 14756:2024** (Third Revision, published 22 Nov 2024); the listing prints *IS 14756 : 2022* and the
   resolution to the published version is shown.
4. Step 3: QCOs with S.O. numbers — S.O. 3583(E) (09 Aug 2023) and later amendments — each linking to the official PDF.
5. Steps 4–6: Scheme I description and guideline documents; the parsed **Product Manual** (sample size, raw material,
   grouping) and the **Scheme of Inspection and Testing** table with page 7 reference.
6. Steps 7–8: LIMS-listed laboratories and the 10 official application steps; open any **Evidence** chip to show the
   source, retrieval date and snippet. Use **Print** for the report.

Contrast: "packaged drinking water" → **Needs verification / De-notified** (quoted basis); "pressure cooker" →
**Candidate** because two official products tie; "IS 2062" → confirmed standard published in two parts, linked to the
structural-steel listing that cites IS 2062:2011.

## 2. Document gap analysis

1. Open **Gap Analysis** → **Use labelled demo files** (requirement sheet marked *NOT an Indian Standard*, fictional
   datasheet and test report).
2. Result: 11 requirements — 7 Pass, 1 Non-conformity indication (measured wall thickness 0.47 mm < 0.50 mm),
   1 Potential gap (declared lid gap 1.8 mm > 1.5 mm), 1 Unknown (HV vs HRC), 1 Insufficient evidence (capacity).
3. Point out unit conversion (20.3 cm meets 200–205 mm; 16 kgf vs N), the preference for measured values, the quoted
   source line and page for both sides, and **End session & delete files**.

## 3. Hallmarking — Jaipur

1. Open **Hallmarking** with district *Jaipur*, state *Rajasthan*.
2. **Covered** — phase 1, dated 23 Jun 2021, confirmed by the Gazette annex (S.O. 4345(E), 03 Aug 2026).
3. AHCs: 19 operative shown; 2 suspended and 4 with expired validity counted and available with reasons via the toggle.
4. Try *Gurugram* (matched to *Gurgaon* via curated rename), *Bilaspur* (ambiguous: two states), *Jalore* (only in the
   Gazette annex → verify), *Ambalaa* (did-you-mean *Ambala*). Show the jeweller card explaining the CAPTCHA.

## 4. Laboratory search — IS 2062 near Kolkata

1. Open **Testing & Labs** with *IS 2062* and city *Kolkata*.
2. 4 laboratories / 5 scope rows, e.g. BIS Eastern Regional Laboratory (both IS 2062 (Part 2) (2026) and IS 2062 (2011)),
   with product, grade, charges, remarks and clause-wise tests.
3. Try *IS 14543* for a standard whose scope is indexed, and any other number to see the official LIMS link instead.

## Hindi

Switch **हिंदी** in the header. All pages, status chips, caveats and assistant answers switch to Hindi; IS numbers,
S.O. numbers, recognition numbers and clauses stay unchanged. Example: *"क्या राजस्थान में सोने के गहनों पर हॉलमार्किंग
अनिवार्य है?"*.

## Sources & Data Health

Show the source registry (authority, access status, reuse notes, latest run), ingestion runs, data-quality findings and
the limitations list.
