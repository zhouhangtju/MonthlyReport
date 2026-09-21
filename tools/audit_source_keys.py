from pathlib import Path
import json,sys
sys.path.insert(0,str(Path.cwd()))
from tools.inspect_raw_layouts import PATTERNS
from config.datasets import DATASETS
from storage.importer import iter_rows, read_headers, _db_value
from storage.raw_tables import source_columns
files=[p for p in Path(sys.argv[1]).rglob('*.xlsx') if not p.name.startswith(('~$','._')) and '__MACOSX' not in p.parts and '合并' not in p.name]
for code,prefix in PATTERNS.items():
    choices=sorted((p for p in files if p.name.startswith(prefix)),key=lambda p:-p.stat().st_size)
    p=choices[0]; dataset=DATASETS[code]; seen={}; duplicates=conflicts=missing=count=0
    for row in iter_rows(p):
        count+=1
        if dataset.auto_increment: continue
        key=_db_value(row.get(dataset.key_column))
        if key is None or not key.strip(): missing+=1; continue
        key=key.strip(); value=tuple(_db_value(row.get(c)) for c in source_columns(code))
        if key in seen:
            duplicates+=1
            if seen[key]!=value: conflicts+=1
        else: seen[key]=value
    print(json.dumps(dict(dataset=code,rows=count,duplicates=duplicates,conflicts=conflicts,missing=missing),ensure_ascii=True),flush=True)
