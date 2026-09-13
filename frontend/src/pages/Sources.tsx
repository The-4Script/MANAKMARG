import { useState } from "react";
import { api } from "../api/client";
import type { Meta } from "../api/types";
import { useApi } from "../api/useApi";
import { AuthorityChip } from "../components/evidence";
import { Card, Chip, cx, ErrorNote, ExternalAnchor, formatDate, PageHeader, Spinner, StatusChip } from "../components/ui";
import { useI18n } from "../i18n/I18nProvider";

type SourceItem = {
  source_id: string;
  name: string;
  publisher: string;
  url: string;
  source_type: string;
  purpose: string;
  ingestion_method: string;
  authority: string;
  access_status: string;
  copyright_notes: string;
  access_notes: string | null;
  as_of_label: string | null;
  latest_run: { status: string; completed_at: string | null; records_seen: number; inserted: number; updated: number; unchanged: number; retired: number; rejected: number } | null;
};
type RunItem = { run_id: number; source_id: string; status: string; started_at: string; completed_at: string | null; records_seen: number; inserted: number; updated: number; unchanged: number; retired: number; rejected: number; notes: string | null; error_count: number };
type Finding = { check: string; severity: string; count: number; examples: string[]; note: string };

const ACCESS_TONE: Record<string, "green" | "amber" | "red" | "slate"> = { ok: "green", partial: "amber", captcha_blocked: "red", access_denied: "red", not_used: "slate" };

export default function Sources() {
  const { t, lang } = useI18n();
  const [tab, setTab] = useState<"registry" | "runs" | "quality" | "limitations">("registry");
  const sources = useApi((signal) => api.get<{ items: SourceItem[] }>("/sources", undefined, signal), [], tab === "registry");
  const runs = useApi((signal) => api.get<{ items: RunItem[] }>("/ingestion-runs", { limit: 150 }, signal), [], tab === "runs");
  const quality = useApi((signal) => api.get<{ checked_on: string; findings: Finding[] }>("/data-quality", undefined, signal), [], tab === "quality");
  const meta = useApi((signal) => api.get<Meta>("/meta", undefined, signal), [], tab === "limitations");

  const tabs = [
    ["registry", t("sources.registry")],
    ["runs", t("sources.runs")],
    ["quality", t("sources.quality")],
    ["limitations", t("sources.limitations")],
  ] as const;

  return (
    <div>
      <PageHeader title={t("sources.title")} subtitle={lang === "hi" ? "हर रिकॉर्ड अपने स्रोत, रन और प्राप्ति समय तक खोजा जा सकता है।" : "Every record traces back to its source, ingestion run and retrieval time."} />
      <div className="mb-4 flex flex-wrap gap-2" role="tablist">
        {tabs.map(([id, label]) => (
          <button key={id} role="tab" aria-selected={tab === id} onClick={() => setTab(id)} className={cx("rounded-full px-4 py-2 text-sm font-medium", tab === id ? "bg-ink-800 text-white" : "bg-white text-ink-900 ring-1 ring-slate-200")}>
            {label}
          </button>
        ))}
      </div>

      {tab === "registry" && (
        <>
          {sources.loading && <Spinner />}
          {sources.error && <ErrorNote error={sources.error} onRetry={sources.reload} />}
          <div className="grid gap-3 lg:grid-cols-2">
            {sources.data?.items.map((source) => (
              <Card key={source.source_id} as="article" className="p-5">
                <div className="flex flex-wrap items-center gap-2">
                  <AuthorityChip authority={source.authority} />
                  <Chip tone={ACCESS_TONE[source.access_status] ?? "slate"}>{source.access_status.replaceAll("_", " ")}</Chip>
                  {source.latest_run && <StatusChip status={source.latest_run.status === "success" ? "VALID" : "NEEDS_VERIFICATION"} />}
                </div>
                <h3 className="mt-2 font-semibold text-ink-900">{source.url.startsWith("http") ? <ExternalAnchor href={source.url}>{source.name}</ExternalAnchor> : source.name}</h3>
                <p className="mt-1 text-sm text-slate-700">{source.purpose}</p>
                <p className="mt-2 text-xs text-slate-500">{source.ingestion_method}</p>
                {source.access_notes && <p className="mt-1 text-xs text-amber-800">{source.access_notes}</p>}
                {source.latest_run && (
                  <p className="mt-2 text-xs text-slate-500">
                    {formatDate(source.latest_run.completed_at, lang)} · {source.latest_run.records_seen.toLocaleString("en-IN")} {lang === "hi" ? "रिकॉर्ड" : "records"} · +{source.latest_run.inserted} ~{source.latest_run.updated} ={source.latest_run.unchanged} −{source.latest_run.retired}
                  </p>
                )}
                <details className="mt-2 text-xs text-slate-500">
                  <summary className="cursor-pointer">{lang === "hi" ? "पुनः उपयोग और पहुँच" : "Reuse & access"}</summary>
                  <p className="mt-1">{source.copyright_notes}</p>
                </details>
              </Card>
            ))}
          </div>
        </>
      )}

      {tab === "runs" && (
        <Card className="overflow-x-auto">
          {runs.loading && <Spinner />}
          {runs.error && <ErrorNote error={runs.error} onRetry={runs.reload} />}
          {runs.data && (
            <table className="min-w-full text-left text-sm">
              <thead className="bg-slate-50 text-xs text-slate-600">
                <tr>
                  {["Run", "Source", "Status", "Completed", "Seen", "+", "~", "=", "−", "Rejected", "Notes"].map((heading) => (
                    <th key={heading} className="px-3 py-2 font-medium">
                      {heading}
                    </th>
                  ))}
                </tr>
              </thead>
              <tbody className="divide-y divide-slate-100">
                {runs.data.items.map((run) => (
                  <tr key={run.run_id}>
                    <td className="px-3 py-2 font-mono text-xs">{run.run_id}</td>
                    <td className="px-3 py-2 font-mono text-xs">{run.source_id}</td>
                    <td className="px-3 py-2">
                      <Chip tone={run.status === "success" ? "green" : run.status === "failed" ? "red" : "amber"}>{run.status}</Chip>
                    </td>
                    <td className="px-3 py-2 text-xs">{run.completed_at?.replace("T", " ").slice(0, 19)}</td>
                    <td className="px-3 py-2 tabular-nums">{run.records_seen}</td>
                    <td className="px-3 py-2 tabular-nums">{run.inserted}</td>
                    <td className="px-3 py-2 tabular-nums">{run.updated}</td>
                    <td className="px-3 py-2 tabular-nums">{run.unchanged}</td>
                    <td className="px-3 py-2 tabular-nums">{run.retired}</td>
                    <td className="px-3 py-2 tabular-nums">{run.rejected}</td>
                    <td className="max-w-xs truncate px-3 py-2 text-xs text-slate-500" title={run.notes ?? ""}>
                      {run.notes}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          )}
        </Card>
      )}

      {tab === "quality" && (
        <>
          {quality.loading && <Spinner />}
          {quality.error && <ErrorNote error={quality.error} onRetry={quality.reload} />}
          {quality.data && (
            <Card className="divide-y divide-slate-100">
              {[...quality.data.findings]
                .sort((a, b) => ["error", "warning", "info"].indexOf(a.severity) - ["error", "warning", "info"].indexOf(b.severity))
                .map((finding) => (
                  <div key={finding.check} className="flex flex-wrap items-start gap-3 px-5 py-3">
                    <Chip tone={finding.severity === "error" ? "red" : finding.severity === "warning" ? "amber" : "slate"}>{finding.severity}</Chip>
                    <div className="min-w-0 flex-1">
                      <p className="font-mono text-sm text-ink-900">{finding.check}</p>
                      <p className="text-sm text-slate-600">{finding.note}</p>
                      {finding.examples.length > 0 && <p className="mt-1 truncate text-xs text-slate-500">{finding.examples.slice(0, 3).join("; ")}</p>}
                    </div>
                    <span className="text-lg font-semibold tabular-nums text-ink-900">{finding.count.toLocaleString("en-IN")}</span>
                  </div>
                ))}
            </Card>
          )}
        </>
      )}

      {tab === "limitations" && (
        <Card className="p-5">
          {meta.loading && <Spinner />}
          <ul className="space-y-2 text-sm text-slate-700">
            {meta.data?.limitations.map((item) => (
              <li key={item.key} className="flex gap-2">
                <span className="mt-2 size-1.5 shrink-0 rounded-full bg-saffron-500" aria-hidden />
                {lang === "hi" ? item.hi : item.en}
              </li>
            ))}
          </ul>
        </Card>
      )}
    </div>
  );
}
