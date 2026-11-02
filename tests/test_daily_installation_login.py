import json
import subprocess
import sys
import tempfile
import unittest
from datetime import date
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from tools import daily_installation as task


class LoginTests(unittest.TestCase):
    def exercise(self, fail=False, eoms_fail=False, export_fail=False, missing_history=False):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            commands = []
            def execute(command, **kwargs):
                commands.append(command)
                self.assertTrue(kwargs['check'])
                if fail or (eoms_fail and command[1].endswith('eoms/refresh_login.py')):
                    raise subprocess.CalledProcessError(1, command)
                if '--output' in command:
                    Path(command[command.index('--output') + 1]).write_text(
                        json.dumps({'metric_run_id': str(len(commands)), 'metric_code': Path(command[1]).stem, 'period_start': command[command.index('--start-date')+1], 'period_end': command[command.index('--end-date')+1], 'results': [{'numerator': 0, 'city': '杭州'}]}, ensure_ascii=False), encoding='utf-8')
            with patch.object(task, 'OUTPUT_DIR', root / 'outputs/daily_installation'), patch.object(task, 'ROOT', root), patch.object(task.subprocess, 'run', side_effect=execute), \
                 patch.object(task, 'validate_excel'), patch.object(task, 'cleanup_current_runs') as cleanup, \
                 patch('tools.installation_excel.export_excel', return_value='test.xlsx', side_effect=RuntimeError('export failed') if export_fail else None), \
                 patch('storage.database.has_collection_coverage', side_effect=lambda db, code, start, end: not missing_history or start == end), \
                 patch('storage.database.has_successful_coverage', return_value=True):
                if export_fail or missing_history:
                    with self.assertRaises(RuntimeError):
                        task.run(date(2026, 10, 30), node='/test/node')
                    cleanup.assert_not_called()
                elif fail or eoms_fail:
                    with self.assertRaises(subprocess.CalledProcessError):
                        task.run(date(2026, 10, 30), node='/test/node')
                else:
                    task.run(date(2026, 10, 30), node='/test/node')
            report = json.loads((root / 'outputs/daily_installation/installation_fault_rate/2026-10-30/2026-10-30.json').read_text(encoding='utf-8'))
            self.assertEqual(commands[0][1:], [str(root / 'collector/youshu/refresh_login.py'), '--node', '/test/node'])
            return commands, report

    def test_only_yesterday_collected_with_full_calculation_windows(self):
        commands, report = self.exercise()
        collected = [c for c in commands if '/collector/' in c[1] and '--start-date' in c]
        self.assertEqual(len(collected), 4)
        for command in collected:
            self.assertEqual(command[command.index('--start-date') + 1], '2026-10-29')
            self.assertEqual(command[command.index('--end-date') + 1], '2026-10-29')
        calculated = [c for c in commands if '--output' in c]
        self.assertEqual([c[c.index('--start-date') + 1] for c in calculated],
                         ['2026-07-30'] * 3 + ['2026-08-01'] * 3)

    def test_missing_history_does_not_calculate_or_backfill(self):
        commands, report = self.exercise(missing_history=True)
        self.assertFalse(any('--output' in c for c in commands))
        self.assertEqual(report['status'], 'failed')
        self.assertIn('历史数据覆盖不完整', report['error'])

    def test_export_failure_keeps_database_results(self):
        _, report = self.exercise(export_fail=True)
        self.assertEqual(report['status'], 'failed')
        self.assertEqual(report['cleanup']['status'], 'not_started')

    def test_login_before_collection_and_metrics(self):
        commands, report = self.exercise()
        self.assertEqual(len(commands), 12)
        self.assertTrue(commands[1][1].endswith('youshu/fetch_install.py'))
        self.assertEqual(report['status'], 'success')
        self.assertEqual(report['youshu_login'], 'success')
        self.assertEqual(report['eoms_login'], 'success')
        self.assertTrue(commands[4][1].endswith('eoms/refresh_login.py'))
        self.assertTrue(commands[5][1].endswith('eoms/fetch_complaints.py'))

    def test_eoms_login_failure_stops_task(self):
        commands, report = self.exercise(eoms_fail=True)
        self.assertEqual(len(commands), 5)
        self.assertEqual(report['status'], 'failed')
        self.assertEqual(report['eoms_login'], 'failed')
        self.assertEqual(report['youshu_login'], 'success')
        self.assertFalse(report['collection_complete'])
        self.assertEqual(report['windows'], {})

    def test_login_failure_stops_task(self):
        commands, report = self.exercise(fail=True)
        self.assertEqual(len(commands), 1)
        self.assertEqual(report['status'], 'failed')
        self.assertEqual(report['youshu_login'], 'failed')
        self.assertFalse(report['collection_complete'])
        self.assertEqual(report['windows'], {})


if __name__ == '__main__':
    unittest.main()
