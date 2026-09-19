"""Automated weekly refresh of BIS published-standards metadata (overall list + per-ministry classification).

* ``portal``     — the only module that knows how the BIS Standards portal serves its Excel exports
* ``validation`` — checks a downloaded export before it can reach the database
* ``smoke``      — the assistant must answer the same way on the staged dataset as on the active one
* ``pipeline``   — download → validate → stage → index → check → activate (or keep the active dataset)
* ``log``        — refresh log and active-dataset pointer
* ``scheduler``  — Saturday schedule inside the server process

See docs/DATA_REFRESH.md.
"""
