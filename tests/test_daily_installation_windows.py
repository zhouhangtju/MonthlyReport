import sys
import unittest
from datetime import date
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from tools.daily_installation import windows


class WindowTests(unittest.TestCase):
    def test_confirmed_example(self):
        self.assertEqual(windows(date(2026, 10, 30)), {
            'rolling_three_months': ('2026-07-30', '2026-10-29'),
            'calendar_three_months': ('2026-08-01', '2026-10-29')})

    def test_leap_month_end(self):
        self.assertEqual(windows(date(2024, 5, 31))['rolling_three_months'],
                         ('2024-02-29', '2024-05-30'))

    def test_year_boundary(self):
        self.assertEqual(windows(date(2026, 1, 1))['calendar_three_months'],
                         ('2025-11-01', '2025-12-31'))


if __name__ == '__main__':
    unittest.main()
