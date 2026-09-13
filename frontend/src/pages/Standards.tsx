import { Library, Search } from "lucide-react";
import { useState, type FormEvent } from "react";
import { Link, useSearchParams } from "react-router-dom";
import { api } from "../api/client";
import type { Evidence, ListingView, SourceRollup } from "../api/types";
import { useApi } from "../api/useApi";
import { EvidenceProvider, EvidenceRefs, SourcesList } from "../components/evidence";
import { Button, Card, Chip, EmptyState, ErrorNote, ExternalAnchor, formatDate, Id, inputClass, PageHeader, Spinner } from "../components/ui";
import { useI18n } from "../i18n/I18nProvider";
import { EFFECTS, pick } from "../i18n/domain";
import { ListingSummary } from "./Journey";

type StandardItem = { standard_id: number; std_key: string; title: string; standard_type: string | null; publication_date: string | null; listing_status: string };
type Detail = {
  standard: StandardItem & { family_key: string; revision_label: string | null; designation_raw: string; evidence_id: string };
  versions: { std_key: string; year: number | null; publication_date: string | null; is_current: boolean }[];
  classification: { name: string; dimension: string }[];
  aliases: { raw_text: string; context: string }[];
  listings: ListingView[];
  compulsory: string;
  guidelines: { guideline_id: number; title: string; is_ref_raw: string; url: string; doc_kind: string; size_text: string | null; parse_status: string }[];
  lab_scope: { rows: number; laboratories: number };
  portal_url: string;
  evidence: Evidence[];
  sources: SourceRollup[];
};

function StandardDetail({ stdKey }: { stdKey: string }) {
  const { t, lang } = useI18n();
  const detail = useApi((signal) => api.get<Detail>("/standards/detail", { key: stdKey }, signal), [stdKey]);
  if (detail.loading) return <Spinner />;
  if (detail.error) return <ErrorNote error={detail.error} onRetry={detail.reload} />;
  const data = detail.data;
  if (!data) return null;
  const number = data.standard.std_key.match(/\d+/)?.[0];
  return (
    <EvidenceProvider evidence={data.evidence}>
      <Card className="p-6">
        <div className="flex flex-wrap items-start justify-between gap-3">
          <div>
            <h2 className="text-2xl font-semibold text-ink-900">
              <Id>{data.standard.std_key}</Id>
            </h2>
            <p className="mt-1 text-slate-700">{data.standard.title}</p>
          </div>
          <div className="flex items-center gap-2">
            <Chip tone="indigo">{pick(EFFECTS[data.compulsory], lang, data.compulsory)}</Chip>
            <EvidenceRefs ids={[data.standard.evidence_id]} />
          </div>
        </div>
        <dl className="mt-4 grid gap-3 text-sm sm:grid-cols-3">
          <div>
            <dt className="text-slate-500">{lang === "hi" ? "प्रकार" : "Type"}</dt>
            <dd>{data.standard.standard_type ?? "—"}</dd>
          </div>
          <div>
            <dt className="text-slate-500">{lang === "hi" ? "प्रकाशित" : "Published"}</dt>
            <dd>{formatDate(data.standard.publication_date, lang)}</dd>
          </div>
          <div>
            <dt className="text-slate-500">{lang === "hi" ? "संशोधन" : "Revision"}</dt>
            <dd>{data.standard.revision_label ?? "—"}</dd>
          </div>
        </dl>
        <div className="mt-4 flex flex-wrap gap-3 text-sm">
          <ExternalAnchor href={data.portal_url}>{t("standards.portal")}</ExternalAnchor>
          <Link className="text-ink-700 hover:underline" to={`/journey?std_key=${encodeURIComponent(data.standard.std_key)}`}>
            {lang === "hi" ? "अनुपालन यात्रा बनाएँ →" : "Build compliance journey →"}
          </Link>
          {data.lab_scope.rows > 0 && number && (
            <Link className="text-ink-700 hover:underline" to={`/labs?ref=IS%20${number}`}>
              {t("standards.labs")} ({data.lab_scope.laboratories}) →
            </Link>
          )}
        </div>
      </Card>

      <div className="mt-4 grid gap-4 lg:grid-cols-2">
        <Card className="p-5">
          <h3 className="font-semibold text-ink-900">{t("standards.versions")}</h3>
          <ul className="mt-2 space-y-1 text-sm">
            {data.versions.map((version) => (
              <li key={version.std_key} className="flex items-center gap-2">
                <Link to={`/standards?key=${encodeURIComponent(version.std_key)}`} className="text-ink-800 hover:underline">
                  <Id>{version.std_key}</Id>
                </Link>
                <span className="text-xs text-slate-500">{formatDate(version.publication_date, lang)}</span>
                {!version.is_current && <Chip>retired</Chip>}
              </li>
            ))}
          </ul>
          {data.classification.length > 0 && (
            <p className="mt-3 text-xs text-slate-500">
              {lang === "hi" ? "मंत्रालय निर्यात (आंशिक):" : "Ministry exports (partial):"} {data.classification.map((node) => node.name).join("; ")}
            </p>
          )}
        </Card>
        <Card className="p-5">
          <h3 className="font-semibold text-ink-900">{t("standards.manuals")}</h3>
          {data.guidelines.length ? (
            <ul className="mt-2 space-y-1 text-sm">
              {data.guidelines.map((guideline) => (
                <li key={guideline.guideline_id} className="flex flex-wrap items-center gap-2">
                  <ExternalAnchor href={guideline.url}>{guideline.title}</ExternalAnchor>
                  <Chip>{guideline.parse_status.replaceAll("_", " ")}</Chip>
                </li>
              ))}
            </ul>
          ) : (
            <p className="mt-2 text-sm text-slate-500">{t("common.notAvailable")}</p>
          )}
        </Card>
      </div>

      <section className="mt-4">
        <h3 className="mb-2 font-semibold text-ink-900">{t("standards.listings")}</h3>
        {data.listings.length ? (
          <div className="space-y-3">
            {data.listings.map((listing) => (
              <Card key={listing.coverage_id} className="p-5">
                <div className="mb-2 flex justify-end">
                  <EvidenceRefs ids={[listing.evidence_id, ...listing.orders.map((order) => order.evidence_id)]} />
                </div>
                <ListingSummary listing={listing} />
              </Card>
            ))}
          </div>
        ) : (
          <EmptyState>{pick(EFFECTS.NO_LISTING_FOUND, lang, "")}</EmptyState>
        )}
      </section>
      <div className="mt-4">
        <SourcesList sources={data.sources} />
      </div>
    </EvidenceProvider>
  );
}

export default function Standards() {
  const { t, lang } = useI18n();
  const [params, setParams] = useSearchParams();
  const [query, setQuery] = useState(params.get("q") ?? "");
  const key = params.get("key");
  const q = params.get("q") ?? "";
  const list = useApi((signal) => api.get<{ items: StandardItem[]; matched_identifiers: { ref_raw: string; kind: string; note: string }[] }>("/standards", { q, limit: 30 }, signal), [q], !key);

  const submit = (event: FormEvent) => {
    event.preventDefault();
    setParams(query.trim() ? { q: query.trim() } : {});
  };

  return (
    <div>
      <PageHeader title={t("standards.title")} subtitle={lang === "hi" ? "BIS की प्रकाशित मानक सूची (12 सितंबर 2026 निर्यात) से।" : "From the BIS published-standards list (export of 12 Sep 2026)."} />
      <form onSubmit={submit} className="mb-6 flex gap-3">
        <label className="relative flex-1">
          <span className="sr-only">{t("common.search")}</span>
          <Search className="pointer-events-none absolute left-3.5 top-1/2 size-4 -translate-y-1/2 text-slate-400" aria-hidden />
          <input value={query} onChange={(e) => setQuery(e.target.value)} placeholder={t("standards.placeholder")} className={`${inputClass} pl-10`} />
        </label>
        <Button type="submit">
          <Library className="size-4" aria-hidden /> {t("common.search")}
        </Button>
      </form>
      {key ? (
        <>
          <button onClick={() => setParams(q ? { q } : {})} className="mb-3 text-sm text-ink-700 hover:underline">
            ← {lang === "hi" ? "खोज परिणाम" : "Back to results"}
          </button>
          <StandardDetail stdKey={key} />
        </>
      ) : (
        <>
          {list.loading && <Spinner />}
          {list.error && <ErrorNote error={list.error} onRetry={list.reload} />}
          {list.data && (
            <Card className="divide-y divide-slate-100">
              {list.data.items.map((item) => (
                <Link key={item.standard_id} to={`/standards?key=${encodeURIComponent(item.std_key)}${q ? `&q=${encodeURIComponent(q)}` : ""}`} className="flex flex-wrap items-baseline gap-x-4 gap-y-1 px-5 py-3 hover:bg-ink-50/50">
                  <Id>{item.std_key}</Id>
                  <span className="min-w-0 flex-1 text-sm text-slate-700">{item.title}</span>
                  <span className="text-xs text-slate-500">{item.standard_type}</span>
                </Link>
              ))}
              {!list.data.items.length && <div className="p-5 text-sm text-slate-500">{t("common.noResults")}</div>}
            </Card>
          )}
        </>
      )}
    </div>
  );
}
