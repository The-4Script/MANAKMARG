import { AlertTriangle, CheckCircle2, CircleDashed, Printer, Route } from "lucide-react";
import { useEffect, useState, type FormEvent, type ReactNode } from "react";
import { Link, useSearchParams } from "react-router-dom";
import { api } from "../api/client";
import type { Journey as JourneyData, JourneyStep, LabMatch, ListingView } from "../api/types";
import { useApi } from "../api/useApi";
import LabCard from "../components/LabCard";
import { EvidenceProvider, EvidenceRefs, SourcesList } from "../components/evidence";
import { Button, Card, Chip, cx, EmptyState, ErrorNote, ExternalAnchor, Field, formatDate, Id, inputClass, Notice, PageHeader, Spinner, StatusChip } from "../components/ui";
import { useI18n } from "../i18n/I18nProvider";
import { ACTIONS, CAVEATS, EFFECT_TONE, EFFECTS, NOTES, pick, STATES_AND_UTS, STEP_TITLES } from "../i18n/domain";

const STATE_ICON = {
  ok: <CheckCircle2 className="size-6 text-emerald-600" aria-hidden />,
  attention: <AlertTriangle className="size-6 text-amber-500" aria-hidden />,
  missing: <CircleDashed className="size-6 text-slate-400" aria-hidden />,
};

function Row({ label, children }: { label: string; children: ReactNode }) {
  return (
    <div className="grid gap-1 py-1.5 text-sm sm:grid-cols-[11rem_1fr]">
      <dt className="text-slate-500">{label}</dt>
      <dd className="text-slate-800">{children}</dd>
    </div>
  );
}

export function ListingSummary({ listing }: { listing: ListingView }) {
  const { lang } = useI18n();
  return (
    <div className="space-y-2">
      <div className="flex flex-wrap items-center gap-2">
        <span className="font-semibold text-ink-900">{listing.product_name}</span>
        <StatusChip status={EFFECT_TONE[listing.effect] ?? listing.effect} />
        <Chip>{pick(EFFECTS[listing.effect], lang, listing.effect)}</Chip>
      </div>
      <dl>
        <Row label={lang === "hi" ? "योजना" : "Scheme"}>{listing.scheme_name ?? "—"}</Row>
        {listing.parent_product_name && <Row label={lang === "hi" ? "मुख्य प्रविष्टि" : "Listed under"}>{listing.parent_product_name}</Row>}
        {listing.category && <Row label={lang === "hi" ? "श्रेणी" : "Category"}>{listing.category}</Row>}
        <Row label={lang === "hi" ? "मानक (सूची में)" : "Standard (as listed)"}>
          {listing.standards.map((link) => (
            <span key={`${link.ref_raw}-${link.role}`} className="mr-3 inline-flex items-center gap-1">
              <Id>{link.ref_raw}</Id>
              {link.std_key && link.std_key !== link.ref_raw && <span className="text-xs text-slate-500">→ {link.std_key}</span>}
            </span>
          ))}
        </Row>
        {listing.enforcement_date && (
          <Row label={lang === "hi" ? "लागू तिथि" : "Enforcement date"}>
            {formatDate(listing.enforcement_date, lang)}
            {listing.days_to_enforcement != null && listing.days_to_enforcement > 0 && (
              <span className="ml-2 text-amber-800">({lang === "hi" ? `${listing.days_to_enforcement} दिन शेष` : `${listing.days_to_enforcement} days to go`})</span>
            )}
          </Row>
        )}
        {listing.ministry_department && <Row label={lang === "hi" ? "मंत्रालय / विभाग" : "Ministry / department"}>{listing.ministry_department}</Row>}
        {listing.essential_requirement && <Row label={lang === "hi" ? "आवश्यक अपेक्षा" : "Essential requirement"}>{listing.essential_requirement}</Row>}
        {listing.specific_requirement && <Row label={lang === "hi" ? "विशिष्ट अपेक्षा" : "Specific requirement"}>{listing.specific_requirement}</Row>}
      </dl>
      {listing.status_basis && <blockquote className="border-l-2 border-saffron-500 pl-3 text-sm text-slate-700">{listing.status_basis}</blockquote>}
      {listing.orders.length > 0 && (
        <div>
          <h4 className="mb-1 text-sm font-medium text-slate-700">{lang === "hi" ? "आदेश और अधिसूचनाएँ" : "Orders & notifications"}</h4>
          <ul className="space-y-1 text-sm">
            {listing.orders.map((order) => (
              <li key={order.order_id} className="flex flex-wrap items-center gap-2">
                <Chip>{order.kind === "qco" ? "QCO" : order.kind.replaceAll("_", " ")}</Chip>
                <ExternalAnchor href={order.url}>{order.title}</ExternalAnchor>
                {(order.so_number || order.gsr_number) && <Id>{order.so_number ?? order.gsr_number}</Id>}
                {order.order_date && <span className="text-xs text-slate-500">{formatDate(order.order_date, lang)}</span>}
              </li>
            ))}
          </ul>
        </div>
      )}
      {listing.page_url && (
        <ExternalAnchor href={listing.page_url} className="text-sm">
          {lang === "hi" ? "आधिकारिक BIS सूची पृष्ठ" : "Official BIS listing page"}
        </ExternalAnchor>
      )}
    </div>
  );
}

function StepBody({ step, onChoose }: { step: JourneyStep; onChoose: (coverageId: number) => void }) {
  const { lang, t } = useI18n();
  const data = step.data;
  switch (step.key) {
    case "product":
      return (
        <div className="space-y-3 text-sm">
          <div className="flex flex-wrap items-center gap-2">
            <StatusChip status={data.label} />
            {data.synonyms_used?.length > 0 && (
              <span className="text-xs text-slate-500">
                {t("common.matchedVia")}: {[...new Set((data.synonyms_used as [string, string][]).map(([term]) => term))].join(", ")}
              </span>
            )}
          </div>
          {data.candidates?.length > 0 && (
            <div>
              <p className="mb-2 font-medium text-slate-700">{t("journey.confirmProduct")}</p>
              <div className="flex flex-wrap gap-2">
                {data.candidates.map((candidate: { coverage_id: number; product_name: string; listing_status: string; token_coverage: number }) => (
                  <button key={candidate.coverage_id} onClick={() => onChoose(candidate.coverage_id)} className="rounded-xl border border-slate-200 bg-white px-3 py-2 text-left hover:border-ink-600">
                    <span className="block font-medium text-ink-900">{candidate.product_name}</span>
                    <span className="mt-1 flex items-center gap-2 text-xs text-slate-500">
                      <StatusChip status={candidate.listing_status} /> {Math.round(candidate.token_coverage * 100)}% {lang === "hi" ? "शब्द मेल" : "word match"}
                    </span>
                  </button>
                ))}
              </div>
            </div>
          )}
        </div>
      );
    case "standards":
      return (
        <div className="space-y-4">
          {data.standards?.map((standard: { std_key: string; title: string; standard_type: string | null; publication_date: string | null; versions: { std_key: string; year: number }[]; classification: { name: string }[]; portal_url: string }) => (
            <div key={standard.std_key}>
              <Link to={`/standards?key=${encodeURIComponent(standard.std_key)}`} className="font-semibold text-ink-800 hover:underline">
                <Id>{standard.std_key}</Id>
              </Link>
              <p className="text-sm text-slate-700">{standard.title}</p>
              <dl className="mt-1">
                {standard.standard_type && <Row label={lang === "hi" ? "मानक का प्रकार" : "Type of standard"}>{standard.standard_type}</Row>}
                <Row label={lang === "hi" ? "प्रकाशन तिथि" : "Published"}>{formatDate(standard.publication_date, lang)}</Row>
                {standard.versions.length > 1 && (
                  <Row label={t("standards.versions")}>
                    {standard.versions.map((version) => (
                      <Id key={version.std_key}>{version.std_key} </Id>
                    ))}
                  </Row>
                )}
                {standard.classification.length > 0 && <Row label={lang === "hi" ? "मंत्रालय (आंशिक)" : "Ministry (partial)"}>{standard.classification.map((node) => node.name).join("; ")}</Row>}
              </dl>
              <ExternalAnchor href={standard.portal_url} className="mt-1 text-sm">
                {t("standards.portal")}
              </ExternalAnchor>
            </div>
          ))}
        </div>
      );
    case "compulsory_status":
      return (
        <div className="space-y-3">
          <div className="flex flex-wrap items-center gap-2 text-sm">
            <StatusChip status={data.label} />
            <Chip tone="indigo">{pick(EFFECTS[data.compulsory], lang, data.compulsory)}</Chip>
          </div>
          {data.listing && <ListingSummary listing={data.listing} />}
          {data.other_listings?.length > 0 && (
            <details className="text-sm">
              <summary className="cursor-pointer text-ink-700">{lang === "hi" ? "अन्य मिलान सूचियाँ" : "Other matching listings"} ({data.other_listings.length})</summary>
              <ul className="mt-2 space-y-1">
                {(data.other_listings as ListingView[]).map((listing) => (
                  <li key={listing.coverage_id} className="flex flex-wrap items-center gap-2">
                    <button className="text-left text-ink-800 hover:underline" onClick={() => onChoose(listing.coverage_id)}>
                      {listing.product_name}
                    </button>
                    <Chip>{pick(EFFECTS[listing.effect], lang, listing.effect)}</Chip>
                  </li>
                ))}
              </ul>
            </details>
          )}
        </div>
      );
    case "scheme":
      return data.name ? (
        <div className="space-y-2 text-sm">
          <p className="font-semibold text-ink-900">{data.name}</p>
          {data.official_description && <p className="text-slate-700">{data.official_description}</p>}
          {data.conformity_mark && <p className="text-slate-600">{data.conformity_mark}</p>}
          {data.documents?.length > 0 && (
            <ul className="grid gap-1 sm:grid-cols-2">
              {data.documents.map((document: { title: string; url: string; size_text: string | null }) => (
                <li key={document.url}>
                  <ExternalAnchor href={document.url}>{document.title}</ExternalAnchor> {document.size_text && <span className="text-xs text-slate-500">({document.size_text})</span>}
                </li>
              ))}
            </ul>
          )}
        </div>
      ) : null;
    case "product_manual":
      return (
        <div className="space-y-3 text-sm">
          {data.manuals?.map((manual: { guideline_id: number; title: string; is_ref_raw: string; url: string; parse_status: string; summary: Record<string, string>; sections: { section_key: string; heading: string | null; page_start: number }[] }) => (
            <div key={manual.guideline_id} className="rounded-xl bg-slate-50 p-3">
              <div className="flex flex-wrap items-center gap-2">
                <ExternalAnchor href={manual.url}>{manual.title}</ExternalAnchor>
                <Id>{manual.is_ref_raw}</Id>
                <Chip tone={manual.parse_status === "parsed" ? "green" : manual.parse_status === "access_denied" ? "red" : "slate"}>{manual.parse_status.replaceAll("_", " ")}</Chip>
              </div>
              {manual.summary && Object.keys(manual.summary).length > 0 && (
                <dl className="mt-2">
                  {(["sampling_guidelines", "raw_material", "grouping_guidelines", "sample_size", "tests_per_day", "scope_of_licence"] as const)
                    .filter((key) => manual.summary[key])
                    .map((key) => (
                      <Row key={key} label={key.replaceAll("_", " ")}>
                        <span className="whitespace-pre-line">{manual.summary[key]}</span>
                      </Row>
                    ))}
                </dl>
              )}
              {manual.sections.length > 0 && (
                <p className="mt-2 text-xs text-slate-500">
                  {manual.sections.map((section) => `${section.heading ?? section.section_key} (p. ${section.page_start})`).join(" · ")}
                </p>
              )}
            </div>
          ))}
        </div>
      );
    case "tests":
      if (data.source === "product_manual") {
        return (
          <div className="space-y-3 text-sm">
            <p className="text-slate-600">
              {lang === "hi" ? "निरीक्षण और परीक्षण योजना —" : "Scheme of Inspection and Testing —"} <ExternalAnchor href={data.manual_url}>{data.manual_title}</ExternalAnchor>
              {data.sit_page && ` (p. ${data.sit_page})`}
            </p>
            {data.sit_rows?.length > 0 && (
              <div className="overflow-x-auto rounded-xl border border-slate-200">
                <table className="min-w-full text-left text-xs">
                  <thead className="bg-slate-50 text-slate-600">
                    <tr>
                      {(lang === "hi" ? ["खंड", "अपेक्षा", "परीक्षण विधि खंड", "नमूने", "आवृत्ति", "टिप्पणी"] : ["Clause", "Requirement", "Test method clause", "Samples", "Frequency", "Remarks"]).map((heading) => (
                        <th key={heading} className="px-3 py-2 font-medium">
                          {heading}
                        </th>
                      ))}
                    </tr>
                  </thead>
                  <tbody className="divide-y divide-slate-100">
                    {data.sit_rows.map((row: Record<string, string | boolean | null>, index: number) => (
                      <tr key={index} className="align-top">
                        <td className="px-3 py-2 font-mono">{row.clause}</td>
                        <td className="px-3 py-2">{row.requirement}</td>
                        <td className="px-3 py-2 font-mono">{row.test_method_clause}</td>
                        <td className="px-3 py-2">{row.samples}</td>
                        <td className="px-3 py-2">
                          {row.frequency}
                          {row.merged_from_previous && <span className="ml-1 text-slate-400" title="merged cell in the PDF">↑</span>}
                        </td>
                        <td className="px-3 py-2 text-slate-600">{row.remarks}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            )}
            {data.test_equipment?.length > 0 && (
              <details>
                <summary className="cursor-pointer text-ink-700">{lang === "hi" ? "परीक्षण उपकरण" : "Test equipment"} ({data.test_equipment.length})</summary>
                <ul className="mt-2 grid gap-1 sm:grid-cols-2">
                  {data.test_equipment.map((test: { sl: string; test: string; clauses: string[]; equipment: string[] }) => (
                    <li key={test.sl} className="rounded bg-slate-50 px-2 py-1">
                      <strong>{test.test}</strong> {test.clauses.length > 0 && <span className="font-mono text-xs">Cl. {test.clauses.join(", ")}</span>}
                      <span className="block text-xs text-slate-600">{test.equipment.join("; ")}</span>
                    </li>
                  ))}
                </ul>
              </details>
            )}
          </div>
        );
      }
      if (data.source === "lims_scope") {
        return (
          <div className="text-sm">
            <p className="text-slate-600">
              {data.lab_name} · <Id>{data.is_ref_raw}</Id>
            </p>
            <ul className="mt-2 grid gap-1 sm:grid-cols-2">
              {data.tests.map((test: string, index: number) => (
                <li key={index} className="rounded bg-slate-50 px-2 py-1 text-xs">
                  {test}
                </li>
              ))}
            </ul>
          </div>
        );
      }
      return null;
    case "labs":
      return (
        <div className="space-y-3">
          {data.matches?.length > 0 ? (
            <div className="grid gap-3 lg:grid-cols-2">
              {(data.matches as LabMatch[]).slice(0, 4).map((lab) => (
                <LabCard key={lab.scope_id} lab={lab} compact />
              ))}
            </div>
          ) : null}
          <div className="flex flex-wrap gap-3 text-sm">
            {data.indexed_doc_numbers?.length > 0 && (
              <Link className="font-medium text-ink-700 hover:underline" to={`/labs?ref=IS%20${data.indexed_doc_numbers[0]}${data.location?.city ? `&city=${encodeURIComponent(data.location.city)}` : ""}`}>
                {lang === "hi" ? "सभी लैब देखें →" : "See all laboratories →"}
              </Link>
            )}
            {data.lims_search_urls?.map((url: string) => (
              <ExternalAnchor key={url} href={url}>
                LIMS
              </ExternalAnchor>
            ))}
          </div>
        </div>
      );
    case "application":
      return (
        <ol className="space-y-2 text-sm">
          {data.steps?.map((item: { step_label: string; text: string; link_url: string | null; link_label: string | null }, index: number) => (
            <li key={index} className="flex gap-3">
              <span className="grid size-6 shrink-0 place-items-center rounded-full bg-ink-50 text-xs font-semibold text-ink-800">{item.step_label}</span>
              <span className="text-slate-700">
                {item.text} {item.link_url && <ExternalAnchor href={item.link_url}>{item.link_label ?? "Link"}</ExternalAnchor>}
              </span>
            </li>
          ))}
        </ol>
      );
    default:
      return null;
  }
}

export default function Journey() {
  const { t, lang } = useI18n();
  const [params, setParams] = useSearchParams();
  const [form, setForm] = useState({ text: params.get("text") ?? params.get("std_key") ?? "", state: params.get("state") ?? "", city: params.get("city") ?? "" });
  useEffect(() => {
    setForm({ text: params.get("text") ?? params.get("std_key") ?? "", state: params.get("state") ?? "", city: params.get("city") ?? "" });
  }, [params]);

  const body = {
    text: params.get("text") || null,
    std_key: params.get("std_key") || null,
    coverage_id: params.get("coverage_id") ? Number(params.get("coverage_id")) : null,
    state: params.get("state") || null,
    city: params.get("city") || null,
  };
  const enabled = !!(body.text || body.std_key || body.coverage_id);
  const journey = useApi((signal) => api.post<JourneyData>("/journey", body, signal), [params.toString()], enabled);

  const submit = (event: FormEvent) => {
    event.preventDefault();
    const next = new URLSearchParams();
    const value = form.text.trim();
    if (!value) return;
    next.set(/^\s*(IS|SP)\b|^\d{2,5}\b/i.test(value) ? "std_key" : "text", value);
    if (form.state) next.set("state", form.state);
    if (form.city.trim()) next.set("city", form.city.trim());
    setParams(next);
  };

  const choose = (coverageId: number) => {
    const next = new URLSearchParams(params);
    next.set("coverage_id", String(coverageId));
    setParams(next);
  };

  const data = journey.data;
  return (
    <div>
      <PageHeader title={t("journey.title")} subtitle={t("journey.subtitle")}>
        {data && (
          <Button variant="secondary" className="no-print" onClick={() => window.print()}>
            <Printer className="size-4" aria-hidden /> {t("common.print")}
          </Button>
        )}
      </PageHeader>

      <form onSubmit={submit} className="no-print grid gap-3 rounded-2xl border border-slate-200 bg-white p-5 shadow-sm md:grid-cols-[2fr_1.2fr_1fr_auto] md:items-end">
        <Field label={lang === "hi" ? "उत्पाद / IS" : "Product / IS"}>
          <input className={inputClass} value={form.text} onChange={(e) => setForm({ ...form, text: e.target.value })} placeholder={t("journey.productPlaceholder")} required />
        </Field>
        <Field label={t("common.state")}>
          <select className={inputClass} value={form.state} onChange={(e) => setForm({ ...form, state: e.target.value })}>
            <option value="">{t("common.any")}</option>
            {STATES_AND_UTS.map((state) => (
              <option key={state}>{state}</option>
            ))}
          </select>
        </Field>
        <Field label={t("common.city")}>
          <input className={inputClass} value={form.city} onChange={(e) => setForm({ ...form, city: e.target.value })} />
        </Field>
        <Button type="submit">
          <Route className="size-4" aria-hidden /> {t("journey.build")}
        </Button>
      </form>

      <div className="mt-6">
        {!enabled && <EmptyState>{lang === "hi" ? "शुरू करने के लिए उत्पाद का नाम या IS संख्या दर्ज करें।" : "Enter a product name or IS number to start."}</EmptyState>}
        {journey.loading && <Spinner />}
        {journey.error && <ErrorNote error={journey.error} onRetry={journey.reload} />}
        {data && !journey.loading && (
          <EvidenceProvider evidence={data.evidence}>
            <Card className="mb-6 p-6">
              <div className="flex flex-wrap items-center gap-3">
                <h2 className="text-xl font-semibold text-ink-900">{data.selected?.product_name ?? (body.text || body.std_key)}</h2>
                <StatusChip status={data.assessment.label} />
                <Chip tone="indigo">{pick(EFFECTS[data.assessment.compulsory], lang, data.assessment.compulsory)}</Chip>
                <span className="ml-auto text-xs text-slate-500">{t("common.checkedOn", { date: formatDate(data.checked_on, lang) })}</span>
              </div>
              {data.next_actions.length > 0 && (
                <div className="mt-4">
                  <h3 className="text-sm font-semibold text-slate-700">{t("common.nextSteps")}</h3>
                  <ol className="mt-2 grid gap-2 md:grid-cols-2">
                    {data.next_actions.map((action, index) => (
                      <li key={index} className="flex gap-2 rounded-xl bg-saffron-50 px-3 py-2 text-sm text-amber-950">
                        <span className="font-semibold">{index + 1}.</span>
                        <span>
                          {pick(ACTIONS[action.code], lang, action.code, action as Record<string, unknown>)} {action.url && <ExternalAnchor href={action.url}>{lang === "hi" ? "खोलें" : "Open"}</ExternalAnchor>}
                        </span>
                      </li>
                    ))}
                  </ol>
                </div>
              )}
            </Card>

            <ol className="relative space-y-4 before:absolute before:bottom-4 before:left-[1.6rem] before:top-4 before:w-px before:bg-slate-200">
              {data.steps.map((step, index) => (
                <li key={step.key} className="relative flex gap-4">
                  <div className="z-10 grid size-[3.25rem] shrink-0 place-items-center rounded-full border border-slate-200 bg-white">{STATE_ICON[step.state]}</div>
                  <Card className={cx("min-w-0 flex-1 p-5", step.state === "missing" && "bg-slate-50/70")}>
                    <div className="mb-3 flex flex-wrap items-center justify-between gap-2">
                      <h3 className="font-semibold text-ink-900">
                        <span className="mr-2 text-slate-400">{index + 1}</span>
                        {pick(STEP_TITLES[step.key], lang, step.key)}
                      </h3>
                      <EvidenceRefs ids={step.evidence_ids} />
                    </div>
                    {step.state === "missing" && !Object.keys(step.data).length ? <p className="text-sm text-slate-500">{t("journey.stepMissing")}</p> : <StepBody step={step} onChoose={choose} />}
                    {step.notes.map((note) => (
                      <p key={note} className="mt-2 text-xs text-amber-800">
                        {pick(NOTES[note], lang, note)}
                      </p>
                    ))}
                  </Card>
                </li>
              ))}
            </ol>

            {data.assessment.caveats.length > 0 && (
              <div className="mt-6">
                <Notice>
                  <strong>{t("common.caveats")}:</strong>
                  <ul className="mt-1 list-disc space-y-1 pl-5">
                    {data.assessment.caveats.map((code) => (
                      <li key={code}>{pick(CAVEATS[code], lang, code)}</li>
                    ))}
                  </ul>
                </Notice>
              </div>
            )}
            <div className="mt-6">
              <SourcesList sources={data.sources} />
            </div>
          </EvidenceProvider>
        )}
      </div>
    </div>
  );
}
