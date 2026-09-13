"""Product families used for the end-to-end demonstration.

For these families the pipeline goes deeper than listings and metadata: it fetches the QCO documents
linked from the scheme pages, the Product Manual PDF (where BIS allows access) and the LIMS Indian
Standard-wise test facilities. Every other product is still covered by the listings and metadata.

This list only chooses what to fetch. It adds no facts: statuses, standards and labs always come from
the fetched official records.
"""

from dataclasses import dataclass


@dataclass(frozen=True)
class LimsQuery:
    doc_no: str
    part: str | None = None

    @property
    def family_key(self) -> str:
        return f"IS {self.doc_no}" + (f" (Part {self.part})" if self.part else "")


@dataclass(frozen=True)
class DemoFamily:
    key: str
    label: str
    lims_queries: tuple[LimsQuery, ...]
    why_selected: str


DEMO_FAMILIES: tuple[DemoFamily, ...] = (
    DemoFamily(
        "stainless_steel_utensils",
        "Stainless steel utensils and cookware",
        (LimsQuery("14756"),),
        "Scheme I listing with a QCO history and a text-extractable Product Manual.",
    ),
    DemoFamily(
        "cement",
        "Ordinary Portland cement",
        (LimsQuery("269"),),
        "Long-standing cement QCO and many recognised laboratories.",
    ),
    DemoFamily(
        "structural_steel",
        "Hot rolled structural steel",
        (LimsQuery("2062"),),
        "Steel listing whose Product Manual PDF is access-restricted, exercising access-denied handling.",
    ),
    DemoFamily(
        "two_wheeler_helmets",
        "Helmets for riders of two-wheeler motor vehicles",
        (LimsQuery("4151"),),
        "Consumer safety product listed under Scheme I.",
    ),
    DemoFamily(
        "toys",
        "Toys (non-electric and electric)",
        (LimsQuery("9873", "1"), LimsQuery("15644")),
        "Consumer products listed under Scheme I.",
    ),
    DemoFamily(
        "ceiling_fans",
        "Electric ceiling type fans",
        (LimsQuery("374"),),
        "Household electrical product listed under Scheme I.",
    ),
    DemoFamily(
        "pressure_cookers",
        "Domestic pressure cookers",
        (LimsQuery("2347"),),
        "Household product listed under Scheme I.",
    ),
    DemoFamily(
        "packaged_drinking_water",
        "Packaged drinking water",
        (LimsQuery("14543"),),
        "Listed as de-notified from compulsory BIS certification, exercising status handling.",
    ),
    DemoFamily(
        "household_appliances",
        "Household and similar electrical appliances",
        (LimsQuery("302", "1"),),
        "Scheme I listing that also appears on the upcoming-QCO page.",
    ),
    DemoFamily(
        "circuit_breakers",
        "Low-voltage circuit breakers",
        (LimsQuery("60947", "2"),),
        "Scheme X listing with specific requirements.",
    ),
    DemoFamily(
        "laptops",
        "Laptops, notebooks and tablets",
        (LimsQuery("62368", "1"),),
        "Scheme II compulsory registration listing.",
    ),
    DemoFamily(
        "bicycle_reflectors",
        "Retro-reflective devices for bicycles",
        (LimsQuery("10613"),),
        "Scheme IV listing with an essential requirement quoting an IS clause.",
    ),
)
