"""Retention is exercised against the current fixed-column MySQL schema."""
import unittest
import test_split_raw_tables_integration as fixed_tests

class OrchestrationRetentionTest(unittest.TestCase):
    setUp = fixed_tests.FixedRawTablesTest.setUp
    drop_database = fixed_tests.FixedRawTablesTest.drop_database
    write = fixed_tests.FixedRawTablesTest.write
    put = fixed_tests.FixedRawTablesTest.put
    test_prune_requires_summary_then_archives = fixed_tests.FixedRawTablesTest.test_raw_calculation_and_retention_use_business_key

if __name__ == "__main__": unittest.main()
