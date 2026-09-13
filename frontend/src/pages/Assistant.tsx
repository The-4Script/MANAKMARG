import { ArrowRight, Bot, Send, Sparkles } from "lucide-react";
import { useEffect, useRef, useState, type FormEvent } from "react";
import { Link, useSearchParams } from "react-router-dom";
import { api } from "../api/client";
import type { AssistantResponse } from "../api/types";
import { EvidenceProvider, EvidenceRefs, SourcesList } from "../components/evidence";
import { Card, Chip, ErrorNote, formatDate, Notice, PageHeader, Spinner, StatusChip } from "../components/ui";
import { useI18n } from "../i18n/I18nProvider";
import { CAVEATS, pick } from "../i18n/domain";

const EXAMPLES = {
  en: [
    "Which standard applies to stainless steel utensils and is BIS certification mandatory?",
    "Is hallmarking mandatory in Jaipur? Show operative AHCs.",
    "Labs for IS 2062 in Kolkata",
    "Upcoming QCOs",
  ],
  hi: ["स्टेनलेस स्टील के बर्तनों पर कौन सा मानक लागू है?", "क्या जयपुर में हॉलमार्किंग अनिवार्य है?", "कोलकाता में IS 2062 के लिए लैब", "प्रेशर कुकर के लिए BIS लाइसेंस कैसे लें?"],
};

const INTENT_LABEL: Record<string, [string, string]> = {
  product_compliance: ["Product compliance", "उत्पाद अनुपालन"],
  compulsory_status: ["Compulsory status", "अनिवार्यता"],
  applicable_standard: ["Applicable standard", "लागू मानक"],
  hallmarking: ["Hallmarking", "हॉलमार्किंग"],
  lab_search: ["Laboratories", "प्रयोगशालाएँ"],
  tests_required: ["Tests", "परीक्षण"],
  certification_process: ["Certification process", "प्रमाणन प्रक्रिया"],
  upcoming_qco: ["Upcoming QCOs", "आगामी QCO"],
  gap_analysis: ["Gap analysis", "गैप विश्लेषण"],
  general_question: ["General question", "सामान्य प्रश्न"],
};

type Turn = { query: string; response?: AssistantResponse; error?: Error };

function Answer({ response }: { response: AssistantResponse }) {
  const { t, lang } = useI18n();
  const understanding = response.understanding;
  return (
    <EvidenceProvider evidence={response.evidence}>
      <Card className="p-6">
        <div className="flex flex-wrap items-center gap-2 text-xs text-slate-500">
          <span>{t("assistant.understood")}:</span>
          {understanding.intents.map((intent) => (
            <Chip key={intent} tone="indigo">
              {INTENT_LABEL[intent]?.[lang === "hi" ? 1 : 0] ?? intent}
            </Chip>
          ))}
          {understanding.standard_refs.map((ref) => (
            <Chip key={ref}>
              <span className="id-token">{ref}</span>
            </Chip>
          ))}
          {understanding.product_text && <Chip>{understanding.product_text}</Chip>}
          {[understanding.district, understanding.city, understanding.state].filter(Boolean).map((place) => (
            <Chip key={place}>{place}</Chip>
          ))}
        </div>

        <div className="mt-4 flex flex-wrap items-start gap-3">
          <h2 className="flex-1 text-xl font-semibold leading-snug text-ink-900">{response.headline}</h2>
          {response.status_label && <StatusChip status={response.status_label} />}
        </div>
        {response.narrative && (
          <p className="mt-3 flex gap-2 rounded-xl bg-ink-50/70 p-3 text-sm text-ink-900">
            <Sparkles className="mt-0.5 size-4 shrink-0 text-saffron-600" aria-hidden />
            {response.narrative}
          </p>
        )}

        <div className="mt-5 space-y-5">
          {response.sections.map((section) => (
            <section key={section.key}>
              <h3 className="text-sm font-semibold uppercase tracking-wide text-slate-500">{section.title}</h3>
              <ul className="mt-2 space-y-2">
                {section.items.map((item, index) => (
                  <li key={index} className="flex flex-wrap items-start gap-2 text-sm leading-relaxed text-slate-800">
                    <span className="mt-2 size-1.5 shrink-0 rounded-full bg-saffron-500" aria-hidden />
                    <span className="min-w-0 flex-1">{item.text}</span>
                    <EvidenceRefs ids={item.evidence_ids} />
                  </li>
                ))}
              </ul>
            </section>
          ))}
        </div>

        {response.next_actions.length > 0 && (
          <div className="mt-5">
            <h3 className="text-sm font-semibold uppercase tracking-wide text-slate-500">{t("common.nextSteps")}</h3>
            <ol className="mt-2 grid gap-2 md:grid-cols-2">
              {response.next_actions.map((action, index) => (
                <li key={index} className="rounded-xl bg-saffron-50 px-3 py-2 text-sm text-amber-950">
                  {index + 1}. {action.text} <EvidenceRefs ids={action.evidence_ids} />
                </li>
              ))}
            </ol>
          </div>
        )}

        {response.links.length > 0 && (
          <div className="mt-4 flex flex-wrap gap-3">
            {response.links.map((link) => (
              <Link key={link.to} to={link.to} className="inline-flex items-center gap-1 text-sm font-medium text-ink-700 hover:underline">
                {link.label} <ArrowRight className="size-4" aria-hidden />
              </Link>
            ))}
          </div>
        )}

        {response.caveats.length > 0 && (
          <div className="mt-5">
            <Notice>
              <ul className="list-disc space-y-1 pl-5">
                {response.caveats.map((code) => (
                  <li key={code}>{pick(CAVEATS[code], lang, code)}</li>
                ))}
              </ul>
            </Notice>
          </div>
        )}
        <p className="mt-4 text-xs text-slate-500">
          {response.narrative_source === "llm" ? t("assistant.llmNote") : t("assistant.templateNote")} · {t("common.checkedOn", { date: formatDate(new Date().toISOString(), lang) })}
        </p>
      </Card>
      <div className="mt-3">
        <SourcesList sources={response.sources} />
      </div>
    </EvidenceProvider>
  );
}

export default function Assistant() {
  const { t, lang } = useI18n();
  const [params, setParams] = useSearchParams();
  const [text, setText] = useState("");
  const [turns, setTurns] = useState<Turn[]>([]);
  const [loading, setLoading] = useState(false);
  const asked = useRef<string | null>(null);

  const ask = async (query: string) => {
    const clean = query.trim();
    if (!clean) return;
    setLoading(true);
    setText("");
    setTurns((previous) => [{ query: clean }, ...previous]);
    try {
      const response = await api.post<AssistantResponse>("/assistant/query", { query: clean, lang });
      setTurns((previous) => [{ query: clean, response }, ...previous.slice(1)]);
    } catch (reason) {
      setTurns((previous) => [{ query: clean, error: reason instanceof Error ? reason : new Error(String(reason)) }, ...previous.slice(1)]);
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    const q = params.get("q");
    if (q && asked.current !== q) {
      asked.current = q;
      ask(q);
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [params]);

  const submit = (event: FormEvent) => {
    event.preventDefault();
    if (text.trim()) setParams({ q: text.trim() });
  };

  return (
    <div>
      <PageHeader title={t("assistant.title")} subtitle={t("navigator.subtitle")} />
      <form onSubmit={submit} className="sticky top-16 z-20 flex gap-3 rounded-2xl border border-slate-200 bg-white p-3 shadow-md">
        <Bot className="ml-2 mt-2.5 size-5 shrink-0 text-ink-700" aria-hidden />
        <input value={text} onChange={(event) => setText(event.target.value)} placeholder={t("assistant.placeholder")} className="min-w-0 flex-1 bg-transparent px-1 py-2 text-base text-slate-900 placeholder:text-slate-400 focus:outline-none" />
        <button type="submit" disabled={loading || !text.trim()} className="inline-flex items-center gap-2 rounded-xl bg-ink-800 px-4 py-2 font-medium text-white hover:bg-ink-700 disabled:bg-slate-300">
          <Send className="size-4" aria-hidden /> {t("assistant.ask")}
        </button>
      </form>

      {!turns.length && (
        <div className="mt-6 grid gap-3 md:grid-cols-2">
          {EXAMPLES[lang].map((example) => (
            <button key={example} onClick={() => setParams({ q: example })} className="rounded-2xl border border-slate-200 bg-white p-4 text-left text-sm text-ink-900 shadow-sm hover:border-ink-600">
              {example}
            </button>
          ))}
        </div>
      )}

      <div className="mt-6 space-y-8">
        {turns.map((turn, index) => (
          <article key={`${turn.query}-${index}`} className="space-y-3">
            <p className="ml-auto w-fit max-w-2xl rounded-2xl rounded-br-sm bg-ink-800 px-4 py-2.5 text-white">{turn.query}</p>
            {!turn.response && !turn.error && <Spinner />}
            {turn.error && <ErrorNote error={turn.error} onRetry={() => ask(turn.query)} />}
            {turn.response && <Answer response={turn.response} />}
            {turn.response && index === 0 && turn.response.follow_ups.length > 0 && (
              <div className="flex flex-wrap items-center gap-2 text-sm">
                <span className="text-slate-500">{t("assistant.followUps")}:</span>
                {turn.response.follow_ups.map((follow) => (
                  <button key={follow} onClick={() => setParams({ q: follow })} className="rounded-full bg-white px-3 py-1 text-ink-800 ring-1 ring-slate-200 hover:ring-ink-600">
                    {follow}
                  </button>
                ))}
              </div>
            )}
          </article>
        ))}
      </div>
    </div>
  );
}
