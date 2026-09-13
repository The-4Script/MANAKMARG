import { ArrowRight, Compass, FileSearch, FlaskConical, Gem, Route, Search, ShieldCheck, Sparkles } from "lucide-react";
import { useState, type FormEvent } from "react";
import { Link, useNavigate } from "react-router-dom";
import { api } from "../api/client";
import type { Meta } from "../api/types";
import { useApi } from "../api/useApi";
import { Card, formatDate } from "../components/ui";
import { useI18n } from "../i18n/I18nProvider";

const DEMOS = [
  {
    icon: Route,
    en: ["Manufacturer journey", "Stainless steel utensils — standard, QCO, manual, tests, labs and next steps."],
    hi: ["निर्माता यात्रा", "स्टेनलेस स्टील के बर्तन — मानक, QCO, मैनुअल, परीक्षण, लैब और अगले कदम।"],
    to: "/journey?text=stainless%20steel%20utensils",
  },
  {
    icon: FileSearch,
    en: ["Document gap analysis", "Compare a labelled demo datasheet and test report against a demo requirement sheet."],
    hi: ["दस्तावेज़ गैप विश्लेषण", "लेबल वाली डेमो डेटाशीट और परीक्षण रिपोर्ट की डेमो आवश्यकता पत्र से तुलना करें।"],
    to: "/gap-analysis?demo=1",
  },
  {
    icon: Gem,
    en: ["Hallmarking in Jaipur", "District coverage, operative AHCs and the official sources."],
    hi: ["जयपुर में हॉलमार्किंग", "ज़िला कवरेज, सक्रिय AHC और आधिकारिक स्रोत।"],
    to: "/hallmarking?district=Jaipur&state=Rajasthan",
  },
  {
    icon: FlaskConical,
    en: ["Labs for IS 2062 in Kolkata", "Laboratories LIMS lists for structural steel, near Kolkata."],
    hi: ["कोलकाता में IS 2062 लैब", "कोलकाता के पास संरचनात्मक इस्पात के लिए LIMS में सूचीबद्ध प्रयोगशालाएँ।"],
    to: "/labs?ref=IS%202062&city=Kolkata",
  },
];

const COUNT_LABELS: [string, string, string][] = [
  ["standards", "Indian Standards (published list)", "भारतीय मानक (प्रकाशित सूची)"],
  ["coverage_listings", "Compulsory-certification listings", "अनिवार्य प्रमाणन सूचियाँ"],
  ["orders", "QCOs & notifications linked", "जुड़े QCO और अधिसूचनाएँ"],
  ["manuals_parsed", "Product manuals parsed", "पार्स किए गए उत्पाद मैनुअल"],
  ["laboratories", "Laboratories (LIMS)", "प्रयोगशालाएँ (LIMS)"],
  ["lab_scope_rows", "IS-wise lab scope rows", "IS-वार लैब दायरा पंक्तियाँ"],
  ["ahcs", "Assaying & Hallmarking Centres", "परख और हॉलमार्किंग केंद्र"],
  ["hallmarking_districts", "Mandatory hallmarking districts", "अनिवार्य हॉलमार्किंग ज़िले"],
];

export default function Navigator() {
  const { t, lang } = useI18n();
  const navigate = useNavigate();
  const [query, setQuery] = useState("");
  const meta = useApi((signal) => api.get<Meta>("/meta", undefined, signal), []);

  const submit = (event: FormEvent) => {
    event.preventDefault();
    if (query.trim()) navigate(`/assistant?q=${encodeURIComponent(query.trim())}`);
  };

  const pillars = [
    { icon: Compass, title: t("navigator.discover"), text: t("navigator.discoverText"), to: "/standards" },
    { icon: ShieldCheck, title: t("navigator.understand"), text: t("navigator.understandText"), to: "/certification" },
    { icon: FlaskConical, title: t("navigator.check"), text: t("navigator.checkText"), to: "/labs" },
    { icon: Route, title: t("navigator.comply"), text: t("navigator.complyText"), to: "/journey" },
  ];

  return (
    <div className="space-y-10">
      <section className="relative overflow-hidden rounded-3xl bg-ink-900 px-6 py-10 text-white shadow-lg sm:px-10 sm:py-14">
        <div className="pointer-events-none absolute -right-24 -top-24 size-80 rounded-full bg-saffron-500/15 blur-3xl" aria-hidden />
        <div className="pointer-events-none absolute -bottom-32 left-10 size-80 rounded-full bg-ink-600/40 blur-3xl" aria-hidden />
        <div className="relative max-w-3xl">
          <p className="mb-3 inline-flex items-center gap-2 rounded-full bg-white/10 px-3 py-1 text-xs font-medium text-saffron-100">
            <Sparkles className="size-3.5" aria-hidden /> {t("app.tagline")}
          </p>
          <h1 className="text-3xl font-semibold leading-tight tracking-tight sm:text-4xl">{t("navigator.title")}</h1>
          <p className="mt-3 text-ink-100/90">{t("navigator.subtitle")}</p>
          <form onSubmit={submit} className="mt-7 flex flex-col gap-3 sm:flex-row">
            <label className="relative flex-1">
              <span className="sr-only">{t("common.search")}</span>
              <Search className="pointer-events-none absolute left-4 top-1/2 size-5 -translate-y-1/2 text-slate-400" aria-hidden />
              <input
                value={query}
                onChange={(event) => setQuery(event.target.value)}
                placeholder={t("navigator.placeholder")}
                className="w-full rounded-2xl border-0 bg-white py-4 pl-12 pr-4 text-base text-slate-900 shadow-sm placeholder:text-slate-400 focus:outline-none focus:ring-4 focus:ring-saffron-500/40"
              />
            </label>
            <button type="submit" className="inline-flex items-center justify-center gap-2 rounded-2xl bg-saffron-500 px-6 py-4 font-semibold text-ink-950 hover:bg-saffron-100">
              {t("assistant.ask")} <ArrowRight className="size-5" aria-hidden />
            </button>
          </form>
        </div>
      </section>

      <section className="grid gap-4 sm:grid-cols-2 xl:grid-cols-4">
        {pillars.map(({ icon: Icon, title, text, to }) => (
          <Link key={to} to={to} className="group rounded-2xl border border-slate-200 bg-white p-5 shadow-sm transition hover:-translate-y-0.5 hover:border-ink-100 hover:shadow-md">
            <Icon className="size-6 text-saffron-600" aria-hidden />
            <h2 className="mt-3 text-lg font-semibold uppercase tracking-wide text-ink-900">{title}</h2>
            <p className="mt-1 text-sm text-slate-600">{text}</p>
          </Link>
        ))}
      </section>

      <section>
        <h2 className="mb-4 text-lg font-semibold text-ink-900">{t("navigator.demos")}</h2>
        <div className="grid gap-4 md:grid-cols-2">
          {DEMOS.map((demo) => {
            const [title, text] = lang === "hi" ? demo.hi : demo.en;
            const Icon = demo.icon;
            return (
              <Link key={demo.to} to={demo.to} className="flex items-start gap-4 rounded-2xl border border-slate-200 bg-white p-5 shadow-sm transition hover:border-saffron-500/50 hover:shadow-md">
                <div className="grid size-11 shrink-0 place-items-center rounded-xl bg-saffron-50 text-saffron-600">
                  <Icon className="size-5" aria-hidden />
                </div>
                <div className="min-w-0">
                  <h3 className="font-semibold text-ink-900">{title}</h3>
                  <p className="mt-0.5 text-sm text-slate-600">{text}</p>
                </div>
                <ArrowRight className="ml-auto mt-1 size-5 shrink-0 text-slate-400" aria-hidden />
              </Link>
            );
          })}
        </div>
      </section>

      <Card className="p-6">
        <div className="mb-4 flex flex-wrap items-baseline justify-between gap-2">
          <h2 className="text-lg font-semibold text-ink-900">{t("navigator.coverage")}</h2>
          {meta.data && <span className="text-xs text-slate-500">{t("common.checkedOn", { date: formatDate(meta.data.checked_on, lang) })}</span>}
        </div>
        {meta.data ? (
          <>
            <dl className="grid grid-cols-2 gap-4 md:grid-cols-4">
              {COUNT_LABELS.map(([key, en, hi]) => (
                <div key={key} className="rounded-xl bg-ink-50/60 p-4">
                  <dt className="text-xs text-slate-600">{lang === "hi" ? hi : en}</dt>
                  <dd className="mt-1 text-2xl font-semibold tabular-nums text-ink-900">{(meta.data!.counts[key] ?? 0).toLocaleString("en-IN")}</dd>
                </div>
              ))}
            </dl>
            <ul className="mt-5 space-y-1.5 text-sm text-slate-600">
              {meta.data.limitations.map((item) => (
                <li key={item.key} className="flex gap-2">
                  <span className="mt-2 size-1.5 shrink-0 rounded-full bg-saffron-500" aria-hidden />
                  {lang === "hi" ? item.hi : item.en}
                </li>
              ))}
            </ul>
          </>
        ) : (
          <p className="text-sm text-slate-500">{meta.error ? meta.error.message : t("common.loading")}</p>
        )}
      </Card>
    </div>
  );
}
