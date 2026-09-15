import { FileText, Link2, X } from "lucide-react";
import { createContext, useContext, useMemo, useState, type ReactNode } from "react";
import type { Evidence, SourceRollup } from "../api/types";
import { useI18n } from "../i18n/I18nProvider";
import { Chip, cx, ExternalAnchor, formatDate } from "./ui";

type EvidenceContextValue = { byId: Map<string, Evidence>; open: (ids: string[]) => void };

const EvidenceContext = createContext<EvidenceContextValue>({ byId: new Map(), open: () => undefined });

const AUTHORITY: Record<string, { en: string; hi: string; tone: "green" | "amber" | "slate" | "indigo" }> = {
  official_primary: { en: "Official source", hi: "आधिकारिक स्रोत", tone: "green" },
  official_secondary: { en: "Official (secondary)", hi: "आधिकारिक (द्वितीयक)", tone: "indigo" },
  derived: { en: "Derived cross-check", hi: "व्युत्पन्न जाँच", tone: "amber" },
  curated: { en: "Curated matching aid", hi: "संकलित मिलान सहायता", tone: "slate" },
  supplied_dataset: { en: "Supplied dataset", hi: "प्रदत्त डेटासेट", tone: "slate" },
};

const ACTION_KEYS = new Set([
  "view_notification",
  "verify_on_bis",
  "view_standard_portal",
  "view_product_manual",
  "view_lims",
  "view_hallmarking_source",
  "open_official_document",
  "view_official_source",
]);

function actionLabel(action: string, t: (key: never) => string): string {
  return t((ACTION_KEYS.has(action) ? `source.${action}` : "source.view_official_source") as never);
}

/** Direct links to the official BIS / Gazette pages behind an item (at most two). Pass one shared ``shown`` set per
 * answer so the same official page is linked once, at its first mention, instead of on every line. */
export function OfficialSourceLinks({ ids, shown }: { ids: (string | null | undefined)[] | undefined; shown?: Set<string> }) {
  const { byId } = useContext(EvidenceContext);
  const { t } = useI18n();
  const seen = shown ?? new Set<string>();
  const links: { url: string; action: string }[] = [];
  for (const id of ids ?? []) {
    const item = id ? byId.get(id) : undefined;
    if (!item?.url || !item.action || seen.has(item.url)) continue;
    seen.add(item.url);
    links.push({ url: item.url, action: item.action });
  }
  if (!links.length) return null;
  return (
    <span className="no-print inline-flex flex-wrap items-center gap-x-3 gap-y-1">
      {links.slice(0, 2).map((link) => (
        <ExternalAnchor key={link.url} href={link.url} className="text-xs font-medium">
          {actionLabel(link.action, t as never)}
        </ExternalAnchor>
      ))}
    </span>
  );
}

export function AuthorityChip({ authority }: { authority: string }) {
  const { lang } = useI18n();
  const info = AUTHORITY[authority] ?? { en: authority, hi: authority, tone: "slate" as const };
  return <Chip tone={info.tone}>{lang === "hi" ? info.hi : info.en}</Chip>;
}

export function EvidenceProvider({ evidence, children }: { evidence: Evidence[] | undefined; children: ReactNode }) {
  const [selected, setSelected] = useState<string[] | null>(null);
  const byId = useMemo(() => new Map((evidence ?? []).map((item) => [item.id, item])), [evidence]);
  const value = useMemo(() => ({ byId, open: (ids: string[]) => setSelected(ids) }), [byId]);
  return (
    <EvidenceContext.Provider value={value}>
      {children}
      {selected && <EvidenceDrawer items={selected.map((id) => byId.get(id)).filter((item): item is Evidence => !!item)} onClose={() => setSelected(null)} />}
    </EvidenceContext.Provider>
  );
}

export function EvidenceRefs({ ids, className }: { ids: (string | null | undefined)[] | undefined; className?: string }) {
  const { open, byId } = useContext(EvidenceContext);
  const { t } = useI18n();
  const valid = [...new Set((ids ?? []).filter((id): id is string => !!id && byId.has(id)))];
  if (!valid.length) return null;
  return (
    <button
      type="button"
      onClick={() => open(valid)}
      className={cx("no-print inline-flex items-center gap-1.5 rounded-full border border-ink-100 bg-ink-50 px-2.5 py-0.5 text-xs font-medium text-ink-700 hover:border-ink-600", className)}
      title={valid.join(", ")}
    >
      <FileText className="size-3.5" aria-hidden />
      {t("common.evidence")} · {valid.length}
    </button>
  );
}

function EvidenceDrawer({ items, onClose }: { items: Evidence[]; onClose: () => void }) {
  const { t, lang } = useI18n();
  return (
    <div className="no-print fixed inset-0 z-50" role="dialog" aria-modal aria-label={t("common.evidence")}>
      <div className="absolute inset-0 bg-ink-950/40" onClick={onClose} />
      <aside className="absolute inset-y-0 right-0 flex w-full max-w-lg flex-col bg-white shadow-2xl">
        <header className="flex items-center justify-between border-b border-slate-200 px-5 py-4">
          <h2 className="text-lg font-semibold text-ink-900">{t("common.evidence")}</h2>
          <button onClick={onClose} className="rounded-lg p-1.5 hover:bg-slate-100" aria-label={t("common.close")}>
            <X className="size-5" />
          </button>
        </header>
        <ol className="flex-1 space-y-4 overflow-y-auto p-5">
          {items.map((item) => (
            <li key={item.id} className="rounded-xl border border-slate-200 p-4">
              <div className="flex flex-wrap items-center gap-2">
                <span className="id-token rounded bg-slate-100 px-1.5 py-0.5 text-slate-600">{item.id}</span>
                <AuthorityChip authority={item.authority} />
                {item.page && <Chip>p. {item.page}</Chip>}
              </div>
              <h3 className="mt-2 font-medium text-ink-900">{item.title}</h3>
              {item.snippet && <blockquote className="mt-2 border-l-2 border-saffron-500 pl-3 text-sm text-slate-700">“{item.snippet}”</blockquote>}
              <dl className="mt-3 space-y-1 text-xs text-slate-500">
                <div>
                  <dt className="inline font-medium">{t("common.source")}: </dt>
                  <dd className="inline">{item.source_name}</dd>
                </div>
                {item.retrieved_at && (
                  <div>
                    <dt className="inline font-medium">{t("common.retrieved")}: </dt>
                    <dd className="inline">{formatDate(item.retrieved_at, lang)}</dd>
                  </div>
                )}
              </dl>
              {item.url && item.action && (
                <ExternalAnchor href={item.url} className="mt-2 text-sm font-medium">
                  {actionLabel(item.action, t as never)}
                </ExternalAnchor>
              )}
              {item.url && !item.action && (
                <ExternalAnchor href={item.url} className="mt-2 text-sm">
                  {t("common.officialLink")}
                </ExternalAnchor>
              )}
            </li>
          ))}
        </ol>
      </aside>
    </div>
  );
}

export function SourcesList({ sources }: { sources: SourceRollup[] | undefined }) {
  const { t, lang } = useI18n();
  if (!sources?.length) return null;
  return (
    <section className="rounded-2xl border border-slate-200 bg-white p-5">
      <h2 className="mb-3 flex items-center gap-2 font-semibold text-ink-900">
        <Link2 className="size-4" aria-hidden /> {t("common.sources")}
      </h2>
      <ul className="grid gap-3 md:grid-cols-2">
        {sources.map((source) => (
          <li key={source.source_id} className="text-sm">
            <div className="flex flex-wrap items-center gap-2">
              <ExternalAnchor href={source.url}>{source.name}</ExternalAnchor>
              <AuthorityChip authority={source.authority} />
            </div>
            <p className="mt-0.5 text-xs text-slate-500">
              {source.retrieved_at.length ? `${t("common.retrieved")}: ${formatDate(source.retrieved_at[0], lang)}` : null}
              {source.as_of ? ` · ${source.as_of}` : null}
            </p>
          </li>
        ))}
      </ul>
    </section>
  );
}
