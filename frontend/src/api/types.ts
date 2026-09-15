// Response shapes of the MANAK MARG API (mirrors the backend dataclasses serialised by FastAPI).

export type Evidence = {
  id: string;
  kind: string;
  title: string;
  snippet: string | null;
  source_id: string;
  source_name: string;
  authority: string;
  url: string | null;
  locator: string | null;
  retrieved_at: string | null;
  page: number | null;
  clause: string | null;
  record_id: string | null;
  /** Official-source action for this evidence (only for official BIS/Gazette URLs), e.g. "view_notification". */
  action?: string | null;
};

export type SourceRollup = {
  source_id: string;
  name: string;
  authority: string;
  url: string | null;
  as_of: string | null;
  evidence_ids: string[];
  retrieved_at: string[];
};

export type WithEvidence = { evidence: Evidence[]; sources: SourceRollup[] };

export type Limitation = { key: string; en: string; hi: string };

export type Meta = {
  version: string;
  llm_enabled: boolean;
  checked_on: string;
  counts: Record<string, number>;
  as_of: Record<string, string | null>;
  limitations: Limitation[];
  upload_ttl_minutes: number;
  voice_enabled?: boolean;
  voice_max_mb?: number;
  ai_usage?: Record<string, number>;
};

export type Understanding = {
  text: string;
  language: string;
  intent: string;
  intents: string[];
  standard_refs: string[];
  doc_numbers: string[];
  recognition_nos: string[];
  so_numbers: string[];
  state: string | null;
  district: string | null;
  district_state: string | null;
  city: string | null;
  metal: string | null;
  product_text: string | null;
  confidence: number;
};

export type CoverageCandidate = {
  coverage_id: number;
  product_name: string;
  category: string | null;
  scheme_id: string | null;
  page_kind: string;
  listing_status: string;
  standard_ref_raw: string | null;
  parent_coverage_id: number | null;
  score: number;
  token_coverage: number;
  matched_via: string[];
};

export type StandardCandidate = {
  standard_id: number;
  std_key: string;
  title: string;
  standard_type: string | null;
  score: number;
  matched_via: string[];
};

export type StandardLink = {
  ref_raw: string;
  role: string;
  resolution: string;
  family_key: string | null;
  standard_id: number | null;
  std_key: string | null;
  title: string | null;
  evidence_id: string | null;
};

export type OrderView = {
  order_id: number;
  title: string;
  kind: string;
  so_number: string | null;
  gsr_number: string | null;
  order_date: string | null;
  url: string | null;
  text_indexed: boolean;
  evidence_id: string;
};

export type ListingView = {
  coverage_id: number;
  scheme_id: string | null;
  scheme_name: string | null;
  page_kind: string;
  section_label: string | null;
  category: string | null;
  product_name: string;
  parent_coverage_id: number | null;
  parent_product_name: string | null;
  listing_status: string;
  status_basis: string | null;
  effect: string;
  days_to_enforcement: number | null;
  enforcement_date: string | null;
  enforcement_date_raw: string | null;
  ministry_department: string | null;
  essential_requirement: string | null;
  specific_requirement: string | null;
  notification_text: string | null;
  standards: StandardLink[];
  orders: OrderView[];
  page_url: string | null;
  retrieved_at: string | null;
  evidence_id: string;
  token_coverage: number | null;
  matched_via: string[];
};

export type IdentifierView = {
  ref_raw: string;
  kind: string;
  std_key: string | null;
  family_key: string | null;
  standard_ids: number[];
  note: string;
};

export type AssessmentView = {
  label: string;
  compulsory: string;
  basis: string;
  listings: ListingView[];
  candidates: CoverageCandidate[];
  standards: StandardCandidate[];
  identifiers: IdentifierView[];
  synonyms_used: [string, string][];
  caveats: string[];
  checked_on: string;
};

export type LabMatch = {
  scope_id: number;
  lab_id: number | null;
  lab_name: string;
  lab_category: string | null;
  osl_code: string | null;
  address: string | null;
  city: string | null;
  district: string | null;
  state: string | null;
  pincode: string | null;
  org_phone: string | null;
  org_email: string | null;
  is_ref_raw: string;
  family_key: string | null;
  version_year: number | null;
  version_in_published_list: boolean;
  product: string | null;
  grade_type: string | null;
  charges_total: number | null;
  validity_date: string | null;
  remark: string | null;
  exclusions: string | null;
  tests: string[];
  test_count: number;
  status: string;
  status_reasons: string[];
  location_match: string;
  evidence_ids: string[];
};

export type LabSearch = WithEvidence & {
  query: string;
  designations: string[];
  doc_numbers: string[];
  indexed_doc_numbers: string[];
  lims_search_urls: string[];
  location: { state: string | null; district: string | null; city: string | null };
  location_fallback: boolean;
  checked_on: string;
  matches: LabMatch[];
  counts: { rows?: number; by_status?: Record<string, number>; laboratories?: number };
  notes: string[];
};

export type DistrictMatch = {
  district_id: number;
  state: string;
  district: string;
  phase_no: number | null;
  phase_label: string | null;
  phase_order_date: string | null;
  phase_order_date_raw: string | null;
  gazette_validated: boolean | null;
  gazette_note: string | null;
  matched_name: string;
  match_basis: string;
  evidence_ids: string[];
};

export type DistrictCheck = WithEvidence & {
  query_district: string;
  query_state: string | null;
  status: string;
  matches: DistrictMatch[];
  suggestions: { district: string; state: string }[];
  notes: string[];
};

export type AhcView = {
  ahc_id: number;
  recognition_no: string;
  name: string;
  address: string | null;
  district: string | null;
  state: string | null;
  pincode: string | null;
  gold: boolean | null;
  silver: boolean | null;
  scope_text: string | null;
  validity_date: string | null;
  list_status_raw: string | null;
  effective_status: string;
  reasons: string[];
  org_phone: string | null;
  org_email: string | null;
  evidence_ids: string[];
};

export type AhcSearch = WithEvidence & {
  state: string | null;
  district: string | null;
  checked_on: string;
  operative: AhcView[];
  inactive: AhcView[];
  counts: Record<string, number>;
  total_operative: number;
};

export type JourneyStep = {
  key: string;
  state: "ok" | "attention" | "missing";
  // Step payloads differ per key; pages narrow them where rendered.
  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  data: Record<string, any>;
  evidence_ids: string[];
  notes: string[];
};

export type NextAction = { code: string; url?: string | null; [key: string]: unknown };

export type Journey = WithEvidence & {
  query: Record<string, string | number | null>;
  checked_on: string;
  assessment: AssessmentView;
  selected: ListingView | null;
  steps: JourneyStep[];
  next_actions: NextAction[];
};

export type AnswerItem = { text: string; evidence_ids: string[] };
export type AnswerSection = { key: string; title: string; items: AnswerItem[] };

export type AssistantResponse = WithEvidence & {
  query: string;
  lang: string;
  understanding: Understanding;
  headline: string;
  status_label: string | null;
  sections: AnswerSection[];
  caveats: string[];
  next_actions: AnswerItem[];
  follow_ups: string[];
  narrative: string | null;
  narrative_source: "template" | "llm";
  links: { label: string; to: string }[];
  headline_evidence?: string[];
  route?: { category: string; reason: string; scheme_id: string | null } | null;
};

export type SearchResponse = {
  understanding: Understanding;
  coverage: CoverageCandidate[];
  standards: StandardCandidate[];
};
