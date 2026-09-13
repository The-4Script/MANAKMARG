from datetime import date
from pathlib import Path

import pytest
import sqlalchemy as sa

from manakmarg.db import schema
from manakmarg.db.engine import get_engine, init_db
from manakmarg.ingest import sources
from manakmarg.ingest.bis_schemes import parse_scheme_i, parse_upcoming_qcos
from manakmarg.ingest.compliance_loader import load_scheme_records, retire_unlinked_orders
from manakmarg.ingest.runs import RunRecorder
from tests.standards_seed import seed_standards

FIXTURES = Path(__file__).resolve().parents[1] / "fixtures" / "bis"
SCHEME_I_URL = (
    "https://www.bis.gov.in/product-certification/products-under-compulsory-certification/scheme-i-mark-scheme/?lang=en"
)
UPCOMING_URL = "https://www.bis.gov.in/upcoming-qcos-notified-and-due-for-implementation/?lang=en"


@pytest.fixture(scope="module")
def scheme_i_records():
    return parse_scheme_i((FIXTURES / "scheme_i.html").read_bytes(), SCHEME_I_URL)


@pytest.fixture
def engine(tmp_path):
    eng = get_engine(tmp_path / "coverage.sqlite3")
    init_db(eng)
    with eng.begin() as conn:
        sources.sync_registry(conn)
        seed_standards(
            conn,
            ["IS 269:2015", "IS 14756:2024", "IS 12330:1988", "IS 302 (Part 1):2024", "IS 12795:2020", "IS 4003 (Part 1):1978"],
        )
    yield eng
    eng.dispose()


def _load_scheme_i(engine, records):
    with RunRecorder(engine, "bis_scheme_i_page") as run:
        summary = load_scheme_records(run, records, scheme_id="SCHEME_I", page_url=SCHEME_I_URL)
    return run, summary


def _coverage(conn, **criteria):
    table = schema.scheme_coverage
    query = sa.select(table)
    for column, value in criteria.items():
        query = query.where(table.c[column] == value)
    return conn.execute(query).mappings().all()


def _standard_links(conn, coverage_id):
    table = schema.coverage_standard
    return conn.execute(sa.select(table).where(table.c.coverage_id == coverage_id).order_by(table.c.ordinal)).mappings().all()


def test_scheme_row_is_seeded_with_page_provenance(engine, scheme_i_records):
    _load_scheme_i(engine, scheme_i_records)
    with engine.connect() as conn:
        scheme = conn.execute(sa.select(schema.certification_scheme)).mappings().one()
    assert scheme["scheme_id"] == "SCHEME_I"
    assert scheme["source_id"] == "bis_scheme_i_page"
    assert scheme["official_url"] == SCHEME_I_URL
    assert "use of mark" in scheme["official_description"]


def test_every_record_becomes_a_coverage_row(engine, scheme_i_records):
    run, summary = _load_scheme_i(engine, scheme_i_records)
    with engine.connect() as conn:
        count = conn.execute(sa.select(sa.func.count()).select_from(schema.scheme_coverage)).scalar()
    assert count == len(scheme_i_records)
    assert summary["coverage_rows"] == len(scheme_i_records)


def test_standard_references_are_resolved_with_explicit_kinds(engine, scheme_i_records):
    _load_scheme_i(engine, scheme_i_records)
    with engine.connect() as conn:
        cement = _coverage(conn, standard_ref_raw="IS 269", product_name="Ordinary Portland Cement")[0]
        cement_links = _standard_links(conn, cement["coverage_id"])
        cookware = _coverage(conn, standard_ref_raw="IS 14756 : 2022")[0]
        cookware_links = _standard_links(conn, cookware["coverage_id"])
        utensils_id = conn.execute(
            sa.select(schema.standard.c.standard_id).where(schema.standard.c.std_key == "IS 14756:2024")
        ).scalar()
    assert cement_links[0]["resolution"] == "family_latest"
    assert cement_links[0]["family_key"] == "IS 269"
    assert cement_links[0]["standard_id"] is not None
    assert cookware_links[0]["resolution"] == "version_not_in_master"
    assert cookware_links[0]["standard_id"] == utensils_id


def test_orders_are_stored_once_and_linked(engine, scheme_i_records):
    _load_scheme_i(engine, scheme_i_records)
    with engine.connect() as conn:
        orders = conn.execute(
            sa.select(schema.regulatory_order).where(schema.regulatory_order.c.so_number == "S.O. 191(E)")
        ).mappings().all()
        cement_rows = _coverage(conn, category="Cement (any variety of cement manufactured or sold in India) such as")
        linked = conn.execute(
            sa.select(sa.func.count())
            .select_from(schema.coverage_order)
            .where(schema.coverage_order.c.order_id == orders[0]["order_id"])
        ).scalar()
    assert len(orders) == 1
    assert orders[0]["order_kind"] == "qco"
    assert orders[0]["order_date"] == date(2003, 2, 17)
    assert linked >= len(cement_rows) > 1


def _order_titles(conn, coverage_id):
    links, orders = schema.coverage_order, schema.regulatory_order
    return conn.execute(
        sa.select(orders.c.title, orders.c.so_number, orders.c.url, orders.c.order_key)
        .select_from(links.join(orders, orders.c.order_id == links.c.order_id))
        .where(links.c.coverage_id == coverage_id)
        .order_by(links.c.ordinal)
    ).all()


def test_orders_sharing_a_pdf_url_are_not_merged(engine, scheme_i_records):
    """The BIS page links both the pressure-cooker amendment (S.O. 2019(E)) and the cables QCO (S.O. 294(E)) to
    Cables_28012020.pdf; each listing must keep its own order and the shared URL is preserved on both."""
    pdf = "https://www.bis.gov.in/wp-content/uploads/2020/01/Cables_28012020.pdf"
    _load_scheme_i(engine, scheme_i_records)
    with engine.connect() as conn:
        cable_rows = [row for row in _coverage(conn, category="Cables")]
        cooker = _coverage(conn, product_name="Domestic Pressure Cooker")[0]
        shared = conn.execute(sa.select(schema.regulatory_order).where(schema.regulatory_order.c.url == pdf)).mappings().all()
        cooker_orders = _order_titles(conn, cooker["coverage_id"])
        cable_orders = {row["coverage_id"]: _order_titles(conn, row["coverage_id"]) for row in cable_rows}
    assert {row["so_number"] for row in shared} == {"S.O. 2019(E)", "S.O. 294(E)"}
    assert len(cable_rows) == 13
    for orders in cable_orders.values():
        assert [order.so_number for order in orders] == ["S.O. 294(E)"]
        assert all("Cables" in order.title and "Pressure Cooker" not in order.title for order in orders)
        assert orders[0].url == pdf
    assert any(order.so_number == "S.O. 2019(E)" and "Pressure Cooker" in order.title for order in cooker_orders)


def test_unlinked_orders_are_retired_not_deleted(engine, scheme_i_records):
    _load_scheme_i(engine, scheme_i_records)
    with engine.begin() as conn:
        conn.execute(
            schema.regulatory_order.insert().values(
                order_key="https://example.invalid/old.pdf", title="Old URL-keyed row", url="https://example.invalid/old.pdf",
                order_kind="qco", source_id="bis_scheme_i_page", source_locator="test", retrieved_at="2026-09-12T00:00:00+00:00", is_current=True,
            )
        )
        assert retire_unlinked_orders(conn) == 1
        row = conn.execute(sa.select(schema.regulatory_order).where(schema.regulatory_order.c.title == "Old URL-keyed row")).mappings().one()
        linked_current = conn.execute(
            sa.select(sa.func.count()).select_from(schema.regulatory_order).where(schema.regulatory_order.c.is_current.is_(False))
        ).scalar()
    assert row["is_current"] is False and linked_current == 1


def test_illustrative_items_point_to_their_parent_listing(engine, scheme_i_records):
    _load_scheme_i(engine, scheme_i_records)
    with engine.connect() as conn:
        spin = _coverage(conn, product_name="Spin Extractors")[0]
        parent = conn.execute(
            sa.select(schema.scheme_coverage).where(schema.scheme_coverage.c.coverage_id == spin["parent_coverage_id"])
        ).mappings().one()
    assert parent["product_name"].startswith("All Electrical Appliances")
    assert spin["listing_status"] == parent["listing_status"]


def test_denotified_status_and_basis_are_stored(engine, scheme_i_records):
    _load_scheme_i(engine, scheme_i_records)
    with engine.connect() as conn:
        water = _coverage(conn, standard_ref_raw="IS 14543")[0]
    assert water["listing_status"] == "DENOTIFIED"
    assert "De-notified" in water["status_basis"]


def test_product_terms_are_indexed_for_search(engine, scheme_i_records):
    _load_scheme_i(engine, scheme_i_records)
    with engine.connect() as conn:
        terms = {
            (row.term_norm, row.origin)
            for row in conn.execute(sa.select(schema.product_term.c.term_norm, schema.product_term.c.origin))
        }
    assert ("stainless steel cookware", "coverage_product") in terms
    assert ("spin extractors", "illustrative_item") in terms


def test_reloading_the_same_page_changes_nothing(engine, scheme_i_records):
    _load_scheme_i(engine, scheme_i_records)
    second_run, _ = _load_scheme_i(engine, scheme_i_records)
    assert second_run.stats["inserted"] == 0
    assert second_run.stats["updated"] == 0
    assert second_run.stats["retired"] == 0


def test_upcoming_rows_resolve_prefixless_references(engine):
    records = parse_upcoming_qcos((FIXTURES / "upcoming_qcos.html").read_bytes(), UPCOMING_URL)
    with RunRecorder(engine, "bis_upcoming_qco_page") as run:
        load_scheme_records(run, records, scheme_id=None, page_url=UPCOMING_URL)
    with engine.connect() as conn:
        wrench = _coverage(conn, product_name="Pipe Wrenches-General Purpose")[0]
        links = _standard_links(conn, wrench["coverage_id"])
        benzene = _coverage(conn, product_name="Linear Alkyl Benzene")[0]
    assert wrench["scheme_id"] is None
    assert wrench["enforcement_date"] == date(2026, 10, 1)
    assert links[0]["resolution"] == "exact_version"
    assert benzene["listing_status"] == "UPCOMING"
