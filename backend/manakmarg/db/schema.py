"""Normalized relational schema (SQLAlchemy Core).

Only portable column types are used so the schema can move to PostgreSQL; the SQLite-specific
FTS5 tables live in ``manakmarg.db.fts``. Timestamps are ISO-8601 strings with UTC offsets because
SQLite has no timezone-aware datetime type. Calendar dates (validity, publication, enforcement)
use ``Date``.

Domain tables carry provenance columns (see ``_provenance``) so every record can be traced to a
registered source, the ingestion run that last touched it, and a locator inside that source.
"""

import sqlalchemy as sa

metadata = sa.MetaData()


def _provenance() -> list[sa.Column]:
    return [
        sa.Column("source_id", sa.String(80), sa.ForeignKey("source.source_id"), nullable=False),
        sa.Column("run_id", sa.Integer, sa.ForeignKey("ingestion_run.run_id")),
        sa.Column("source_locator", sa.Text),
        sa.Column("retrieved_at", sa.String(40)),
        sa.Column("record_hash", sa.String(64)),
        sa.Column("first_seen_run", sa.Integer),
        sa.Column("last_seen_run", sa.Integer),
        sa.Column("is_current", sa.Boolean, nullable=False, server_default=sa.true()),
    ]


# --------------------------------------------------------------------------- provenance & runs

source = sa.Table(
    "source",
    metadata,
    sa.Column("source_id", sa.String(80), primary_key=True),
    sa.Column("name", sa.Text, nullable=False),
    sa.Column("publisher", sa.Text),
    sa.Column("domain", sa.Text),
    sa.Column("url", sa.Text),
    sa.Column("source_type", sa.String(40)),
    sa.Column("purpose", sa.Text),
    sa.Column("ingestion_method", sa.Text),
    sa.Column("authority", sa.String(40)),
    sa.Column("access_status", sa.String(40)),
    sa.Column("document_type", sa.String(60)),
    sa.Column("copyright_notes", sa.Text),
    sa.Column("access_notes", sa.Text),
    sa.Column("as_of_label", sa.Text),
    sa.Column("last_checked", sa.String(40)),
)

ingestion_run = sa.Table(
    "ingestion_run",
    metadata,
    sa.Column("run_id", sa.Integer, primary_key=True, autoincrement=True),
    sa.Column("source_id", sa.String(80), sa.ForeignKey("source.source_id"), nullable=False),
    sa.Column("started_at", sa.String(40), nullable=False),
    sa.Column("completed_at", sa.String(40)),
    sa.Column("status", sa.String(20), nullable=False, server_default="running"),
    sa.Column("records_seen", sa.Integer, nullable=False, server_default="0"),
    sa.Column("inserted", sa.Integer, nullable=False, server_default="0"),
    sa.Column("updated", sa.Integer, nullable=False, server_default="0"),
    sa.Column("unchanged", sa.Integer, nullable=False, server_default="0"),
    sa.Column("retired", sa.Integer, nullable=False, server_default="0"),
    sa.Column("rejected", sa.Integer, nullable=False, server_default="0"),
    sa.Column("errors_json", sa.Text),
    sa.Column("notes", sa.Text),
    sa.Column("code_version", sa.String(20)),
)

raw_artifact = sa.Table(
    "raw_artifact",
    metadata,
    sa.Column("artifact_id", sa.Integer, primary_key=True),
    sa.Column("source_id", sa.String(80), sa.ForeignKey("source.source_id"), nullable=False),
    sa.Column("run_id", sa.Integer, sa.ForeignKey("ingestion_run.run_id")),
    sa.Column("uri", sa.Text, nullable=False),
    sa.Column("local_path", sa.Text),
    sa.Column("retrieved_at", sa.String(40)),
    sa.Column("http_status", sa.Integer),
    sa.Column("content_type", sa.String(120)),
    sa.Column("bytes", sa.Integer),
    sa.Column("sha256", sa.String(64)),
    sa.Column("from_cache", sa.Boolean),
)

document = sa.Table(
    "document",
    metadata,
    sa.Column("document_id", sa.Integer, primary_key=True),
    sa.Column("url", sa.Text, nullable=False, unique=True),
    sa.Column("source_page_url", sa.Text),
    sa.Column("title", sa.Text),
    sa.Column("doc_type", sa.String(40), nullable=False),
    sa.Column("language", sa.String(20)),
    sa.Column("doc_date", sa.Date),
    sa.Column("sha256", sa.String(64)),
    sa.Column("pages", sa.Integer),
    sa.Column("http_status", sa.Integer),
    sa.Column("text_status", sa.String(30), nullable=False, server_default="metadata_only"),
    sa.Column("local_path", sa.Text),
    sa.Column("notes", sa.Text),
    *_provenance(),
)

document_chunk = sa.Table(
    "document_chunk",
    metadata,
    sa.Column("chunk_id", sa.Integer, primary_key=True),
    sa.Column(
        "document_id",
        sa.Integer,
        sa.ForeignKey("document.document_id", ondelete="CASCADE"),
        nullable=False,
    ),
    sa.Column("ordinal", sa.Integer, nullable=False),
    sa.Column("page_start", sa.Integer),
    sa.Column("page_end", sa.Integer),
    sa.Column("section_key", sa.String(60)),
    sa.Column("heading", sa.Text),
    sa.Column("text", sa.Text, nullable=False),
    sa.UniqueConstraint("document_id", "ordinal"),
)

# --------------------------------------------------------------------------- standards

standard = sa.Table(
    "standard",
    metadata,
    sa.Column("standard_id", sa.Integer, primary_key=True),
    sa.Column("std_key", sa.String(160), nullable=False, unique=True),
    sa.Column("family_key", sa.String(160), nullable=False),
    sa.Column("match_key", sa.String(160), nullable=False),
    sa.Column("number_key", sa.String(40), nullable=False),
    sa.Column("designation_raw", sa.Text, nullable=False),
    sa.Column("prefix", sa.String(40)),
    sa.Column("number", sa.String(40)),
    sa.Column("part", sa.String(40)),
    sa.Column("section", sa.String(40)),
    sa.Column("subsection", sa.String(40)),
    sa.Column("year", sa.Integer),
    sa.Column("suffix", sa.String(40)),
    sa.Column("title", sa.Text, nullable=False),
    sa.Column("title_clean", sa.Text),
    sa.Column("revision_label", sa.String(60)),
    sa.Column("amendment_label", sa.String(60)),
    sa.Column("publication_date", sa.Date),
    sa.Column("publication_date_raw", sa.String(40)),
    sa.Column("standard_type", sa.String(60)),
    sa.Column("degree_of_equivalence", sa.String(60)),
    sa.Column("listing_status", sa.String(40), nullable=False),
    sa.Column("in_master_export", sa.Boolean, nullable=False, server_default=sa.false()),
    sa.Column("in_second_export", sa.Boolean, nullable=False, server_default=sa.false()),
    sa.Column("quality_flags", sa.Text),
    *_provenance(),
)
sa.Index("ix_standard_family_key", standard.c.family_key)
sa.Index("ix_standard_match_key", standard.c.match_key)
sa.Index("ix_standard_number_key", standard.c.number_key)

standard_alias = sa.Table(
    "standard_alias",
    metadata,
    sa.Column("alias_id", sa.Integer, primary_key=True),
    sa.Column("raw_text", sa.Text, nullable=False),
    sa.Column("context", sa.String(60), nullable=False),
    sa.Column("normalized_key", sa.String(160)),
    sa.Column("resolution", sa.String(40), nullable=False),
    sa.Column("standard_id", sa.Integer, sa.ForeignKey("standard.standard_id")),
    sa.Column("family_key", sa.String(160)),
    *_provenance(),
    sa.UniqueConstraint("raw_text", "context"),
)
sa.Index("ix_standard_alias_standard_id", standard_alias.c.standard_id)

classification_node = sa.Table(
    "classification_node",
    metadata,
    sa.Column("node_id", sa.Integer, primary_key=True),
    sa.Column("dimension", sa.String(20), nullable=False),
    sa.Column("name", sa.Text, nullable=False),
    sa.Column("parent_node_id", sa.Integer, sa.ForeignKey("classification_node.node_id")),
    sa.Column("export_label", sa.Text, nullable=False),
    *_provenance(),
    sa.UniqueConstraint("dimension", "export_label"),
)

standard_classification = sa.Table(
    "standard_classification",
    metadata,
    sa.Column("standard_id", sa.Integer, sa.ForeignKey("standard.standard_id"), primary_key=True),
    sa.Column("node_id", sa.Integer, sa.ForeignKey("classification_node.node_id"), primary_key=True),
    *_provenance(),
)

standard_relation = sa.Table(
    "standard_relation",
    metadata,
    sa.Column("relation_id", sa.Integer, primary_key=True),
    sa.Column("from_standard_id", sa.Integer, sa.ForeignKey("standard.standard_id"), nullable=False),
    sa.Column("to_standard_id", sa.Integer, sa.ForeignKey("standard.standard_id")),
    sa.Column("to_ref_text", sa.Text),
    sa.Column("relation_type", sa.String(60), nullable=False),
    sa.Column("basis", sa.String(40), nullable=False),
    sa.Column("evidence_text", sa.Text),
    *_provenance(),
)
sa.Index("ix_standard_relation_from", standard_relation.c.from_standard_id)

# --------------------------------------------------------------------------- compulsory certification

certification_scheme = sa.Table(
    "certification_scheme",
    metadata,
    sa.Column("scheme_id", sa.String(20), primary_key=True),
    sa.Column("name", sa.Text, nullable=False),
    sa.Column("short_name", sa.String(40)),
    sa.Column("official_description", sa.Text),
    sa.Column("conformity_mark", sa.Text),
    sa.Column("official_url", sa.Text),
    *_provenance(),
)

regulatory_order = sa.Table(
    "regulatory_order",
    metadata,
    sa.Column("order_id", sa.Integer, primary_key=True),
    sa.Column("order_key", sa.Text, nullable=False, unique=True),
    sa.Column("title", sa.Text, nullable=False),
    sa.Column("url", sa.Text),
    sa.Column("order_kind", sa.String(30), nullable=False),
    sa.Column("so_number", sa.String(40)),
    sa.Column("gsr_number", sa.String(40)),
    sa.Column("order_date", sa.Date),
    sa.Column("order_date_raw", sa.String(60)),
    sa.Column("issuing_authority", sa.Text),
    sa.Column("document_id", sa.Integer, sa.ForeignKey("document.document_id")),
    sa.Column("raw_text", sa.Text),
    *_provenance(),
)

scheme_coverage = sa.Table(
    "scheme_coverage",
    metadata,
    sa.Column("coverage_id", sa.Integer, primary_key=True),
    sa.Column("coverage_key", sa.String(64), nullable=False, unique=True),
    sa.Column("scheme_id", sa.String(20), sa.ForeignKey("certification_scheme.scheme_id")),
    sa.Column("page_kind", sa.String(30), nullable=False),
    sa.Column("section_label", sa.Text),
    sa.Column("category", sa.Text),
    sa.Column("sr_no_raw", sa.String(40)),
    sa.Column("product_name", sa.Text, nullable=False),
    sa.Column("parent_coverage_id", sa.Integer, sa.ForeignKey("scheme_coverage.coverage_id")),
    sa.Column("standard_ref_raw", sa.Text),
    sa.Column("standard_title_raw", sa.Text),
    sa.Column("product_category", sa.Text),
    sa.Column("essential_requirement", sa.Text),
    sa.Column("specific_requirement", sa.Text),
    sa.Column("notification_text_raw", sa.Text),
    sa.Column("listing_status", sa.String(30), nullable=False),
    sa.Column("status_basis", sa.Text),
    sa.Column("ministry_department", sa.Text),
    sa.Column("enforcement_date", sa.Date),
    sa.Column("enforcement_date_raw", sa.String(60)),
    sa.Column("notes", sa.Text),
    *_provenance(),
)
sa.Index("ix_scheme_coverage_scheme", scheme_coverage.c.scheme_id)

coverage_standard = sa.Table(
    "coverage_standard",
    metadata,
    sa.Column(
        "coverage_id",
        sa.Integer,
        sa.ForeignKey("scheme_coverage.coverage_id", ondelete="CASCADE"),
        primary_key=True,
    ),
    sa.Column("ordinal", sa.Integer, primary_key=True),
    sa.Column("ref_raw", sa.Text, nullable=False),
    sa.Column("family_key", sa.String(160)),
    sa.Column("standard_id", sa.Integer, sa.ForeignKey("standard.standard_id")),
    sa.Column("resolution", sa.String(40), nullable=False),
    sa.Column("role", sa.String(40), nullable=False, server_default="specified"),
)
sa.Index("ix_coverage_standard_family", coverage_standard.c.family_key)

coverage_order = sa.Table(
    "coverage_order",
    metadata,
    sa.Column(
        "coverage_id",
        sa.Integer,
        sa.ForeignKey("scheme_coverage.coverage_id", ondelete="CASCADE"),
        primary_key=True,
    ),
    sa.Column("order_id", sa.Integer, sa.ForeignKey("regulatory_order.order_id"), primary_key=True),
    sa.Column("ordinal", sa.Integer, nullable=False),
    sa.Column("relation", sa.String(30)),
)

product_term = sa.Table(
    "product_term",
    metadata,
    sa.Column("term_id", sa.Integer, primary_key=True),
    sa.Column("term", sa.Text, nullable=False),
    sa.Column("term_norm", sa.Text, nullable=False),
    sa.Column("origin", sa.String(40), nullable=False),
    sa.Column("coverage_id", sa.Integer, sa.ForeignKey("scheme_coverage.coverage_id", ondelete="CASCADE")),
    sa.Column("standard_id", sa.Integer, sa.ForeignKey("standard.standard_id")),
    sa.Column("guideline_id", sa.Integer, sa.ForeignKey("product_guideline.guideline_id")),
    sa.Column("weight", sa.Float, nullable=False, server_default="1.0"),
)
sa.Index("ix_product_term_norm", product_term.c.term_norm)

# --------------------------------------------------------------------------- guidelines & process

product_guideline = sa.Table(
    "product_guideline",
    metadata,
    sa.Column("guideline_id", sa.Integer, primary_key=True),
    sa.Column("guideline_key", sa.String(64), nullable=False, unique=True),
    sa.Column("url", sa.Text, nullable=False),
    sa.Column("is_ref_raw", sa.Text, nullable=False),
    sa.Column("family_key", sa.String(160)),
    sa.Column("standard_id", sa.Integer, sa.ForeignKey("standard.standard_id")),
    sa.Column("resolution", sa.String(40)),
    sa.Column("title", sa.Text, nullable=False),
    sa.Column("doc_kind", sa.String(40), nullable=False),
    sa.Column("size_text", sa.String(30)),
    sa.Column("format_text", sa.String(60)),
    sa.Column("document_id", sa.Integer, sa.ForeignKey("document.document_id")),
    sa.Column("parse_status", sa.String(30), nullable=False, server_default="metadata_only"),
    *_provenance(),
)
sa.Index("ix_product_guideline_family", product_guideline.c.family_key)

guideline_section = sa.Table(
    "guideline_section",
    metadata,
    sa.Column("section_id", sa.Integer, primary_key=True),
    sa.Column(
        "guideline_id",
        sa.Integer,
        sa.ForeignKey("product_guideline.guideline_id", ondelete="CASCADE"),
        nullable=False,
    ),
    sa.Column("ordinal", sa.Integer, nullable=False),
    sa.Column("section_key", sa.String(60), nullable=False),
    sa.Column("heading", sa.Text),
    sa.Column("page_start", sa.Integer),
    sa.Column("page_end", sa.Integer),
    sa.Column("text", sa.Text, nullable=False),
    sa.Column("structured_json", sa.Text),
    sa.UniqueConstraint("guideline_id", "ordinal"),
)

process_step = sa.Table(
    "process_step",
    metadata,
    sa.Column("step_id", sa.Integer, primary_key=True),
    sa.Column("scheme_id", sa.String(20), sa.ForeignKey("certification_scheme.scheme_id")),
    sa.Column("ordinal", sa.Integer, nullable=False),
    sa.Column("step_label", sa.String(20)),
    sa.Column("text", sa.Text, nullable=False),
    sa.Column("link_url", sa.Text),
    sa.Column("link_label", sa.Text),
    *_provenance(),
)

scheme_document = sa.Table(
    "scheme_document",
    metadata,
    sa.Column("scheme_doc_id", sa.Integer, primary_key=True),
    sa.Column("scheme_id", sa.String(20), sa.ForeignKey("certification_scheme.scheme_id")),
    sa.Column("ordinal", sa.Integer, nullable=False),
    sa.Column("title", sa.Text, nullable=False),
    sa.Column("url", sa.Text),
    sa.Column("size_text", sa.String(30)),
    sa.Column("category", sa.String(40)),
    *_provenance(),
)

# --------------------------------------------------------------------------- laboratories

laboratory = sa.Table(
    "laboratory",
    metadata,
    sa.Column("lab_id", sa.Integer, primary_key=True),
    sa.Column("lab_key", sa.String(200), nullable=False, unique=True),
    sa.Column("osl_code", sa.String(20)),
    sa.Column("lims_lab_id", sa.Integer),
    sa.Column("name", sa.Text, nullable=False),
    sa.Column("lab_category", sa.String(30), nullable=False),
    sa.Column("address_raw", sa.Text),
    sa.Column("city", sa.Text),
    sa.Column("district", sa.Text),
    sa.Column("state", sa.Text),
    sa.Column("pincode", sa.String(10)),
    sa.Column("org_phone", sa.String(80)),
    sa.Column("org_email", sa.String(200)),
    sa.Column("lims_validity_date", sa.Date),
    sa.Column("lims_validity_raw", sa.String(40)),
    *_provenance(),
)
sa.Index("ix_laboratory_osl_code", laboratory.c.osl_code)

lab_list_entry = sa.Table(
    "lab_list_entry",
    metadata,
    sa.Column("entry_id", sa.Integer, primary_key=True),
    sa.Column("entry_key", sa.String(120), nullable=False, unique=True),
    sa.Column("group_no", sa.Integer, nullable=False),
    sa.Column("osl_code", sa.String(20)),
    sa.Column("name_raw", sa.Text, nullable=False),
    sa.Column("state_raw", sa.Text),
    sa.Column("state", sa.Text),
    sa.Column("ownership", sa.String(20)),
    sa.Column("valid_upto", sa.Date),
    sa.Column("valid_upto_raw", sa.String(40)),
    sa.Column("remarks_raw", sa.Text),
    sa.Column("derived_status", sa.String(30)),
    sa.Column("status_basis", sa.Text),
    sa.Column("list_as_of", sa.String(40)),
    *_provenance(),
)
sa.Index("ix_lab_list_entry_osl_code", lab_list_entry.c.osl_code)

lab_scope = sa.Table(
    "lab_scope",
    metadata,
    sa.Column("scope_id", sa.Integer, primary_key=True),
    sa.Column("scope_key", sa.String(64), nullable=False, unique=True),
    sa.Column("lab_id", sa.Integer, sa.ForeignKey("laboratory.lab_id")),
    sa.Column("lab_name_raw", sa.Text, nullable=False),
    sa.Column("osl_code_raw", sa.String(20)),
    sa.Column("is_ref_raw", sa.Text, nullable=False),
    sa.Column("family_key", sa.String(160)),
    sa.Column("standard_id", sa.Integer, sa.ForeignKey("standard.standard_id")),
    sa.Column("version_year", sa.Integer),
    sa.Column("product", sa.Text),
    sa.Column("grade_type", sa.Text),
    sa.Column("charges_total", sa.Float),
    sa.Column("charges_raw", sa.String(40)),
    sa.Column("validity_date", sa.Date),
    sa.Column("validity_raw", sa.String(40)),
    sa.Column("remark_raw", sa.Text),
    sa.Column("exclusions_text", sa.Text),
    sa.Column("scope_file_url", sa.Text),
    sa.Column("query_doc_no", sa.String(40)),
    *_provenance(),
)
sa.Index("ix_lab_scope_family", lab_scope.c.family_key)

lab_scope_item = sa.Table(
    "lab_scope_item",
    metadata,
    sa.Column("item_id", sa.Integer, primary_key=True),
    sa.Column("scope_id", sa.Integer, sa.ForeignKey("lab_scope.scope_id", ondelete="CASCADE"), nullable=False),
    sa.Column("ordinal", sa.Integer, nullable=False),
    sa.Column("clause", sa.Text),
    sa.Column("parameter", sa.Text),
    sa.Column("exclusion", sa.Text),
    sa.Column("charge", sa.Float),
    sa.Column("charge_raw", sa.String(40)),
    sa.Column("effective_date_raw", sa.String(40)),
    sa.Column("remark", sa.Text),
    sa.UniqueConstraint("scope_id", "ordinal"),
)

# --------------------------------------------------------------------------- hallmarking

ahc = sa.Table(
    "ahc",
    metadata,
    sa.Column("ahc_id", sa.Integer, primary_key=True),
    sa.Column("recognition_no", sa.String(60), nullable=False, unique=True),
    sa.Column("region_code", sa.String(10)),
    sa.Column("name", sa.Text, nullable=False),
    sa.Column("address_raw", sa.Text),
    sa.Column("district", sa.Text),
    sa.Column("area", sa.Text),
    sa.Column("state", sa.Text),
    sa.Column("pincode", sa.String(10)),
    sa.Column("scope_text", sa.Text),
    sa.Column("gold", sa.Boolean),
    sa.Column("silver", sa.Boolean),
    sa.Column("validity_date", sa.Date),
    sa.Column("validity_raw", sa.String(40)),
    sa.Column("list_status_raw", sa.String(60)),
    sa.Column("org_phone", sa.String(80)),
    sa.Column("org_email", sa.String(200)),
    *_provenance(),
)
sa.Index("ix_ahc_state_district", ahc.c.state, ahc.c.district)

ahc_status_event = sa.Table(
    "ahc_status_event",
    metadata,
    sa.Column("event_id", sa.Integer, primary_key=True),
    sa.Column("event_key", sa.String(160), nullable=False, unique=True),
    sa.Column("recognition_no", sa.String(60), nullable=False),
    sa.Column("status", sa.String(40), nullable=False),
    sa.Column("event_date", sa.Date),
    sa.Column("event_date_raw", sa.String(40)),
    sa.Column("region", sa.String(10)),
    sa.Column("center_type", sa.String(20)),
    sa.Column("name_address_raw", sa.Text),
    *_provenance(),
)
sa.Index("ix_ahc_status_event_recognition_no", ahc_status_event.c.recognition_no)

hallmarking_district = sa.Table(
    "hallmarking_district",
    metadata,
    sa.Column("district_id", sa.Integer, primary_key=True),
    sa.Column("district_key", sa.String(200), nullable=False, unique=True),
    sa.Column("sr_no", sa.Integer),
    sa.Column("state_raw", sa.Text, nullable=False),
    sa.Column("state", sa.Text, nullable=False),
    sa.Column("district_raw", sa.Text, nullable=False),
    sa.Column("district", sa.Text, nullable=False),
    sa.Column("district_norm", sa.Text, nullable=False),
    sa.Column("phase_no", sa.Integer),
    sa.Column("phase_label", sa.Text),
    sa.Column("phase_order_date", sa.Date),
    sa.Column("phase_order_date_raw", sa.String(60)),
    sa.Column("gazette_validated", sa.Boolean),
    sa.Column("gazette_note", sa.Text),
    *_provenance(),
)
sa.Index("ix_hallmarking_district_norm", hallmarking_district.c.district_norm)

district_alias = sa.Table(
    "district_alias",
    metadata,
    sa.Column("alias_id", sa.Integer, primary_key=True),
    sa.Column("alias_norm", sa.Text, nullable=False),
    sa.Column(
        "district_id",
        sa.Integer,
        sa.ForeignKey("hallmarking_district.district_id", ondelete="CASCADE"),
        nullable=False,
    ),
    sa.Column("basis", sa.String(40), nullable=False),
    sa.UniqueConstraint("alias_norm", "district_id"),
)

jeweller = sa.Table(
    "jeweller",
    metadata,
    sa.Column("jeweller_id", sa.Integer, primary_key=True),
    sa.Column("licence_no", sa.String(60), nullable=False, unique=True),
    sa.Column("name", sa.Text, nullable=False),
    sa.Column("outlet_address", sa.Text),
    sa.Column("district", sa.Text),
    sa.Column("state", sa.Text),
    sa.Column("is_no", sa.String(20)),
    sa.Column("status", sa.String(40)),
    *_provenance(),
)

# --------------------------------------------------------------------------- knowledge

faq = sa.Table(
    "faq",
    metadata,
    sa.Column("faq_id", sa.Integer, primary_key=True),
    sa.Column("faq_key", sa.String(64), nullable=False, unique=True),
    sa.Column("category", sa.String(60), nullable=False),
    sa.Column("ordinal", sa.Integer, nullable=False),
    sa.Column("question", sa.Text, nullable=False),
    sa.Column("answer", sa.Text, nullable=False),
    sa.Column("answer_links", sa.Text),
    sa.Column("language", sa.String(10), nullable=False, server_default="en"),
    sa.Column("source_url", sa.Text),
    *_provenance(),
)

# --------------------------------------------------------------------------- HSN classification lookup

hsn_code = sa.Table(
    "hsn_code",
    metadata,
    sa.Column("hsn_id", sa.Integer, primary_key=True),
    sa.Column("code", sa.String(16), nullable=False, unique=True),  # exactly as written in the workbook
    sa.Column("code_digits", sa.String(16), nullable=False, index=True),  # digits only, for lookup
    sa.Column("code_length", sa.Integer, nullable=False),
    sa.Column("description", sa.Text, nullable=False),  # verbatim, never rewritten
    sa.Column("sheet_row", sa.Integer),
    *_provenance(),
)
