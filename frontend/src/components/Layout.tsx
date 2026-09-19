import {
  BookOpenCheck,
  Compass,
  Database,
  FileSearch,
  FlaskConical,
  Gem,
  Languages,
  Library,
  Menu,
  MessagesSquare,
  Route,
  ShieldCheck,
  X,
} from "lucide-react";
import { useState, type ReactNode } from "react";
import { NavLink, useLocation } from "react-router-dom";
import { useI18n } from "../i18n/I18nProvider";
import type { StringKey } from "../i18n/strings";
import { cx } from "./ui";

const NAV: { to: string; key: StringKey; icon: typeof Compass }[] = [
  { to: "/", key: "nav.navigator", icon: Compass },
  { to: "/assistant", key: "nav.assistant", icon: MessagesSquare },
  { to: "/journey", key: "nav.journey", icon: Route },
  { to: "/standards", key: "nav.standards", icon: Library },
  { to: "/certification", key: "nav.certification", icon: ShieldCheck },
  { to: "/labs", key: "nav.labs", icon: FlaskConical },
  { to: "/hallmarking", key: "nav.hallmarking", icon: Gem },
  { to: "/gap-analysis", key: "nav.gap", icon: FileSearch },
  { to: "/sources", key: "nav.sources", icon: Database },
];

function Logo() {
  return (
    <div className="w-full overflow-hidden rounded-xl bg-white px-2 py-1" aria-label="MANAK MARG">
      <img src="/assets/manak-marg-logo-full.png" alt="MANAK MARG" className="h-auto w-full" />
    </div>
  );
}

export default function Layout({ children }: { children: ReactNode }) {
  const { t, lang, setLang } = useI18n();
  const [open, setOpen] = useState(false);
  const location = useLocation();

  const nav = (
    <nav className="flex flex-col gap-1" aria-label="Main">
      {NAV.map(({ to, key, icon: Icon }) => (
        <NavLink
          key={to}
          to={to}
          end={to === "/"}
          onClick={() => setOpen(false)}
          className={({ isActive }) =>
            cx(
              "flex items-center gap-3 rounded-xl px-3 py-2.5 text-sm font-medium transition",
              isActive ? "bg-white/12 text-white ring-1 ring-white/15" : "text-ink-100/85 hover:bg-white/8 hover:text-white",
            )
          }
        >
          <Icon className="size-[18px] shrink-0" aria-hidden />
          {t(key)}
        </NavLink>
      ))}
    </nav>
  );

  return (
    <div className="flex min-h-full">
      <aside className="no-print sticky top-0 hidden h-screen w-72 shrink-0 flex-col gap-8 overflow-y-auto bg-ink-950 px-5 py-6 lg:flex">
        <Logo />
        {nav}
        <div className="mt-auto rounded-xl bg-white/5 p-3 text-xs leading-relaxed text-ink-100/75">
          <BookOpenCheck className="mb-1.5 size-4 text-saffron-500" aria-hidden />
          {t("app.prototype")}
        </div>
      </aside>

      <div className="flex min-w-0 flex-1 flex-col">
        <header className="no-print sticky top-0 z-30 flex items-center justify-between gap-3 border-b border-slate-200 bg-paper/90 px-4 py-3 backdrop-blur sm:px-8">
          <div className="flex min-w-0 items-center gap-1.5 lg:hidden">
            <button className="rounded-lg p-2 text-ink-900 hover:bg-slate-100" onClick={() => setOpen(true)} aria-label="Open navigation">
              <Menu className="size-5" />
            </button>
            <img src="/assets/manak-marg-logo-full.png" alt="MANAK MARG" className="h-12 w-24 object-contain object-left" />
          </div>
          <p className="hidden truncate text-xs text-slate-500 sm:block">{t("app.prototype")}</p>
          <button
            onClick={() => setLang(lang === "en" ? "hi" : "en")}
            className="inline-flex items-center gap-2 rounded-full border border-slate-300 bg-white px-3.5 py-1.5 text-sm font-medium text-ink-900 hover:bg-slate-50"
            aria-label="Switch language"
          >
            <Languages className="size-4" aria-hidden />
            {t("common.language")}
          </button>
        </header>

        {open && (
          <div className="fixed inset-0 z-40 lg:hidden" role="dialog" aria-modal>
            <div className="absolute inset-0 bg-ink-950/60" onClick={() => setOpen(false)} />
            <div className="absolute inset-y-0 left-0 flex w-72 flex-col gap-6 overflow-y-auto bg-ink-950 px-5 py-6">
              <div className="flex items-center justify-between">
                <Logo />
                <button onClick={() => setOpen(false)} className="rounded-lg p-1.5 text-white hover:bg-white/10" aria-label={t("common.close")}>
                  <X className="size-5" />
                </button>
              </div>
              {nav}
            </div>
          </div>
        )}

        <main key={location.pathname} className="mx-auto w-full max-w-7xl flex-1 px-4 py-6 sm:px-8 sm:py-8">
          {children}
        </main>
      </div>
    </div>
  );
}
