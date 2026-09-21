"""Run a read-only source sample through an isolated MySQL import and compare cells."""
from pathlib import Path
import sys
sys.path[:0]=[str(Path(__file__).resolve().parents[1]),str(Path(__file__).resolve().parents[1]/'tests')]
from itertools import islice
from tools.inspect_raw_layouts import PATTERNS
from test_split_raw_tables_integration import FixedRawTablesTest
from storage.importer import iter_rows, _db_value
from storage.raw_tables import read_records, source_columns
from storage.database import connect
from config.datasets import DATASETS

def main():
    root=Path(sys.argv[1])
    files=[p for p in root.rglob('*.xlsx') if not p.name.startswith(('~$','._')) and '__MACOSX' not in p.parts and '合并' not in p.name]
    case=FixedRawTablesTest('test_all_tables_keys_and_repeat_import')
    try:
        case.setUp()
        for code,prefix in PATTERNS.items():
            source=max((p for p in files if p.name.startswith(prefix)),key=lambda p:p.stat().st_size)
            iterator=iter_rows(source)
            try: rows=list(islice(iterator,20))
            finally: iterator.close()
            case.put(code,rows)
            with connect(None) as connection:
                actual=read_records(connection,code,'2026-08-01','2026-08-31')
            expected=[]
            for row in rows:
                values={c:_db_value(row.get(c)) for c in source_columns(code)}
                # CSV represents blank cells as empty strings.
                values={k:('' if v is None else v) for k,v in values.items()}
                if not DATASETS[code].auto_increment:
                    values[DATASETS[code].key_column]=values[DATASETS[code].key_column].strip()
                expected.append(values)
            if not DATASETS[code].auto_increment:
                expected=list({r[DATASETS[code].key_column]:r for r in expected}.values())
                actual.sort(key=lambda r:r[DATASETS[code].key_column])
                expected.sort(key=lambda r:r[DATASETS[code].key_column])
            assert [{c:r[c] for c in source_columns(code)} for r in actual]==expected,code
            print(f'{code}: {len(actual)} rows, {len(source_columns(code))} columns OK',flush=True)
    finally:
        case.doCleanups()

if __name__=='__main__': main()
