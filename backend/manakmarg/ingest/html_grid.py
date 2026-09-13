"""HTML table → grid with rowspan/colspan expansion (plan Task 3.1).

BIS listing pages use ``rowspan`` for notification cells and ``colspan`` for category rows. Parsers
work on the expanded grid: every position holds the ``GridCell`` that covers it, and ``origin_row``
tells a cell that starts in the current row apart from one inherited from a row above.
"""

import copy
from dataclasses import dataclass, field

from bs4 import Tag

from manakmarg.normalize.text import clean_ws

_BLOCK_TAGS = ["p", "div", "li", "ul", "ol", "tr", "table", "h1", "h2", "h3", "h4", "h5", "h6", "section"]
_LINE_BREAK = " "


@dataclass(frozen=True)
class Link:
    text: str
    href: str


@dataclass(frozen=True, eq=False)
class GridCell:
    text: str
    lines: tuple[str, ...]
    links: tuple[Link, ...]
    origin_row: int
    origin_col: int
    rowspan: int
    colspan: int
    is_header: bool
    element: Tag = field(repr=False)


def _span(tag: Tag, attribute: str) -> int:
    try:
        return max(int(str(tag.get(attribute, "1")).strip() or "1"), 1)
    except ValueError:
        return 1


def _direct_rows(table: Tag) -> list[Tag]:
    rows: list[Tag] = []
    for child in table.children:
        if not isinstance(child, Tag):
            continue
        if child.name == "tr":
            rows.append(child)
        elif child.name in ("thead", "tbody", "tfoot"):
            rows.extend(item for item in child.children if isinstance(item, Tag) and item.name == "tr")
    return rows


def _direct_cells(row: Tag) -> list[Tag]:
    return [child for child in row.children if isinstance(child, Tag) and child.name in ("td", "th")]


def cell_lines(element: Tag) -> tuple[str, ...]:
    """Text lines of an element, split only at <br> and block-element boundaries."""
    clone = copy.copy(element)
    for line_break in clone.find_all("br"):
        line_break.replace_with(_LINE_BREAK)
    for block in clone.find_all(_BLOCK_TAGS):
        block.insert_before(_LINE_BREAK)
        block.insert_after(_LINE_BREAK)
    pieces = (clean_ws(piece) for piece in clone.get_text("").split(_LINE_BREAK))
    return tuple(piece for piece in pieces if piece)


def _links(element: Tag) -> tuple[Link, ...]:
    return tuple(
        Link(clean_ws(anchor.get_text("")), anchor["href"].strip()) for anchor in element.find_all("a", href=True)
    )


def table_to_grid(table: Tag) -> list[list[GridCell | None]]:
    grid: list[list[GridCell | None]] = []
    carried: dict[int, list] = {}
    for row_index, row in enumerate(_direct_rows(table)):
        cells = iter(_direct_cells(row))
        upcoming = next(cells, None)
        grid_row: list[GridCell | None] = []
        column = 0
        while upcoming is not None or any(carried_column >= column for carried_column in carried):
            if column in carried:
                cell, remaining = carried[column]
                grid_row.append(cell)
                if remaining <= 1:
                    del carried[column]
                else:
                    carried[column][1] = remaining - 1
                column += 1
                continue
            if upcoming is None:
                grid_row.append(None)
                column += 1
                continue
            element, upcoming = upcoming, next(cells, None)
            rowspan, colspan = _span(element, "rowspan"), _span(element, "colspan")
            lines = cell_lines(element)
            cell = GridCell(
                text=" ".join(lines),
                lines=lines,
                links=_links(element),
                origin_row=row_index,
                origin_col=column,
                rowspan=rowspan,
                colspan=colspan,
                is_header=element.name == "th",
                element=element,
            )
            for _ in range(colspan):
                grid_row.append(cell)
                if rowspan > 1:
                    carried[column] = [cell, rowspan - 1]
                column += 1
        grid.append(grid_row)
    return grid


def distinct_cells(grid_row: list[GridCell | None]) -> list[GridCell]:
    """Cells of a grid row in column order, each colspan-repeated cell listed once."""
    found: list[GridCell] = []
    seen: set[int] = set()
    for cell in grid_row:
        if cell is None or id(cell) in seen:
            continue
        seen.add(id(cell))
        found.append(cell)
    return found


def origin_cells(grid: list[list[GridCell | None]], row_index: int) -> list[GridCell]:
    """Cells that start in ``row_index`` (inherited rowspan cells excluded)."""
    return [cell for cell in distinct_cells(grid[row_index]) if cell.origin_row == row_index]
