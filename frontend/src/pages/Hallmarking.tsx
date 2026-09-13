import { Gem, MapPin, Search } from "lucide-react";
import { useState, type FormEvent } from "react";
import { useSearchParams } from "react-router-dom";
import { api } from "../api/client";
import type { AhcSearch, AhcView, DistrictCheck } from "../api/types";
import { useApi } from "../api/useApi";
import { EvidenceProvider, EvidenceRefs, SourcesList } from "../components/evidence";
import { Button, Card, Chip, EmptyState, ErrorNote, ExternalAnchor, Field, formatDate, Id, inputClass, Notice, PageHeader, Spinner, StatusChip } from "../components/ui";
import { useI18n } from "../i18n/I18nProvider";
import { NOTES, pick, STATES_AND_UTS } from "../i18n/domain";

type Faq = { faq_id: number; question: string; answer: string; source_url: string };

function AhcCard({ ahc }: { ahc: AhcView }) {
  const { lang, t } = useI18n();
  return (
    <Card as="article" className="p-4">
      <div className="flex flex-wrap items-start justify-between gap-2">
        <div>
          <h4 className="font-semibold text-ink-900">{ahc.name}</h4>
          <p className="mt-0.5 text-xs text-slate-500">
            <Id>{ahc.recognition_no}</Id>
          </p>
        </div>
        <div className="flex flex-wrap items-center gap-2">
          <StatusChip status={ahc.effective_status} />
          <EvidenceRefs ids={ahc.evidence_ids} />
        </div>
      </div>
      <p className="mt-2 flex gap-2 text-sm text-slate-700">
        <MapPin className="mt-0.5 size-4 shrink-0 text-slate-400" aria-hidden />
        {ahc.address}
      </p>
      <div className="mt-2 flex flex-wrap items-center gap-2 text-xs text-slate-600">
        {ahc.gold && <Chip tone="amber">{lang === "hi" ? "सोना" : "Gold"}</Chip>}
        {ahc.silver && <Chip>{lang === "hi" ? "चांदी" : "Silver"}</Chip>}
        <span>
          {t("common.validUntil")}: {formatDate(ahc.validity_date, lang)}
        </span>
        {(ahc.org_phone || ahc.org_email) && <span className="break-all">· {[ahc.org_phone, ahc.org_email].filter(Boolean).join(" · ")}</span>}
      </div>
      {ahc.effective_status !== "OPERATIVE" && <p className="mt-2 text-xs text-rose-800">{ahc.reasons.join(" ")}</p>}
    </Card>
  );
}

export default function Hallmarking() {
  const { t, lang } = useI18n();
  const [params, setParams] = useSearchParams();
  const [district, setDistrict] = useState(params.get("district") ?? "");
  const [state, setState] = useState(params.get("state") ?? "");
  const [metal, setMetal] = useState("");
  const [includeInactive, setIncludeInactive] = useState(false);

  const checkParams = { district: params.get("district"), state: params.get("state") };
  const check = useApi((signal) => api.get<DistrictCheck>("/hallmarking/district-check", checkParams, signal), [params.toString()], !!checkParams.district);
  const ahcParams = { state: params.get("state"), district: params.get("district"), metal: params.get("metal"), include_inactive: params.get("inactive") === "1" };
  const ahcs = useApi((signal) => api.get<AhcSearch>("/hallmarking/ahc", { ...ahcParams, limit: 60 }, signal), [params.toString()], !!(ahcParams.state || ahcParams.district));
  const jewellers = useApi((signal) => api.get<{ url: string }>("/hallmarking/jewellers", undefined, signal), []);
  const faqs = useApi((signal) => api.get<{ items: Faq[] }>("/faq", { category: "hallmarking_mandatory", limit: 10 }, signal), []);

  const submit = (event: FormEvent) => {
    event.preventDefault();
    const next = new URLSearchParams();
    if (district.trim()) next.set("district", district.trim());
    if (state) next.set("state", state);
    if (metal) next.set("metal", metal);
    if (includeInactive) next.set("inactive", "1");
    setParams(next);
  };

  const choose = (nextDistrict: string, nextState: string) => {
    setDistrict(nextDistrict);
    setState(nextState);
    setParams({ district: nextDistrict, state: nextState });
  };

  return (
    <div className="space-y-6">
      <PageHeader title={t("hm.title")} subtitle={t("hm.districtCheck")} />
      <form onSubmit={submit} className="grid gap-3 rounded-2xl border border-slate-200 bg-white p-5 shadow-sm md:grid-cols-[1.5fr_1.5fr_1fr_auto] md:items-end">
        <Field label={t("common.district")}>
          <input className={inputClass} value={district} onChange={(e) => setDistrict(e.target.value)} placeholder="Jaipur, Gurugram, Kolkata…" />
        </Field>
        <Field label={t("common.state")}>
          <select className={inputClass} value={state} onChange={(e) => setState(e.target.value)}>
            <option value="">{t("common.any")}</option>
            {STATES_AND_UTS.map((item) => (
              <option key={item}>{item}</option>
            ))}
          </select>
        </Field>
        <Field label={lang === "hi" ? "धातु" : "Metal"}>
          <select className={inputClass} value={metal} onChange={(e) => setMetal(e.target.value)}>
            <option value="">{t("common.any")}</option>
            <option value="gold">{lang === "hi" ? "सोना" : "Gold"}</option>
            <option value="silver">{lang === "hi" ? "चांदी" : "Silver"}</option>
          </select>
        </Field>
        <Button type="submit">
          <Search className="size-4" aria-hidden /> {t("common.search")}
        </Button>
        <label className="flex items-center gap-2 text-sm text-slate-600 md:col-span-4">
          <input type="checkbox" checked={includeInactive} onChange={(e) => setIncludeInactive(e.target.checked)} className="size-4 accent-ink-800" />
          {t("hm.showInactive")}
        </label>
      </form>

      {check.loading && <Spinner />}
      {check.error && <ErrorNote error={check.error} onRetry={check.reload} />}
      {check.data && !check.loading && (
        <EvidenceProvider evidence={check.data.evidence}>
          <Card className="p-6">
            <div className="flex flex-wrap items-center gap-3">
              <Gem className="size-6 text-saffron-600" aria-hidden />
              <h2 className="text-xl font-semibold text-ink-900">
                {check.data.query_district}
                {check.data.query_state ? `, ${check.data.query_state}` : ""}
              </h2>
              <StatusChip status={check.data.status} />
            </div>
            {check.data.matches.map((match) => (
              <div key={match.district_id} className="mt-4 rounded-xl bg-ink-50/60 p-4">
                <div className="flex flex-wrap items-center justify-between gap-2">
                  <p className="font-medium text-ink-900">
                    {match.district}, {match.state}
                    {match.match_basis !== "official_name" && (
                      <span className="ml-2 text-xs font-normal text-slate-500">
                        ({lang === "hi" ? "मिलान" : "matched via"} {match.match_basis.replaceAll("_", " ")})
                      </span>
                    )}
                  </p>
                  <div className="flex items-center gap-2">
                    {check.data!.status === "AMBIGUOUS" && (
                      <Button variant="secondary" onClick={() => choose(match.district, match.state)}>
                        {lang === "hi" ? "यह चुनें" : "Choose"}
                      </Button>
                    )}
                    <EvidenceRefs ids={match.evidence_ids} />
                  </div>
                </div>
                <p className="mt-1 text-sm text-slate-700">
                  {match.phase_no
                    ? lang === "hi"
                      ? `चरण ${match.phase_no} — ${match.phase_order_date_raw ?? ""}`
                      : `Phase ${match.phase_no} — ${match.phase_order_date_raw ?? ""}`
                    : pick(NOTES.gazette_only, lang, "")}
                </p>
                {match.gazette_note && <p className="mt-1 text-xs text-slate-500">{match.gazette_note}</p>}
              </div>
            ))}
            {check.data.status === "NOT_IN_LIST" && (
              <Notice>
                {lang === "hi"
                  ? "यह ज़िला अनुक्रमित चरणवार सूची या राजपत्र अनुसूची में नहीं मिला। अनिवार्य हॉलमार्किंग केवल अधिसूचित ज़िलों में लागू होती है — BIS से पुष्टि करें।"
                  : "This district was not found in the indexed phase-wise list or Gazette annex. Mandatory hallmarking applies only in notified districts — verify with BIS."}
                {check.data.suggestions.length > 0 && (
                  <span className="mt-2 flex flex-wrap items-center gap-2">
                    {lang === "hi" ? "क्या आपका मतलब:" : "Did you mean:"}
                    {check.data.suggestions.map((item) => (
                      <button key={`${item.district}-${item.state}`} className="rounded-full bg-white px-2.5 py-0.5 ring-1 ring-amber-300 hover:ring-ink-600" onClick={() => choose(item.district, item.state)}>
                        {item.district}, {item.state}
                      </button>
                    ))}
                  </span>
                )}
              </Notice>
            )}
            {check.data.notes.map((note) => (
              <p key={note} className="mt-2 text-xs text-slate-500">
                {pick(NOTES[note], lang, note)}
              </p>
            ))}
          </Card>
          <SourcesList sources={check.data.sources} />
        </EvidenceProvider>
      )}

      <section>
        <h2 className="mb-3 text-lg font-semibold text-ink-900">{t("hm.ahcFinder")}</h2>
        {!(ahcParams.state || ahcParams.district) && <EmptyState>{lang === "hi" ? "AHC देखने के लिए ज़िला या राज्य चुनें।" : "Choose a district or state to see Assaying & Hallmarking Centres."}</EmptyState>}
        {ahcs.loading && <Spinner />}
        {ahcs.error && <ErrorNote error={ahcs.error} onRetry={ahcs.reload} />}
        {ahcs.data && !ahcs.loading && (
          <EvidenceProvider evidence={ahcs.data.evidence}>
            <div className="mb-3 flex flex-wrap items-center gap-2 text-sm text-slate-600">
              {Object.entries(ahcs.data.counts).map(([status, count]) => (
                <span key={status} className="inline-flex items-center gap-1">
                  <StatusChip status={status} /> {count}
                </span>
              ))}
              <span className="text-xs">{t("common.checkedOn", { date: formatDate(ahcs.data.checked_on, lang) })}</span>
            </div>
            <p className="mb-3 text-xs text-slate-500">
              {lang === "hi"
                ? "कोई केंद्र तभी सक्रिय दिखाया जाता है जब सूची की स्थिति “Operative” हो, वैधता बाकी हो और किसी आधिकारिक सूची में निलंबन या रद्दीकरण न हो।"
                : "A centre is shown as operative only when its listed status is “Operative”, its validity has not ended, and no official list records a suspension or cancellation."}
            </p>
            <div className="grid gap-3 lg:grid-cols-2">
              {[...ahcs.data.operative, ...ahcs.data.inactive].map((ahc) => (
                <AhcCard key={ahc.recognition_no} ahc={ahc} />
              ))}
            </div>
            {ahcs.data.operative.length === 0 && ahcs.data.inactive.length === 0 && <EmptyState>{t("common.noResults")}</EmptyState>}
          </EvidenceProvider>
        )}
      </section>

      <div className="grid gap-4 lg:grid-cols-2">
        <Card className="p-5">
          <h2 className="font-semibold text-ink-900">{t("hm.jewellers")}</h2>
          <p className="mt-2 text-sm text-slate-600">
            {t("hm.jewellersNote")} {jewellers.data && <ExternalAnchor href={jewellers.data.url}>{lang === "hi" ? "आधिकारिक रिपोर्ट" : "Official report"}</ExternalAnchor>}
          </p>
        </Card>
        <Card className="p-5">
          <h2 className="font-semibold text-ink-900">{t("hm.faqs")}</h2>
          <div className="mt-2 divide-y divide-slate-100">
            {faqs.data?.items.map((faq) => (
              <details key={faq.faq_id} className="py-2">
                <summary className="cursor-pointer text-sm font-medium text-ink-900">{faq.question}</summary>
                <p className="mt-1 whitespace-pre-line text-sm text-slate-600">{faq.answer}</p>
                <ExternalAnchor href={faq.source_url} className="mt-1 text-xs">
                  BIS FAQ
                </ExternalAnchor>
              </details>
            ))}
          </div>
        </Card>
      </div>
    </div>
  );
}
