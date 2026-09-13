import { AlertTriangle, ExternalLink, Info, Loader2 } from "lucide-react";
import type { ButtonHTMLAttributes, ReactNode } from "react";
import { useI18n } from "../i18n/I18nProvider";
import type { StringKey } from "../i18n/strings";

export function cx(...classes: (string | false | null | undefined)[]) {
  return classes.filter(Boolean).join(" ");
}

export function Card({ children, className, as: Tag = "section" }: { children: ReactNode; className?: string; as?: "section" | "div" | "article" }) {
  return <Tag className={cx("rounded-2xl border border-slate-200 bg-white shadow-sm", className)}>{children}</Tag>;
}

export function PageHeader({ title, subtitle, children }: { title: string; subtitle?: string; children?: ReactNode }) {
  return (
    <header className="mb-6 flex flex-wrap items-end justify-between gap-4">
      <div>
        <h1 className="text-2xl font-semibold tracking-tight text-ink-900 sm:text-3xl">{title}</h1>
        {subtitle && <p className="mt-1.5 max-w-3xl text-slate-600">{subtitle}</p>}
      </div>
      {children}
    </header>
  );
}

export function Button({
  children,
  variant = "primary",
  className,
  ...rest
}: ButtonHTMLAttributes<HTMLButtonElement> & { variant?: "primary" | "secondary" | "ghost" }) {
  const styles = {
    primary: "bg-ink-800 text-white hover:bg-ink-700 disabled:bg-slate-300",
    secondary: "border border-slate-300 bg-white text-ink-900 hover:bg-slate-50 disabled:text-slate-400",
    ghost: "text-ink-700 hover:bg-ink-50",
  }[variant];
  return (
    <button
      className={cx("inline-flex items-center justify-center gap-2 rounded-xl px-4 py-2.5 text-sm font-medium transition disabled:cursor-not-allowed", styles, className)}
      {...rest}
    >
      {children}
    </button>
  );
}

const TONES = {
  green: "bg-emerald-50 text-emerald-800 ring-emerald-200",
  amber: "bg-amber-50 text-amber-900 ring-amber-200",
  red: "bg-rose-50 text-rose-800 ring-rose-200",
  slate: "bg-slate-100 text-slate-700 ring-slate-200",
  indigo: "bg-ink-50 text-ink-800 ring-ink-100",
} as const;

const STATUS_TONE: Record<string, keyof typeof TONES> = {
  CONFIRMED: "green",
  OPERATIVE: "green",
  PASS: "green",
  VALID: "green",
  COVERED: "green",
  BIS_LAB: "green",
  LISTED_COMPULSORY: "indigo",
  LIKELY_APPLICABLE: "amber",
  UPCOMING: "amber",
  POTENTIAL_GAP: "amber",
  CANDIDATE: "amber",
  NEEDS_VERIFICATION: "amber",
  COVERED_NEEDS_VERIFICATION: "amber",
  AMBIGUOUS: "amber",
  SUSPENDED_GOLD_ONLY: "red",
  DENOTIFIED: "red",
  RESCINDED: "red",
  FAIL: "red",
  SUSPENDED: "red",
  CANCELLED: "red",
  EXPIRED: "red",
  EXPIRED_VALIDITY: "red",
  WITHDRAWN: "red",
  NOT_OPERATIVE: "red",
};

export function Chip({ children, tone = "slate", className }: { children: ReactNode; tone?: keyof typeof TONES; className?: string }) {
  return <span className={cx("inline-flex items-center gap-1 rounded-full px-2.5 py-0.5 text-xs font-medium ring-1 ring-inset", TONES[tone], className)}>{children}</span>;
}

export function StatusChip({ status }: { status: string | null | undefined }) {
  const { t } = useI18n();
  if (!status) return null;
  const key = `status.${status}` as StringKey;
  const label = t(key);
  return <Chip tone={STATUS_TONE[status] ?? "slate"}>{label === key ? status.replaceAll("_", " ").toLowerCase() : label}</Chip>;
}

export function Spinner({ label }: { label?: string }) {
  const { t } = useI18n();
  return (
    <div className="flex items-center gap-2 py-8 text-slate-500" role="status">
      <Loader2 className="size-5 animate-spin" aria-hidden />
      <span>{label ?? t("common.loading")}</span>
    </div>
  );
}

export function ErrorNote({ error, onRetry }: { error: Error; onRetry?: () => void }) {
  const { t } = useI18n();
  return (
    <div className="flex flex-wrap items-center gap-3 rounded-xl border border-rose-200 bg-rose-50 p-4 text-rose-900" role="alert">
      <AlertTriangle className="size-5" aria-hidden />
      <span>
        {t("common.error")}: {error.message}
      </span>
      {onRetry && (
        <Button variant="secondary" onClick={onRetry}>
          {t("common.retry")}
        </Button>
      )}
    </div>
  );
}

export function EmptyState({ children }: { children: ReactNode }) {
  return (
    <div className="flex items-start gap-3 rounded-xl border border-dashed border-slate-300 bg-slate-50 p-5 text-slate-600">
      <Info className="mt-0.5 size-5 shrink-0" aria-hidden />
      <div>{children}</div>
    </div>
  );
}

export function Notice({ tone = "amber", children }: { tone?: "amber" | "slate" | "indigo"; children: ReactNode }) {
  const styles = {
    amber: "border-amber-200 bg-saffron-50 text-amber-950",
    slate: "border-slate-200 bg-slate-50 text-slate-700",
    indigo: "border-ink-100 bg-ink-50 text-ink-900",
  }[tone];
  return <div className={cx("rounded-xl border p-4 text-sm", styles)}>{children}</div>;
}

export function ExternalAnchor({ href, children, className }: { href: string | null | undefined; children: ReactNode; className?: string }) {
  if (!href) return <>{children}</>;
  return (
    <a href={href} target="_blank" rel="noopener noreferrer" className={cx("inline-flex items-center gap-1 text-ink-700 underline decoration-ink-100 underline-offset-4 hover:decoration-ink-600", className)}>
      {children}
      <ExternalLink className="size-3.5 shrink-0" aria-hidden />
    </a>
  );
}

export function Id({ children }: { children: ReactNode }) {
  return <span className="id-token">{children}</span>;
}

export function Field({ label, children }: { label: string; children: ReactNode }) {
  return (
    <label className="flex min-w-0 flex-col gap-1.5 text-sm">
      <span className="font-medium text-slate-700">{label}</span>
      {children}
    </label>
  );
}

export const inputClass =
  "w-full rounded-xl border border-slate-300 bg-white px-3.5 py-2.5 text-slate-900 placeholder:text-slate-400 focus:border-ink-600 focus:outline-none focus:ring-2 focus:ring-ink-100";

export function formatDate(value: string | null | undefined, lang: string): string {
  if (!value) return "—";
  const date = new Date(value.length === 10 ? `${value}T00:00:00` : value);
  if (Number.isNaN(date.getTime())) return value;
  return date.toLocaleDateString(lang === "hi" ? "hi-IN" : "en-IN", { day: "numeric", month: "short", year: "numeric" });
}
