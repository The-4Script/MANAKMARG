"""Deterministic resolution of standard references to published standards (spec §6.1, step 9).

Every reference gets an explicit resolution kind so that nothing downstream mistakes a family match or a
prefix-mismatch candidate for an exact version:

``exact_version``            the referenced version is in the published list
``match_key_version``        same version written in another notation (hyphen vs ``(Part n)``, suffix)
``family_latest``            no year given — all versions, latest first
``family_ambiguous``         no part given but the standard is published in parts
``version_not_in_master``    the family exists but not the referenced year
``international_reference``  an ISO/IEC reference that is not an Indian Standard in the list
``prefix_mismatch_candidate`` same number under a different prefix — a candidate only, never a match
``unresolved``               nothing matches
"""

from collections import defaultdict
from dataclasses import dataclass

import sqlalchemy as sa
from sqlalchemy.engine import Connection

from manakmarg.db import schema
from manakmarg.normalize.is_number import Designation, extract_designations

EXACT_VERSION = "exact_version"
MATCH_KEY_VERSION = "match_key_version"
FAMILY_LATEST = "family_latest"
FAMILY_AMBIGUOUS = "family_ambiguous"
VERSION_NOT_IN_MASTER = "version_not_in_master"
INTERNATIONAL_REFERENCE = "international_reference"
PREFIX_MISMATCH_CANDIDATE = "prefix_mismatch_candidate"
UNRESOLVED = "unresolved"

CONFIDENT_KINDS = frozenset({EXACT_VERSION, MATCH_KEY_VERSION, FAMILY_LATEST})


@dataclass(frozen=True)
class Resolution:
    ref_raw: str
    kind: str
    designation: Designation | None
    family_key: str | None
    standard_ids: tuple[int, ...]
    note: str = ""

    @property
    def best_standard_id(self) -> int | None:
        return self.standard_ids[0] if self.standard_ids else None


@dataclass(frozen=True)
class _Version:
    standard_id: int
    std_key: str
    family_key: str
    match_key: str
    number_key: str
    prefix: str | None
    part: str | None
    year: int | None


def _latest_first(versions: list[_Version]) -> list[_Version]:
    return sorted(versions, key=lambda version: (version.year is None, -(version.year or 0), version.std_key))


def _ids(versions: list[_Version]) -> tuple[int, ...]:
    return tuple(version.standard_id for version in versions)


def _keys(versions: list[_Version]) -> str:
    return ", ".join(version.std_key for version in versions)


class StandardResolver:
    """In-memory index of current standards; build once per ingestion run or request batch."""

    def __init__(self, conn: Connection):
        table = schema.standard
        rows = conn.execute(
            sa.select(
                table.c.standard_id,
                table.c.std_key,
                table.c.family_key,
                table.c.match_key,
                table.c.number_key,
                table.c.prefix,
                table.c.part,
                table.c.year,
            ).where(table.c.is_current.is_(True))
        ).all()
        self._by_std_key: dict[str, _Version] = {}
        self._by_match_year: dict[tuple[str, int | None], list[_Version]] = defaultdict(list)
        self._by_family: dict[str, list[_Version]] = defaultdict(list)
        self._by_match: dict[str, list[_Version]] = defaultdict(list)
        self._by_prefix_number: dict[tuple[str | None, str], list[_Version]] = defaultdict(list)
        self._by_number: dict[str, list[_Version]] = defaultdict(list)
        for row in rows:
            version = _Version(*row)
            self._by_std_key[version.std_key] = version
            self._by_match_year[(version.match_key, version.year)].append(version)
            self._by_family[version.family_key].append(version)
            self._by_match[version.match_key].append(version)
            self._by_prefix_number[(version.prefix, version.number_key)].append(version)
            self._by_number[version.number_key].append(version)

    def resolve_text(self, text: str | None, *, assume_is_prefix: bool = False) -> list[Resolution]:
        """Resolve every designation mentioned in ``text``."""
        return [self.resolve(designation) for designation in extract_designations(text or "", assume_is_prefix=assume_is_prefix)]

    def resolve(self, designation: Designation) -> Resolution:
        exact = self._by_std_key.get(designation.std_key)
        if exact is not None:
            return Resolution(designation.raw, EXACT_VERSION, designation, exact.family_key, (exact.standard_id,))

        if designation.year is not None:
            same_version = self._by_match_year.get((designation.match_key, designation.year))
            if same_version:
                ordered = _latest_first(same_version)
                return Resolution(
                    designation.raw,
                    MATCH_KEY_VERSION,
                    designation,
                    ordered[0].family_key,
                    _ids(ordered),
                    note=f"Written as {designation.std_key}; published as {_keys(ordered)}.",
                )

        family = self._by_family.get(designation.family_key) or self._by_match.get(designation.match_key)
        if family:
            ordered = _latest_first(family)
            if designation.year is None:
                return Resolution(
                    designation.raw,
                    FAMILY_LATEST,
                    designation,
                    ordered[0].family_key,
                    _ids(ordered),
                    note=f"No year in the reference; published version(s): {_keys(ordered)}.",
                )
            return Resolution(
                designation.raw,
                VERSION_NOT_IN_MASTER,
                designation,
                ordered[0].family_key,
                _ids(ordered),
                note=f"{designation.std_key} is not in the published list; listed version(s): {_keys(ordered)}.",
            )

        if designation.part is None:
            parts = [
                version
                for version in self._by_prefix_number.get((designation.prefix, designation.number_key), [])
                if version.part is not None
            ]
            if parts:
                ordered = sorted(parts, key=lambda version: (version.part or "", -(version.year or 0)))
                return Resolution(
                    designation.raw,
                    FAMILY_AMBIGUOUS,
                    designation,
                    designation.family_key,
                    _ids(ordered),
                    note=f"The reference names no part; published parts: {_keys(ordered)}.",
                )

        if (designation.prefix or "").split("/")[0] not in {"IS", "SP"}:
            return Resolution(
                designation.raw,
                INTERNATIONAL_REFERENCE,
                designation,
                None,
                (),
                note="International standard reference; not an Indian Standard in the published list.",
            )

        other_prefix = [
            version
            for version in self._by_number.get(designation.number_key, [])
            if version.prefix != designation.prefix
            and version.part == designation.part
            and (designation.year is None or version.year == designation.year)
        ]
        if other_prefix:
            ordered = _latest_first(other_prefix)
            return Resolution(
                designation.raw,
                PREFIX_MISMATCH_CANDIDATE,
                designation,
                None,
                _ids(ordered),
                note=f"Same number under a different prefix: {_keys(ordered)}. Verify before relying on it.",
            )

        return Resolution(
            designation.raw,
            UNRESOLVED,
            designation,
            designation.family_key,
            (),
            note="No published standard in the indexed list matches this reference.",
        )
