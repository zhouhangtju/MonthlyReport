"""库存利旧中间表：精确匹配两份对照表，生成六个工作表并按批次入库。"""
import argparse
import calendar
from collections import defaultdict
from datetime import datetime
from decimal import Decimal, InvalidOperation
import hashlib
from io import BytesIO
import json
from pathlib import Path
import sys
import uuid

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
from openpyxl import Workbook, load_workbook
from openpyxl.cell import WriteOnlyCell
from openpyxl.styles import Font, PatternFill
from storage.database import connect

NAMES = ['物料仓库库存统计','物料名称表','可利旧与不可利旧设备型号对照表','不可利旧设备清单','sheet1','sheet2']

def dump(value):
    return json.dumps(value, ensure_ascii=False, default=str)

def read_table(content):
    wb = load_workbook(BytesIO(content), read_only=True, data_only=True)
    try:
        rows = list(wb.active.values)
        headers = list(rows[0])
        if len(set(headers)) != len(headers): raise ValueError('重复表头')
        return headers, [list(r) for r in rows[1:] if any(v is not None for v in r)]
    finally: wb.close()

def number(value):
    if value is None or value == '': return Decimal(0)
    if isinstance(value, bool): raise ValueError('数量不能为布尔值')
    try: result = Decimal(str(value))
    except InvalidOperation: raise ValueError(f'非法数量：{value!r}')
    if not result.is_finite() or result < 0: raise ValueError(f'非法数量：{value!r}')
    return result

def calculate(inventory, materials, models):
    headers, rows = inventory
    required = ['物料名称','型号','地市','返修物资-正常SN','回收物资-正常SN']
    if not set(required).issubset(headers): raise ValueError('库存表缺列：'+str(set(required)-set(headers)))
    if set(['物料分类','不可利旧设备型号','可利旧数量']) & set(headers): raise ValueError('请提供未加工的库存表')
    mh, mr = materials; nh, nr = models
    mapping = {}
    for row in mr:
        key, value = row[mh.index('物料名称')], row[mh.index('划分类型')]
        if key is None or key == '': continue
        if key in mapping and mapping[key] != value: raise ValueError(f'物料名称存在冲突分类：{key}')
        mapping[key] = value
    blocked = {r[nh.index('不可利旧设备型号')] for r in nr if r[nh.index('不可利旧设备型号')] not in (None,'')}
    details, excluded = [], []
    groups = [defaultdict(Decimal), defaultdict(Decimal)]
    unmatched = 0
    for row in rows:
        r = dict(zip(headers,row)); category = mapping.get(r['物料名称'])
        model = r['型号'] if r['型号'] in blocked else None
        quantity = number(r['返修物资-正常SN']) + number(r['回收物资-正常SN'])
        item = row+[category,model,quantity]; details.append(item)
        key = (category,r['地市']); groups[0][key] += quantity
        if r['物料名称'] not in mapping: unmatched += 1
        if model is not None: excluded.append(item); groups[1][key] += quantity
    new_headers = headers+['物料分类','不可利旧设备型号','可利旧数量']
    summaries = []
    for g in groups:
        summaries.append((['物料分类','地市','可利旧数量'], [[a,b,v] for (a,b),v in sorted(g.items(), key=lambda x:(str(x[0][0] or ''),str(x[0][1] or '')))]))
    assert sum(r[-1] for r in details)==sum(r[-1] for r in summaries[0][1])
    assert sum(r[-1] for r in excluded)==sum(r[-1] for r in summaries[1][1])
    sheets = [(new_headers,details),materials,models,(new_headers,excluded),*summaries]
    audit = dict(rows=len(rows),unmatched_material_rows=unmatched,blocked_rows=len(excluded),total=sum(r[-1] for r in details),blocked_total=sum(r[-1] for r in excluded))
    return sheets,audit

def export(path,sheets):
    wb=Workbook(write_only=True)
    for name,(headers,rows) in zip(NAMES,sheets):
        ws=wb.create_sheet(name);ws.freeze_panes='A2'
        from openpyxl.utils import get_column_letter
        for i in range(len(headers)): ws.column_dimensions[get_column_letter(i+1)].width=22
        cells=[]
        for h in headers:
            c=WriteOnlyCell(ws,value=h);c.font=Font(bold=True,color='FFFFFF');c.fill=PatternFill('solid',fgColor='176B87');cells.append(c)
        ws.append(cells)
        for row in rows:
            cells=[]
            for v in row:
                c=WriteOnlyCell(ws,value=float(v) if isinstance(v,Decimal) else v)
                if isinstance(v,str): c.data_type='s'
                cells.append(c)
            ws.append(cells)
        ws.auto_filter.ref=f'A1:{get_column_letter(len(headers))}{len(rows)+1}'
    path.parent.mkdir(parents=True,exist_ok=True);wb.save(path);wb.close()

def save(month,sheets,audit,sources):
    run='inventory_reuse_'+uuid.uuid4().hex
    now=datetime.now().isoformat();year,mo=map(int,month.split('-'))
    with connect() as c:
        c.execute('''CREATE TABLE IF NOT EXISTS intermediate_terminal_inventory_reuse (
            metric_run_id VARCHAR(80) NOT NULL,sheet_name VARCHAR(100) NOT NULL,source_row_number INT NOT NULL,
            material_category VARCHAR(255),city VARCHAR(255),blocked_model TEXT,reusable_quantity DECIMAL(24,6),
            row_data LONGTEXT NOT NULL,PRIMARY KEY(metric_run_id,sheet_name,source_row_number)
        ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4''')
        c.execute('''CREATE TABLE IF NOT EXISTS terminal_inventory_reuse_audit (
            metric_run_id VARCHAR(80) PRIMARY KEY,report_month VARCHAR(7) NOT NULL,
            sources LONGTEXT NOT NULL,audit LONGTEXT NOT NULL,sheet_headers LONGTEXT NOT NULL
        ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4''')
    with connect() as c:
        c.execute('''INSERT INTO metric_run(metric_run_id,metric_code,metric_version,period_start,period_end,started_at,finished_at,status,source_runs)
            VALUES (?,?,?,?,?,?,?,?,?)''',(run,'terminal_inventory_reuse','1.0',month+'-01',f'{month}-{calendar.monthrange(year,mo)[1]:02d}',now,now,'success',dump(sources)))
        c.execute('INSERT INTO terminal_inventory_reuse_audit VALUES (?,?,?,?,?)',(run,month,dump(sources),dump(audit),dump({n:h for n,(h,_) in zip(NAMES,sheets)})))
        for name,(headers,rows) in zip(NAMES,sheets):
            batch=[]
            for i,row in enumerate(rows,2):
                r=dict(zip(headers,row))
                batch.append((run,name,i,r.get('物料分类'),r.get('地市'),r.get('不可利旧设备型号'),r.get('可利旧数量'),dump(row)))
                if len(batch)==500:
                    c.executemany('INSERT INTO intermediate_terminal_inventory_reuse VALUES (?,?,?,?,?,?,?,?)',batch);batch=[]
            if batch:c.executemany('INSERT INTO intermediate_terminal_inventory_reuse VALUES (?,?,?,?,?,?,?,?)',batch)
    return run

def run(args):
    datetime.strptime(args.month,'%Y-%m')
    sources=[]
    if args.input:
        content=args.input.read_bytes();sources.append({'path':str(args.input),'sha256':hashlib.sha256(content).hexdigest()})
    else:
        year,mo=map(int,args.month.split('-'))
        with connect() as c:
            source=c.execute('''SELECT snapshot_id,etl_run_id,workbook,sha256 FROM tr_source_snapshot
                WHERE dataset_code='integration_terminal_inventory_export' AND period_start=? AND period_end=?
                ORDER BY created_at DESC,snapshot_id DESC LIMIT 1''',(args.month+'-01',f'{args.month}-{calendar.monthrange(year,mo)[1]:02d}')).fetchone()
        if not source: raise ValueError('该月缺少库存平台导出快照，请先采集或用--input指定原始表')
        content=source.pop('workbook');sources.append(source)
    tables=[read_table(content)]
    for p in [args.material_names,args.model_map]:
        b=p.read_bytes();sources.append({'path':str(p),'sha256':hashlib.sha256(b).hexdigest()});tables.append(read_table(b))
    sheets,audit=calculate(*tables)
    result={'month':args.month,'audit':audit,'sources':sources}
    if args.mode!='database':
        path=args.output_dir/f'终端库存利旧中间结果_{args.month}.xlsx';export(path,sheets);result['file']=str(path)
        wb=load_workbook(path,read_only=True,data_only=True)
        try:
            assert wb.sheetnames==NAMES
            for name,(_,rows) in zip(NAMES,sheets):assert sum(1 for _ in wb[name].values)==len(rows)+1
        finally:wb.close()
    if args.mode!='file':result['metric_run_id']=save(args.month,sheets,audit,sources)
    if args.mode!='database':(args.output_dir/f'终端库存利旧审计_{args.month}.json').write_text(dump(result),encoding='utf-8')
    return result

def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--month',required=True)
    p.add_argument('--input',type=Path,help='可选：原始库存Excel；默认读取该月数据库平台导出快照')
    p.add_argument('--material-names',type=Path,required=True)
    p.add_argument('--model-map',type=Path,required=True)
    p.add_argument('--mode',choices=['file','database','both'],default='both')
    p.add_argument('--output-dir',type=Path,default=ROOT/'outputs/terminal_inventory_reuse')
    print(dump(run(p.parse_args())))
if __name__=='__main__':main()
