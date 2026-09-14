"""Fail clearly instead of recomputing from purged source history."""

from storage.database import has_successful_coverage


def require_source_history(connection, database, dataset):
    for row in connection.execute("SELECT period_start,period_end FROM data_retention_purge WHERE dataset_code=?", (dataset,)):
        if not has_successful_coverage(database, dataset, row[0], row[1]):
            raise RuntimeError(
                f"{dataset}: source history {row[0]}..{row[1]} was cleaned. "
                "Reimport required original files into an isolated calculation database before recomputing; stored metric results remain available."
            )
