"""SQL adapter regressions; no MySQL server required."""
import unittest
from storage.database import MySQLCursor

class DriverCursor:
    def execute(self, sql, params=None):
        self.sql = sql if params is None else sql % tuple(repr(v) for v in params)
    def executemany(self, sql, rows):
        self.sqls = [sql % tuple(repr(v) for v in row) for row in rows]

class PlaceholderTest(unittest.TestCase):
    def test_percent_in_report_column(self):
        driver=DriverCursor()
        MySQLCursor(driver).execute('INSERT INTO report (`一次上门率(%)`) VALUES (?)',('99.8',))
        self.assertEqual(driver.sql,"INSERT INTO report (`一次上门率(%)`) VALUES ('99.8')")
    def test_batch_percent_column(self):
        driver=DriverCursor()
        MySQLCursor(driver).executemany('INSERT INTO report (`成功率(%)`) VALUES (?)',[(1,),(2,)])
        self.assertEqual(driver.sqls,['INSERT INTO report (`成功率(%)`) VALUES (1)','INSERT INTO report (`成功率(%)`) VALUES (2)'])
    def test_no_parameters_preserves_percent(self):
        driver=DriverCursor()
        MySQLCursor(driver).execute('CREATE TABLE report (`成功率(%)` TEXT)')
        self.assertEqual(driver.sql,'CREATE TABLE report (`成功率(%)` TEXT)')
