import sys
import unittest
from datetime import datetime, timezone
from pathlib import Path
from zoneinfo import ZoneInfo
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from tools.daily_installation import next_schedule


class ScheduleTests(unittest.TestCase):
    def test_before_at_and_after_five(self):
        tz = ZoneInfo('Asia/Shanghai')
        for hour, minute, expected_day in [(4, 59, 30), (5, 0, 30), (5, 1, 31)]:
            result = next_schedule(datetime(2026, 10, 30, hour, minute, tzinfo=tz))
            self.assertEqual((result.day, result.hour, result.minute), (expected_day, 5, 0))

    def test_utc_converted_to_beijing(self):
        result = next_schedule(datetime(2026, 12, 31, 22, tzinfo=timezone.utc))
        self.assertEqual(result.isoformat(), '2027-01-02T05:00:00+08:00')
