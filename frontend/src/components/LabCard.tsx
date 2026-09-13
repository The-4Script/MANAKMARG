import { BadgeCheck, MapPin, Phone } from "lucide-react";
import { useState } from "react";
import type { LabMatch } from "../api/types";
import { useI18n } from "../i18n/I18nProvider";
import { EvidenceRefs } from "./evidence";
import { Card, Chip, formatDate, Id, StatusChip } from "./ui";

const CATEGORY: Record<string, [string, string]> = {
  BIS_LAB: ["BIS laboratory", "BIS प्रयोगशाला"],
  BIS_RECOGNISED: ["BIS recognised", "BIS मान्यता प्राप्त"],
  GOVT_EMPANELLED: ["Govt. empanelled", "सरकारी सूचीबद्ध"],
};

export default function LabCard({ lab, compact = false }: { lab: LabMatch; compact?: boolean }) {
  const { t, lang } = useI18n();
  const [showTests, setShowTests] = useState(false);
  const category = lab.lab_category ? CATEGORY[lab.lab_category] : null;
  return (
    <Card as="article" className="p-5">
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div className="min-w-0">
          <h3 className="font-semibold text-ink-900">{lab.lab_name}</h3>
          <div className="mt-1 flex flex-wrap items-center gap-2 text-xs text-slate-600">
            {category && <Chip tone="indigo">{lang === "hi" ? category[1] : category[0]}</Chip>}
            {lab.osl_code && (
              <span>
                OSL <Id>{lab.osl_code}</Id>
              </span>
            )}
            {!(lab.status === "BIS_LAB" && lab.lab_category === "BIS_LAB") && <StatusChip status={lab.status} />}
          </div>
        </div>
        <EvidenceRefs ids={lab.evidence_ids} />
      </div>

      <div className="mt-3 grid gap-2 text-sm text-slate-700 sm:grid-cols-2">
        <p className="flex gap-2">
          <MapPin className="mt-0.5 size-4 shrink-0 text-slate-400" aria-hidden />
          <span>{[lab.city, lab.district, lab.state, lab.pincode].filter(Boolean).join(", ") || "—"}</span>
        </p>
        {!compact && (lab.org_phone || lab.org_email) && (
          <p className="flex gap-2">
            <Phone className="mt-0.5 size-4 shrink-0 text-slate-400" aria-hidden />
            <span className="break-all">{[lab.org_phone, lab.org_email].filter(Boolean).join(" · ")}</span>
          </p>
        )}
      </div>

      <dl className="mt-3 grid gap-x-6 gap-y-1.5 text-sm sm:grid-cols-2">
        <div>
          <dt className="text-xs text-slate-500">IS</dt>
          <dd className="flex flex-wrap items-center gap-2">
            <Id>{lab.is_ref_raw}</Id>
            {lab.version_in_published_list && (
              <span className="inline-flex items-center gap-1 text-xs text-emerald-700">
                <BadgeCheck className="size-3.5" aria-hidden /> {lang === "hi" ? "प्रकाशित सूची में संस्करण" : "version in published list"}
              </span>
            )}
          </dd>
        </div>
        <div>
          <dt className="text-xs text-slate-500">{t("common.validUntil")}</dt>
          <dd>{formatDate(lab.validity_date, lang)}</dd>
        </div>
        {lab.product && (
          <div className="sm:col-span-2">
            <dt className="text-xs text-slate-500">{lang === "hi" ? "उत्पाद" : "Product"}</dt>
            <dd>{lab.product}</dd>
          </div>
        )}
        {!compact && lab.grade_type && (
          <div>
            <dt className="text-xs text-slate-500">{lang === "hi" ? "ग्रेड / प्रकार" : "Grade / type"}</dt>
            <dd>{lab.grade_type}</dd>
          </div>
        )}
        {!compact && lab.charges_total != null && (
          <div>
            <dt className="text-xs text-slate-500">{t("labs.charges")}</dt>
            <dd className="tabular-nums">₹{lab.charges_total.toLocaleString("en-IN")}</dd>
          </div>
        )}
        {lab.remark && (
          <div className="sm:col-span-2">
            <dt className="text-xs text-slate-500">{lang === "hi" ? "टिप्पणी (LIMS)" : "Remark (LIMS)"}</dt>
            <dd>{lab.remark}</dd>
          </div>
        )}
      </dl>

      {lab.exclusions && (
        <p className="mt-3 rounded-lg bg-amber-50 px-3 py-2 text-sm text-amber-950">
          <strong>{t("labs.exclusions")}:</strong> {lab.exclusions}
        </p>
      )}
      {!compact && lab.status_reasons.length > 0 && <p className="mt-2 text-xs text-slate-500">{lab.status_reasons.join(" ")}</p>}

      {!compact && lab.test_count > 0 && (
        <div className="mt-3">
          <button className="text-sm font-medium text-ink-700 hover:underline" onClick={() => setShowTests((value) => !value)}>
            {t("labs.tests")} ({lab.test_count}) {showTests ? "▴" : "▾"}
          </button>
          {showTests && (
            <ul className="mt-2 grid gap-1 text-xs text-slate-700 sm:grid-cols-2">
              {lab.tests.map((test, index) => (
                <li key={index} className="rounded bg-slate-50 px-2 py-1">
                  {test}
                </li>
              ))}
              {lab.test_count > lab.tests.length && <li className="px-2 py-1 text-slate-500">+{lab.test_count - lab.tests.length}</li>}
            </ul>
          )}
        </div>
      )}
    </Card>
  );
}
