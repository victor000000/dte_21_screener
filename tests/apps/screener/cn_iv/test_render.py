"""test_render.py — the board's report text, and the staleness note it must not invent."""
import datetime as dt
import pathlib
import sys
import unittest

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[4]))

from apps.screener.cn_iv import board as B  # noqa: E402
from apps.screener.cn_iv import render as R  # noqa: E402

DAY = dt.date(2026, 9, 30)
UNIVERSE = [("SR", "CZCE", "白糖期权"), ("SI", "GFEX", "工业硅")]


def series(n, end=DAY, start_iv=0.10):
    return [(end - dt.timedelta(days=n - 1 - i), start_iv + i * 0.001) for i in range(n)]


def board(rows):
    return B.build_board(UNIVERSE, {"SR": {"s": rows}}, {})


class TestHorizonColumns(unittest.TestCase):
    def test_a_covered_window_prints_a_rank_and_a_long_one_prints_full(self):
        # 800 daily points: 1Y and 2Y are covered, 5Y and 10Y are longer than the history.
        text = R.render(board(series(800)), DAY, 35.0)
        self.assertIn("| 100 | 100 | full | full |", text)

    def test_full_is_not_a_number_and_the_history_column_carries_the_span(self):
        text = R.render(board(series(120)), DAY, 35.0)
        self.assertIn("| full | full | full | full |", text)
        self.assertIn("120 from", text)

    def test_the_horizon_legend_is_stated_once(self):
        text = R.render(board(series(120)), DAY, 35.0)
        self.assertIn("SHORTER than the window", text)


class TestTableShape(unittest.TestCase):
    def test_every_row_has_the_same_cell_count_as_the_header(self):
        # A row one cell wide of the header still renders, still contains every substring the
        # other tests assert, and is silently misaligned in the one place a reader trusts most.
        # Mixes a rankable product with an unrankable one, since they are built separately.
        text = R.render(board(series(800)), DAY, 35.0)
        rows = [ln for ln in text.splitlines() if ln.startswith("|")]
        widths = {ln.count("|") for ln in rows}
        self.assertEqual(len(widths), 1, f"ragged table: pipe counts {widths}")


class TestStalenessNote(unittest.TestCase):
    def test_no_hardcoded_holiday_survives(self):
        # The removed version said "Golden Week (Oct 1-8, 2026)" on ANY gap >= 2 days, so a
        # downloader that died silently read as a closed exchange.
        for ctx in (None, "No CN session is missing."):
            self.assertNotIn("Golden Week", R.render(board(series(120)), DAY, 35.0, context=ctx))

    def test_the_caller_supplies_the_cause(self):
        text = R.render(board(series(120)), DAY, 35.0,
                        context="3 CN session(s) since are NOT stored -- a download gap.")
        self.assertIn("**Data through 2026-09-30**", text)
        self.assertIn("a download gap", text)

    def test_without_a_cause_the_note_claims_nothing(self):
        # The count itself is deliberately not pinned: it moves with the clock, and a test that
        # asserted "8 day(s)" would fail tomorrow for a reason that has nothing to do with this.
        text = R.render(board(series(120)), DAY, 35.0)
        self.assertIn("**Data through 2026-09-30** —", text)
        self.assertIn("day(s) behind today's clock.", text)


if __name__ == "__main__":
    unittest.main()
