import { Link } from "react-router-dom";
import { EmptyState, PageHeader } from "../components/ui";
import { useI18n } from "../i18n/I18nProvider";

export default function NotFound() {
  const { lang } = useI18n();
  return (
    <div className="space-y-6">
      <PageHeader
        title={lang === "hi" ? "पृष्ठ नहीं मिला" : "Page not found"}
        subtitle={lang === "hi" ? "यह पता MANAK MARG में मौजूद नहीं है।" : "This address does not exist in MANAK MARG."}
      />
      <EmptyState>
        <Link to="/" className="font-medium text-ink-700 hover:underline">
          {lang === "hi" ? "मुख्य पृष्ठ पर जाएँ" : "Go to the home page"}
        </Link>
      </EmptyState>
    </div>
  );
}
