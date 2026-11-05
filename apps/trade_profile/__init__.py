"""trade_profile — the risk / P&L surface of the book.

Answers "what is my risk, and what has reached its 50% target": combined delta/
vega/theta, the snapshot-vs-live comparison, profit targets, margin, and the
overnight-move view. See bootstrap.py and the layer-split plan.

This file was missing while `audit`, `data_ops`, `plan`, `screener` and
`trade_log` all had one. Imports still worked (PEP 420 namespace packages nest
inside a regular package), but anything that enumerates packages by the presence
of __init__.py -- setuptools, several linters -- would silently drop the whole
layer.
"""
