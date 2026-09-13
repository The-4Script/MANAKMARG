from bs4 import BeautifulSoup

from manakmarg.ingest.html_grid import Link, distinct_cells, origin_cells, table_to_grid


def _grid(html):
    return table_to_grid(BeautifulSoup(html, "lxml").find("table"))


def _texts(cells):
    return [cell.text for cell in cells]


ROWSPAN_TABLE = """
<table>
  <tr><th>Sr No.</th><th>IS No.</th><th>Product</th><th>Notification</th></tr>
  <tr><td colspan="4">Cement (any variety of cement manufactured or sold in India) such as</td></tr>
  <tr><td>1.</td><td>IS 12330</td><td>Sulphate Resisting Portland Cement</td>
      <td rowspan="3"><a href="/SO-No-191(E).pdf">1. Cement (Quality Control)Order, 2003</a></td></tr>
  <tr><td>2.</td><td>IS 12600</td><td>Low heat Portland Cement</td></tr>
  <tr><td>3.</td><td>IS 269</td><td>Ordinary Portland Cement</td></tr>
  <tr><td>4.</td><td>IS 455</td><td>Portland Slag Cement</td><td>Other order</td></tr>
</table>
"""


def test_rowspan_cells_are_repeated_down_the_column():
    grid = _grid(ROWSPAN_TABLE)
    assert grid[3][3].text == "1. Cement (Quality Control)Order, 2003"
    assert grid[4][3] is grid[2][3]
    assert grid[4][3].origin_row == 2
    assert grid[5][3].text == "Other order"


def test_origin_cells_exclude_inherited_cells():
    grid = _grid(ROWSPAN_TABLE)
    assert _texts(origin_cells(grid, 3)) == ["2.", "IS 12600", "Low heat Portland Cement"]
    assert _texts(origin_cells(grid, 2)) == [
        "1.",
        "IS 12330",
        "Sulphate Resisting Portland Cement",
        "1. Cement (Quality Control)Order, 2003",
    ]


def test_colspan_category_row_fills_every_column():
    grid = _grid(ROWSPAN_TABLE)
    category = grid[1]
    assert len(category) == 4
    assert all(cell is category[0] for cell in category)
    assert category[0].colspan == 4
    assert _texts(origin_cells(grid, 1)) == ["Cement (any variety of cement manufactured or sold in India) such as"]


def test_header_cells_are_marked():
    grid = _grid(ROWSPAN_TABLE)
    assert grid[0][0].is_header is True
    assert grid[2][0].is_header is False


UPCOMING_TABLE = """
<table id="myTable">
  <tr><th>Sr. No.</th><th>Ministry/ Department</th><th>Product</th><th>Indian Standard</th><th>Enforcement date</th></tr>
  <tr><th rowspan="3">13</th><td rowspan="3"><span>DPIIT</span></td>
      <td><span>All electrical appliances. Illustrative list of electrical appliances is given below:</span></td>
      <td rowspan="3"><span>IS 302 (Part 1) : 2024 IEC 60335-1:2020</span></td>
      <td colspan="2" rowspan="3"><span>01 October, 2026</span></td></tr>
  <tr><td><span>Vacuum Cleaners and Water Suction Cleaning Appliances</span></td></tr>
  <tr><td><span>Spin Extractors</span></td></tr>
  <tr><th>14</th><td>Department of Chemicals and Petrochemicals</td>
      <td colspan="2">Woven Sacks for Packaging of 50 kg Cement</td><td>IS 11652 : 2017</td><td> 06 October 2026</td></tr>
</table>
"""


def test_combined_rowspan_and_colspan_keep_logical_fields_in_order():
    grid = _grid(UPCOMING_TABLE)
    assert _texts(distinct_cells(grid[2])) == [
        "13",
        "DPIIT",
        "Vacuum Cleaners and Water Suction Cleaning Appliances",
        "IS 302 (Part 1) : 2024 IEC 60335-1:2020",
        "01 October, 2026",
    ]
    assert _texts(origin_cells(grid, 2)) == ["Vacuum Cleaners and Water Suction Cleaning Appliances"]
    assert _texts(distinct_cells(grid[4])) == [
        "14",
        "Department of Chemicals and Petrochemicals",
        "Woven Sacks for Packaging of 50 kg Cement",
        "IS 11652 : 2017",
        "06 October 2026",
    ]


def test_links_and_block_lines_are_preserved():
    html = """
    <table><tr><td rowspan="2">
      <p><a href="http://crsbis.in/doc.pdf">Electronics Order, 2012 Dated 03<sup>rd</sup> October 2012</a></p>
      <p> </p><p>Subsequent</p><p>Amendments</p>
      <p><u><a href="/SO 822 (E).pdf">Notification No. S.O. 822(E) dated 20 March 2013</a></u></p>
    </td></tr><tr></tr></table>
    """
    cell = _grid(html)[0][0]
    assert cell.links == (
        Link("Electronics Order, 2012 Dated 03rd October 2012", "http://crsbis.in/doc.pdf"),
        Link("Notification No. S.O. 822(E) dated 20 March 2013", "/SO 822 (E).pdf"),
    )
    assert cell.lines == (
        "Electronics Order, 2012 Dated 03rd October 2012",
        "Subsequent",
        "Amendments",
        "Notification No. S.O. 822(E) dated 20 March 2013",
    )
    assert cell.text == (
        "Electronics Order, 2012 Dated 03rd October 2012 Subsequent Amendments "
        "Notification No. S.O. 822(E) dated 20 March 2013"
    )


def test_br_separated_labels_become_lines():
    html = """<table><tr><td><label>Recognition No.: CRO/RAHC/R-110002</label><br/>
              <label><b>Validity:31/07/2028</b></label><br/><label><b>M/s Jalan Hallmarking Centre</b></label></td></tr></table>"""
    cell = _grid(html)[0][0]
    assert cell.lines == ("Recognition No.: CRO/RAHC/R-110002", "Validity:31/07/2028", "M/s Jalan Hallmarking Centre")


def test_ragged_rows_do_not_fail():
    grid = _grid("<table><tr><th>A</th><th>B</th><th>C</th></tr><tr><td>only one</td></tr></table>")
    assert _texts(distinct_cells(grid[1])) == ["only one"]


def test_nested_tables_are_not_flattened_into_rows():
    grid = _grid("<table><tr><td>1</td><td>26000<table><tr><td>Clause</td></tr><tr><td>6.1</td></tr></table></td></tr></table>")
    assert len(grid) == 1
    assert len(grid[0]) == 2
    assert grid[0][1].element.find("table") is not None
