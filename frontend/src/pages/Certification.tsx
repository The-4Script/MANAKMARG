import { CalendarClock, ChevronDown, Search } from "lucide-react";
import { useState, type FormEvent } from "react";
import { Link, useSearchParams } from "react-router-dom";
import { api } from "../api/client";
import type { Evidence, ListingView, SourceRollup } from "../api/types";
import { useApi } from "../api/useApi";
import { EvidenceProvider, EvidenceRefs, SourcesList } from "../components/evidence";
import { Button, Card, cx, ErrorNote, ExternalAnchor, formatDate, Id, inputClass, PageHeader, Spinner, StatusChip } from "../components/ui";
import { useI18n } from "../i18n/I18nProvider";
import { EFFECT_TONE, EFFECTS, pick } from "../i18n/domain";
import { ListingSummary } from "./Journey";

type Scheme = { scheme_id: string; name: string; short_name: string | null; official_description: string | null; conformity_mark: string | null; official_url: string | null; counts: Record<string, number> };
type Row = {
  coverage_id: number;
  scheme_id: string | null;
  product_name: string;
  category: string | null;
  section_label: string | null;
  standard_ref_raw: string | null;
  listing_status: string;
  effect: string;
  enforcement_date: string | null;
  days_to_enforcement: number | null;
};

function ListingDetail({ coverageId }: { coverageId: number }) {
  const detail = useApi((signal) => api.get<{ listing: ListingView; illustrative_items: { coverage_id: number; product_name: string }[]; evidence: Evidence[]; sources: SourceRollup[] }>(`/coverage/${coverageId}`, undefined, signal), [coverageId]);
  const { lang } = useI18n();
  if (detail.loading) return <Spinner />;
  if (detail.error) return <ErrorNote error={detail.error} />;
  if (!detail.data) return null;
  const { listing, illustrative_items } = detail.data;
  return (
    <EvidenceProvider evidence={detail.data.evidence}>
      <div className="flex justify-end">
        <EvidenceRefs ids={[listing.evidence_id, ...listing.orders.map((order) => order.evidence_id)]} />
      </div>
      <ListingSummary listing={listing} />
      {illustrative_items.length > 0 && (
        <p className="mt-3 text-xs text-slate-600">
          {lang === "hi" ? "उदाहरण उत्पाद:" : "Illustrative items:"} {illustrative_items.map((item) => item.product_name).join(", ")}
        </p>
      )}
      <Link to={`/journey?coverage_id=${listing.coverage_id}`} className="mt-3 inline-block text-sm font-medium text-ink-700 hover:underline">
        {lang === "hi" ? "इस उत्पाद की अनुपालन यात्रा →" : "Compliance journey for this listing →"}
      </Link>
    </EvidenceProvider>
  );
}

function Upcoming() {
  const { t, lang } = useI18n();
  const upcoming = useApi((signal) => api.get<{ checked_on: string; items: ListingView[]; evidence: Evidence[]; sources: SourceRollup[] }>("/qco/upcoming", undefined, signal), []);
  if (upcoming.loading) return <Spinner />;
  if (upcoming.error) return <ErrorNote error={upcoming.error} onRetry={upcoming.reload} />;
  if (!upcoming.data) return null;
  return (
    <EvidenceProvider evidence={upcoming.data.evidence}>
      <ol className="space-y-3">
        {upcoming.data.items.map((item) => (
          <li key={item.coverage_id}>
            <Card className="flex flex-wrap items-start gap-4 p-4">
              <div className={cx("grid w-24 shrink-0 place-items-center rounded-xl px-2 py-3 text-center", item.effect === "UPCOMING" ? "bg-saffron-50 text-amber-900" : "bg-slate-100 text-slate-700")}>
                <CalendarClock className="size-5" aria-hidden />
                <span className="mt-1 text-xs font-semibold">{formatDate(item.enforcement_date, lang)}</span>
              </div>
              <div className="min-w-0 flex-1">
                <p className="font-medium text-ink-900">{item.product_name}</p>
                <p className="mt-0.5 flex flex-wrap items-center gap-2 text-xs text-slate-600">
                  {item.standards.map((link) => (
                    <Id key={link.ref_raw}>{link.ref_raw}</Id>
                  ))}
                  {item.ministry_department && <span>· {item.ministry_department}</span>}
                </p>
                <p className="mt-1 text-sm">
                  {item.effect === "UPCOMING" && item.days_to_enforcement != null ? (
                    <span className="text-amber-800">{t("cert.daysLeft", { days: item.days_to_enforcement })}</span>
                  ) : (
                    <span className="text-rose-800">{t("cert.inForce")}</span>
                  )}
                </p>
              </div>
              <EvidenceRefs ids={[item.evidence_id, ...item.orders.map((order) => order.evidence_id)]} />
            </Card>
          </li>
        ))}
      </ol>
      <div className="mt-4">
        <SourcesList sources={upcoming.data.sources} />
      </div>
    </EvidenceProvider>
  );
}

export default function Certification() {
  const { t, lang } = useI18n();
  const [params, setParams] = useSearchParams();
  const tab = params.get("tab") ?? "SCHEME_I";
  const q = params.get("q") ?? "";
  const [query, setQuery] = useState(q);
  const [open, setOpen] = useState<number | null>(null);
  const [page, setPage] = useState(0);
  const schemes = useApi((signal) => api.get<{ items: Scheme[]; upcoming_counts: Record<string, number> }>("/schemes", undefined, signal), []);
  const rows = useApi((signal) => api.get<{ total: number; items: Row[] }>("/coverage", { scheme_id: tab, q, limit: 40, offset: page * 40 }, signal), [tab, q, page], tab !== "UPCOMING");
  const scheme = schemes.data?.items.find((item) => item.scheme_id === tab);

  const tabs = [...(schemes.data?.items.map((item) => ({ id: item.scheme_id, label: item.short_name ?? item.name })) ?? []), { id: "UPCOMING", label: t("cert.upcoming") }] as { id: string; label: string }[];

  const submit = (event: FormEvent) => {
    event.preventDefault();
    setPage(0);
    setParams({ tab, ...(query.trim() ? { q: query.trim() } : {}) });
  };

  return (
    <div>
      <PageHeader title={t("cert.title")} subtitle={lang === "hi" ? "BIS के ‘अनिवार्य प्रमाणन वाले उत्पाद’ पृष्ठों की सूचियाँ, स्थिति के उद्धृत आधार सहित।" : "Listings from BIS ‘Products under Compulsory Certification’ pages, each with its quoted status basis."} />
      <div className="no-print mb-4 flex flex-wrap gap-2" role="tablist">
        {tabs.map((item) => (
          <button
            key={item.id}
            role="tab"
            aria-selected={tab === item.id}
            onClick={() => {
              setPage(0);
              setOpen(null);
              setParams({ tab: item.id });
            }}
            className={cx("rounded-full px-4 py-2 text-sm font-medium", tab === item.id ? "bg-ink-800 text-white" : "bg-white text-ink-900 ring-1 ring-slate-200 hover:ring-ink-600")}
          >
            {item.label}
          </button>
        ))}
      </div>

      {tab === "UPCOMING" ? (
        <Upcoming />
      ) : (
        <>
          {scheme && (
            <Card className="mb-4 p-5">
              <h2 className="font-semibold text-ink-900">{scheme.name}</h2>
              {scheme.official_description && <p className="mt-1 text-sm text-slate-700">{scheme.official_description}</p>}
              <div className="mt-2 flex flex-wrap items-center gap-2 text-xs">
                {Object.entries(scheme.counts).map(([status, count]) => (
                  <span key={status} className="inline-flex items-center gap-1">
                    <StatusChip status={status} /> {count}
                  </span>
                ))}
                {scheme.official_url && <ExternalAnchor href={scheme.official_url}>BIS</ExternalAnchor>}
              </div>
            </Card>
          )}
          <form onSubmit={submit} className="mb-4 flex gap-3">
            <input value={query} onChange={(e) => setQuery(e.target.value)} className={inputClass} placeholder={lang === "hi" ? "उत्पाद या IS से छानें" : "Filter by product or IS"} />
            <Button type="submit">
              <Search className="size-4" aria-hidden /> {t("common.search")}
            </Button>
          </form>
          {rows.loading && <Spinner />}
          {rows.error && <ErrorNote error={rows.error} onRetry={rows.reload} />}
          {rows.data && (
            <Card className="divide-y divide-slate-100">
              {rows.data.items.map((row) => (
                <div key={row.coverage_id}>
                  <button className="flex w-full flex-wrap items-center gap-x-4 gap-y-1 px-5 py-3 text-left hover:bg-ink-50/40" onClick={() => setOpen(open === row.coverage_id ? null : row.coverage_id)} aria-expanded={open === row.coverage_id}>
                    <span className="min-w-0 flex-1 font-medium text-ink-900">{row.product_name}</span>
                    {row.standard_ref_raw && <Id>{row.standard_ref_raw}</Id>}
                    <StatusChip status={EFFECT_TONE[row.effect] ?? row.listing_status} />
                    <span className="hidden text-xs text-slate-500 md:inline">{pick(EFFECTS[row.effect], lang, row.effect)}</span>
                    <ChevronDown className={cx("size-4 text-slate-400 transition", open === row.coverage_id && "rotate-180")} aria-hidden />
                  </button>
                  {open === row.coverage_id && (
                    <div className="bg-slate-50/60 px-5 py-4">
                      <ListingDetail coverageId={row.coverage_id} />
                    </div>
                  )}
                </div>
              ))}
              <div className="flex items-center justify-between px-5 py-3 text-sm text-slate-600">
                <span>
                  {rows.data.total.toLocaleString("en-IN")} {lang === "hi" ? "सूचियाँ" : "listings"}
                </span>
                <span className="flex gap-2">
                  <Button variant="secondary" disabled={page === 0} onClick={() => setPage(page - 1)}>
                    ←
                  </Button>
                  <Button variant="secondary" disabled={(page + 1) * 40 >= rows.data.total} onClick={() => setPage(page + 1)}>
                    →
                  </Button>
                </span>
              </div>
            </Card>
          )}
        </>
      )}
    </div>
  );
}
