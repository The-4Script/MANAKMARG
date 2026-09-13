import { FlaskConical } from "lucide-react";
import { useEffect, useState, type FormEvent } from "react";
import { useSearchParams } from "react-router-dom";
import { api } from "../api/client";
import type { LabSearch } from "../api/types";
import { useApi } from "../api/useApi";
import LabCard from "../components/LabCard";
import { EvidenceProvider, SourcesList } from "../components/evidence";
import { Button, Chip, EmptyState, ErrorNote, ExternalAnchor, Field, inputClass, Notice, PageHeader, Spinner, StatusChip } from "../components/ui";
import { useI18n } from "../i18n/I18nProvider";
import { NOTES, pick, STATES_AND_UTS } from "../i18n/domain";

export default function Labs() {
  const { t, lang } = useI18n();
  const [params, setParams] = useSearchParams();
  const [form, setForm] = useState({
    ref: params.get("ref") ?? "",
    state: params.get("state") ?? "",
    district: params.get("district") ?? "",
    city: params.get("city") ?? "",
  });
  const query = { ref: params.get("ref") ?? "", state: params.get("state"), district: params.get("district"), city: params.get("city") };
  const indexed = useApi((signal) => api.get<{ items: { doc_no: string; rows: number; laboratories: number }[] }>("/labs/indexed-standards", undefined, signal), []);
  const result = useApi((signal) => api.get<LabSearch>("/labs/for-standard", query, signal), [params.toString()], !!query.ref);

  useEffect(() => {
    setForm({ ref: params.get("ref") ?? "", state: params.get("state") ?? "", district: params.get("district") ?? "", city: params.get("city") ?? "" });
  }, [params]);

  const submit = (event: FormEvent) => {
    event.preventDefault();
    const next = new URLSearchParams();
    for (const [key, value] of Object.entries(form)) if (value.trim()) next.set(key, value.trim());
    setParams(next);
  };

  const data = result.data;
  return (
    <div>
      <PageHeader title={t("labs.title")} subtitle={t("labs.subtitle")} />
      <form onSubmit={submit} className="grid gap-3 rounded-2xl border border-slate-200 bg-white p-5 shadow-sm md:grid-cols-[2fr_1.4fr_1fr_1fr_auto] md:items-end">
        <Field label="IS">
          <input className={inputClass} value={form.ref} onChange={(e) => setForm({ ...form, ref: e.target.value })} placeholder={t("labs.standardPlaceholder")} required />
        </Field>
        <Field label={t("common.state")}>
          <select className={inputClass} value={form.state} onChange={(e) => setForm({ ...form, state: e.target.value })}>
            <option value="">{t("common.any")}</option>
            {STATES_AND_UTS.map((state) => (
              <option key={state}>{state}</option>
            ))}
          </select>
        </Field>
        <Field label={t("common.district")}>
          <input className={inputClass} value={form.district} onChange={(e) => setForm({ ...form, district: e.target.value })} />
        </Field>
        <Field label={t("common.city")}>
          <input className={inputClass} value={form.city} onChange={(e) => setForm({ ...form, city: e.target.value })} />
        </Field>
        <Button type="submit">
          <FlaskConical className="size-4" aria-hidden /> {t("labs.find")}
        </Button>
      </form>

      {indexed.data && (
        <p className="mt-3 flex flex-wrap items-center gap-2 text-xs text-slate-500">
          {lang === "hi" ? "IS-वार दायरा अनुक्रमित:" : "IS-wise scope indexed for:"}
          {indexed.data.items.map((item) => (
            <button key={item.doc_no} onClick={() => setParams({ ref: `IS ${item.doc_no}`, ...(query.city ? { city: query.city } : {}) })} className="rounded-full bg-white px-2 py-0.5 ring-1 ring-slate-200 hover:ring-ink-600">
              IS {item.doc_no} · {item.laboratories}
            </button>
          ))}
        </p>
      )}

      <div className="mt-6 space-y-4">
        {result.loading && <Spinner />}
        {result.error && <ErrorNote error={result.error} onRetry={result.reload} />}
        {data && !result.loading && (
          <EvidenceProvider evidence={data.evidence}>
            <div className="flex flex-wrap items-center gap-2 text-sm text-slate-600">
              {data.designations.map((designation) => (
                <Chip key={designation} tone="indigo">
                  <span className="id-token">{designation}</span>
                </Chip>
              ))}
              {data.counts.laboratories != null && (
                <span>
                  {data.counts.laboratories} {lang === "hi" ? "प्रयोगशालाएँ" : "laboratories"} · {data.counts.rows} {lang === "hi" ? "दायरा पंक्तियाँ" : "scope rows"}
                </span>
              )}
              {Object.entries(data.counts.by_status ?? {}).map(([status, count]) => (
                <span key={status} className="inline-flex items-center gap-1">
                  <StatusChip status={status} /> {count}
                </span>
              ))}
              <span className="text-xs">{t("common.checkedOn", { date: data.checked_on })}</span>
            </div>
            {data.location_fallback && <Notice>{t("labs.fallback")}</Notice>}
            {data.notes.includes("scope_not_indexed") && (
              <Notice tone="slate">
                {t("labs.notIndexed")}{" "}
                {data.lims_search_urls.map((url) => (
                  <ExternalAnchor key={url} href={url}>
                    LIMS
                  </ExternalAnchor>
                ))}
              </Notice>
            )}
            {data.notes
              .filter((note) => note !== "scope_not_indexed")
              .map((note) => (
                <EmptyState key={note}>{pick(NOTES[note], lang, note)}</EmptyState>
              ))}
            <div className="grid gap-4 lg:grid-cols-2">
              {data.matches.map((lab) => (
                <LabCard key={lab.scope_id} lab={lab} />
              ))}
            </div>
            {data.matches.length > 0 && (
              <p className="text-xs text-slate-500">
                {lang === "hi"
                  ? "प्रयोगशाला की क्षमता केवल LIMS की IS-वार दायरा पंक्ति के अनुसार दिखाई गई है। नमूना भेजने से पहले प्रयोगशाला से पुष्टि करें।"
                  : "Capability is shown only as LIMS lists it in the IS-wise scope row. Confirm with the laboratory before sending samples."}{" "}
                {data.lims_search_urls[0] && <ExternalAnchor href={data.lims_search_urls[0]}>LIMS</ExternalAnchor>}
              </p>
            )}
            <SourcesList sources={data.sources} />
          </EvidenceProvider>
        )}
        {!query.ref && <EmptyState>{lang === "hi" ? "IS संख्या दर्ज करें, जैसे IS 2062, और वैकल्पिक रूप से स्थान।" : "Enter an IS number such as IS 2062, and optionally a location."}</EmptyState>}
      </div>
    </div>
  );
}
