import { FileCheck2, FlaskConical, ShieldAlert, Trash2, Upload } from "lucide-react";
import { useEffect, useRef, useState } from "react";
import { useSearchParams } from "react-router-dom";
import { api } from "../api/client";
import type { Meta } from "../api/types";
import { useApi } from "../api/useApi";
import { Button, Card, Chip, cx, EmptyState, ErrorNote, Notice, PageHeader, Spinner, StatusChip } from "../components/ui";
import { useI18n } from "../i18n/I18nProvider";
import type { StringKey } from "../i18n/strings";

type SessionFile = { file_id: string; filename: string; role: string; bytes?: number; demo?: boolean };
type Requirement = { parameter: string; operator: string; value: number; value_max: number | null; unit: string | null; unit_raw: string | null; clause: string | null; page: number; raw_text: string; document: string };
type ProductValue = { parameter: string; value: number; value_max: number | null; unit: string | null; unit_raw: string | null; page: number; raw_text: string; document: string; role: string };
type Row = { requirement: Requirement; value: ProductValue | null; status: string; code: string; similarity: number | null; explanation: string };
type Report = { session_id: string; generated_at: string; files: { filename: string; role: string; demo: boolean; requirements?: number; values?: number }[]; requirement_count: number; value_count: number; rows: Row[]; counts: Record<string, number>; notes: string[] };

const ROLES: { role: string; key: StringKey }[] = [
  { role: "requirement", key: "gap.requirement" },
  { role: "datasheet", key: "gap.datasheet" },
  { role: "test_report", key: "gap.report" },
];
const STATUS_ORDER = ["FAIL", "POTENTIAL_GAP", "UNKNOWN", "INSUFFICIENT_EVIDENCE", "PASS"];
const SESSION_KEY = "manakmarg.gapSession";

function limit(requirement: Requirement) {
  const unit = requirement.unit ?? requirement.unit_raw ?? "";
  if (requirement.operator === "range") return `${requirement.value}–${requirement.value_max} ${unit}`;
  return `${requirement.operator === "min" ? "≥" : requirement.operator === "max" ? "≤" : "="} ${requirement.value} ${unit}`;
}

function shown(value: ProductValue) {
  return `${value.value}${value.value_max != null ? `–${value.value_max}` : ""} ${value.unit ?? value.unit_raw ?? ""}`.trim();
}

function explanationHi(row: Row) {
  const value = row.value ? shown(row.value) : "";
  switch (row.code) {
    case "satisfied":
      return `${value} आवश्यकता ${limit(row.requirement)} पूरी करता है।`;
    case "uncertain_match":
      return `${value} आवश्यकता ${limit(row.requirement)} पूरी कर सकता है, पर पुष्टि करें कि “${row.value?.parameter}” वही पैरामीटर है।`;
    case "measured_violation":
      return `मापा गया ${value} आवश्यकता ${limit(row.requirement)} पूरी नहीं करता।`;
    case "declared_violation":
      return `घोषित ${value} आवश्यकता ${limit(row.requirement)} पूरी नहीं करता।`;
    case "units_not_comparable":
      return "इकाइयों की तुलना नहीं की जा सकती।";
    default:
      return "डेटाशीट या परीक्षण रिपोर्ट में कोई मिलान मान नहीं मिला।";
  }
}

export default function GapAnalysis() {
  const { t, lang } = useI18n();
  const [params] = useSearchParams();
  const meta = useApi((signal) => api.get<Meta>("/meta", undefined, signal), []);
  const [session, setSession] = useState<string | null>(() => {
    try {
      return sessionStorage.getItem(SESSION_KEY);
    } catch {
      return null;
    }
  });
  const [files, setFiles] = useState<SessionFile[]>([]);
  const [report, setReport] = useState<Report | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<Error | null>(null);
  const demoStarted = useRef(false);

  const remember = (id: string | null) => {
    setSession(id);
    try {
      if (id) sessionStorage.setItem(SESSION_KEY, id);
      else sessionStorage.removeItem(SESSION_KEY);
    } catch {
      /* storage unavailable */
    }
  };

  const ensureSession = async (): Promise<string> => {
    if (session) {
      try {
        const info = await api.get<{ files: SessionFile[] }>(`/documents/sessions/${session}`);
        setFiles(info.files);
        return session;
      } catch {
        remember(null);
      }
    }
    const created = await api.post<{ session_id: string }>("/documents/sessions", {});
    remember(created.session_id);
    setFiles([]);
    return created.session_id;
  };

  const run = async (action: () => Promise<void>) => {
    setBusy(true);
    setError(null);
    try {
      await action();
    } catch (reason) {
      setError(reason instanceof Error ? reason : new Error(String(reason)));
    } finally {
      setBusy(false);
    }
  };

  const refresh = async (id: string) => setFiles((await api.get<{ files: SessionFile[] }>(`/documents/sessions/${id}`)).files);

  const upload = (role: string, file: File) =>
    run(async () => {
      const id = await ensureSession();
      const form = new FormData();
      form.set("role", role);
      form.set("file", file);
      await api.upload(`/documents/sessions/${id}/files`, form);
      await refresh(id);
      setReport(null);
    });

  const useDemo = () =>
    run(async () => {
      const id = await ensureSession();
      await api.post(`/documents/sessions/${id}/demo`, {});
      await refresh(id);
      setReport(await api.post<Report>(`/documents/sessions/${id}/analyze`, {}));
    });

  const analyze = () =>
    run(async () => {
      const id = await ensureSession();
      setReport(await api.post<Report>(`/documents/sessions/${id}/analyze`, {}));
    });

  const removeFile = (fileId: string) =>
    run(async () => {
      if (!session) return;
      await api.delete(`/documents/sessions/${session}/files/${fileId}`);
      await refresh(session);
      setReport(null);
    });

  const endSession = () =>
    run(async () => {
      if (session) await api.delete(`/documents/sessions/${session}`).catch(() => undefined);
      remember(null);
      setFiles([]);
      setReport(null);
    });

  useEffect(() => {
    if (session) api.get<{ files: SessionFile[] }>(`/documents/sessions/${session}`).then((info) => setFiles(info.files)).catch(() => remember(null));
    if (params.get("demo") === "1" && !demoStarted.current) {
      demoStarted.current = true;
      useDemo();
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  const rows = report ? [...report.rows].sort((a, b) => STATUS_ORDER.indexOf(a.status) - STATUS_ORDER.indexOf(b.status)) : [];
  return (
    <div className="space-y-6">
      <PageHeader title={t("gap.title")} subtitle={t("gap.subtitle")} />
      <Notice tone="indigo">
        <span className="flex items-start gap-2">
          <ShieldAlert className="mt-0.5 size-4 shrink-0" aria-hidden />
          <span>
            {t("gap.privacy", { minutes: meta.data?.upload_ttl_minutes ?? 120 })}{" "}
            {lang === "hi"
              ? "यह प्रणाली कोई आवश्यकता स्वयं नहीं बनाती — केवल आपके आवश्यकता-स्रोत दस्तावेज़ में लिखी सीमाओं से तुलना करती है।"
              : "The system never creates requirements — it only compares against limits written in your requirement-source document."}
          </span>
        </span>
      </Notice>

      <div className="grid gap-4 md:grid-cols-3">
        {ROLES.map(({ role, key }) => {
          const roleFiles = files.filter((file) => file.role === role);
          return (
            <Card key={role} className="flex min-w-0 flex-col p-5">
              <h2 className="font-semibold text-ink-900">{t(key)}</h2>
              <p className="mt-1 text-xs text-slate-500">PDF · DOCX · TXT</p>
              <ul className="mt-3 flex-1 space-y-2">
                {roleFiles.map((file) => (
                  <li key={file.file_id} className="flex items-center gap-2 rounded-lg bg-slate-50 px-3 py-2 text-sm">
                    <FileCheck2 className="size-4 shrink-0 text-emerald-600" aria-hidden />
                    <span className="min-w-0 flex-1 truncate" title={file.filename}>
                      {file.filename}
                    </span>
                    {file.demo && <Chip tone="amber">demo</Chip>}
                    <button onClick={() => removeFile(file.file_id)} className="rounded p-1 text-slate-400 hover:bg-slate-200 hover:text-rose-700" aria-label="Remove">
                      <Trash2 className="size-4" />
                    </button>
                  </li>
                ))}
              </ul>
              <label className={cx("mt-3 inline-flex cursor-pointer items-center justify-center gap-2 rounded-xl border border-dashed border-slate-300 px-4 py-3 text-sm font-medium text-ink-800 hover:border-ink-600", busy && "pointer-events-none opacity-60")}>
                <Upload className="size-4" aria-hidden />
                {lang === "hi" ? "फ़ाइल चुनें" : "Choose file"}
                <input
                  type="file"
                  accept=".pdf,.docx,.txt"
                  className="sr-only"
                  onChange={(event) => {
                    const file = event.target.files?.[0];
                    if (file) upload(role, file);
                    event.target.value = "";
                  }}
                />
              </label>
            </Card>
          );
        })}
      </div>

      <div className="flex flex-wrap gap-3">
        <Button onClick={analyze} disabled={busy || !files.length}>
          <FlaskConical className="size-4" aria-hidden /> {t("gap.analyze")}
        </Button>
        <Button variant="secondary" onClick={useDemo} disabled={busy}>
          {t("gap.useDemo")}
        </Button>
        {session && (
          <Button variant="ghost" onClick={endSession} disabled={busy}>
            <Trash2 className="size-4" aria-hidden /> {lang === "hi" ? "सत्र समाप्त करें और फ़ाइलें हटाएँ" : "End session & delete files"}
          </Button>
        )}
      </div>

      {busy && <Spinner />}
      {error && <ErrorNote error={error} />}

      {report && !busy && (
        <section className="space-y-4">
          <div className="flex flex-wrap items-center gap-3">
            {STATUS_ORDER.filter((status) => report.counts[status]).map((status) => (
              <span key={status} className="inline-flex items-center gap-1 text-sm">
                <StatusChip status={status} /> {report.counts[status]}
              </span>
            ))}
            <span className="text-xs text-slate-500">
              {report.requirement_count} {lang === "hi" ? "आवश्यकताएँ" : "requirements"} · {report.value_count} {lang === "hi" ? "उत्पाद मान" : "product values"}
            </span>
          </div>
          {report.files.some((file) => file.demo) && (
            <Notice>
              {lang === "hi"
                ? "डेमो फ़ाइलें काल्पनिक हैं। डेमो आवश्यकता पत्र कोई भारतीय मानक नहीं है।"
                : "Demo files are fictional. The demo requirement sheet is not an Indian Standard."}
            </Notice>
          )}
          {report.notes.map((note) => (
            <EmptyState key={note}>
              {note === "no_requirement_source"
                ? lang === "hi"
                  ? "आवश्यकता-स्रोत दस्तावेज़ अपलोड करें।"
                  : "Upload a requirement-source document."
                : note === "no_requirements_found"
                  ? lang === "hi"
                    ? "आवश्यकता-स्रोत में कोई संख्यात्मक सीमा नहीं मिली।"
                    : "No numeric limits were found in the requirement source."
                  : note === "no_product_documents"
                    ? lang === "hi"
                      ? "डेटाशीट या परीक्षण रिपोर्ट अपलोड करें।"
                      : "Upload a datasheet or test report."
                    : note}
            </EmptyState>
          ))}
          <div className="overflow-x-auto rounded-2xl border border-slate-200 bg-white shadow-sm">
            <table className="min-w-full text-left text-sm">
              <thead className="bg-slate-50 text-xs text-slate-600">
                <tr>
                  <th className="px-4 py-3 font-medium">{lang === "hi" ? "स्थिति" : "Status"}</th>
                  <th className="px-4 py-3 font-medium">{lang === "hi" ? "पैरामीटर" : "Parameter"}</th>
                  <th className="px-4 py-3 font-medium">{lang === "hi" ? "आवश्यकता (स्रोत)" : "Requirement (source)"}</th>
                  <th className="px-4 py-3 font-medium">{lang === "hi" ? "उत्पाद मान (स्रोत)" : "Product value (source)"}</th>
                  <th className="px-4 py-3 font-medium">{lang === "hi" ? "व्याख्या" : "Explanation"}</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-slate-100">
                {rows.map((row, index) => (
                  <tr key={index} className="align-top">
                    <td className="px-4 py-3">
                      <StatusChip status={row.status} />
                    </td>
                    <td className="px-4 py-3 font-medium text-ink-900">{row.requirement.parameter}</td>
                    <td className="px-4 py-3">
                      <span className="font-mono">{limit(row.requirement)}</span>
                      <span className="mt-1 block text-xs text-slate-500">
                        {row.requirement.document} · p. {row.requirement.page}
                        {row.requirement.clause ? ` · ${lang === "hi" ? "खंड" : "clause"} ${row.requirement.clause}` : ""}
                      </span>
                      <q className="mt-1 block text-xs text-slate-600">{row.requirement.raw_text}</q>
                    </td>
                    <td className="px-4 py-3">
                      {row.value ? (
                        <>
                          <span className="font-mono">{shown(row.value)}</span>
                          <span className="mt-1 block text-xs text-slate-500">
                            {row.value.role === "test_report" ? t("gap.report") : t("gap.datasheet")} · {row.value.document} · p. {row.value.page}
                          </span>
                          <q className="mt-1 block text-xs text-slate-600">{row.value.raw_text}</q>
                        </>
                      ) : (
                        <span className="text-slate-400">—</span>
                      )}
                    </td>
                    <td className="px-4 py-3 text-slate-700">{lang === "hi" ? explanationHi(row) : row.explanation}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
          <p className="text-xs text-slate-500">
            {lang === "hi"
              ? "“गैर-अनुरूपता संकेत” कोई प्रमाणन निर्णय नहीं है; अंतिम निर्णय BIS प्रक्रिया और मान्यता प्राप्त प्रयोगशाला परीक्षण से होता है।"
              : "A “non-conformity indication” is not a certification decision; conformity is established through the BIS process and recognised laboratory testing."}
          </p>
        </section>
      )}
    </div>
  );
}
