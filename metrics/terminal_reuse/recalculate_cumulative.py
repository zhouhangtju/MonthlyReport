from pathlib import Path
from collections import defaultdict
from openpyxl import load_workbook
from openpyxl.utils.datetime import from_excel
import re,json,xlrd
import sys
sys.path.insert(0,str(Path(__file__).resolve().parents[2]))
from storage.database import connect
import argparse,calendar,sys
ROOT=Path(__file__).resolve().parents[2]
sys.path.insert(0,str(ROOT))
parser=argparse.ArgumentParser(description='累计终端利旧指标：历史中间表加当月数据库结果，不读取人工核验表')
parser.add_argument('--month',required=True)
parser.add_argument('--opening-stock',type=Path,default=ROOT/'data/24年5月库存数量.xls')
parser.add_argument('--output-dir',type=Path,default=ROOT/'outputs/terminal_reuse/cumulative')
args=parser.parse_args()
month=args.month
from datetime import datetime
period=datetime.strptime(month,'%Y-%m')
end=f'{month}-{calendar.monthrange(period.year,period.month)[1]:02d}'
OUT=args.output_dir;OUT.mkdir(parents=True,exist_ok=True)
with connect() as c:
 def latest(code):
  r=c.execute("SELECT metric_run_id FROM metric_run WHERE metric_code=? AND period_end=? AND status='success' ORDER BY started_at DESC,metric_run_id DESC LIMIT 1",(code,end)).fetchone()
  if not r:raise ValueError('缺少当月成功批次：'+code)
  return r['metric_run_id']
 installation_run=latest('terminal_installation_reuse')
 recovery_run=latest('terminal_recovery')
def norm(v):
 s=str(v or '').strip().removesuffix('市');s=re.sub('(畲族自治县|自治县|县|区)$','',s)
 return {'武林':'上城','江东':'鄞州','南湖':'嘉禾','秀洲':'嘉禾','南城':'开发','开发区':'开发'}.get(s,s)
def unmatched_county(value):
 return norm(value) in {'', '未匹配', '未匹配区', '未匹配区县', '未知', '未知区', '未知区县'}

excluded_counties=[]

def read(p):
 w=load_workbook(p,read_only=True,data_only=True);r=list(w.active.values);w.close();return r
with connect() as c:
 # Use September database intermediates, replacing only the same normalized county/month in calculation below.
 a=c.execute("SELECT sheet_headers FROM terminal_installation_reuse_audit WHERE metric_run_id=?",(installation_run,)).fetchone();h=json.loads(a['sheet_headers'])['sheet5'];sept=[dict(zip(h,json.loads(x['row_data']))) for x in c.execute("SELECT row_data FROM intermediate_terminal_installation_reuse WHERE metric_run_id=? AND sheet_name='sheet5'",(installation_run,)).fetchall()]
 allrows=c.execute("SELECT * FROM intermediate_terminal_reuse_history WHERE report_month BETWEEN '2024-06' AND ?",(month,)).fetchall()
 recovery=[dict(x,dim=json.loads(x['dimension_value'])) for x in c.execute("SELECT dimension_type,dimension_value,metric_value FROM result_terminal_recovery WHERE metric_run_id=?",(recovery_run,)).fetchall()]
# Stop instead of double-counting differently spelled keys from historical imports.
seen_history = set()
for historical in allrows:
 if historical['report_month'] == month: continue
 if historical['dimension_type']=='county' and unmatched_county(historical['county']): continue
 key = (historical['sheet_name'], historical['report_month'], historical['dimension_type'], norm(historical['city'] if historical['dimension_type']=='city' else historical['county']))
 if key in seen_history: raise ValueError('历史存在重复统计键，请先核对清理：'+str(key))
 seen_history.add(key)
install={'city':defaultdict(lambda:[0.,0.]),'county':defaultdict(lambda:[0.,0.])};rec={'city':defaultdict(float),'county':defaultdict(float)}
blank=[]
for a in allrows:
 level=a['dimension_type'];key=norm(a['city'] if level=='city' else a['county'])
 if level=='county' and unmatched_county(a['county']):
  if a['report_month'] != month:
   excluded_counties.append({'source':'history','month':a['report_month'],'sheet':a['sheet_name'],'city':a['city'],'county':a['county'],'new_sn':a['new_sn'],'repair_sn':a['repair_sn'],'recovery_sn':a['recovery_sn'],'recovered_quantity':a['recovered_quantity']})
  continue
 if a['sheet_name']=='装机利旧数':
  if a['report_month']==month:continue
  v=install[level][key];v[0]+=a['repair_sn']+a['recovery_sn'];v[1]+=a['new_sn']+a['repair_sn']+a['recovery_sn']
 elif a['sheet_name']=='拆回终端数':
  if a['report_month']==month:continue
  if a['recovered_quantity'] is None:blank.append(dict(a));continue
  rec[level][key]+=a['recovered_quantity']
for a in sept:
 if a['统计层级']=='区县' and unmatched_county(a['区县']):
  excluded_counties.append({'source':'current_installation','month':month,'city':a['地市'],'county':a['区县'],'new_sn':float(a['新物资数量有SN'] or 0),'repair_sn':float(a['返修物资数量有SN'] or 0),'recovery_sn':float(a['回收物资数量有SN'] or 0)})
  continue
 level='city' if a['统计层级']=='地市' else 'county';key=norm(a['地市'] if level=='city' else a['区县']);n=float(a['返修物资数量有SN'])+float(a['回收物资数量有SN']);v=install[level][key];v[0]+=n;v[1]+=n+float(a['新物资数量有SN'])
for a in recovery:
 if a['dim'].get('column')!='已拆回设备数量':continue
 if a['dimension_type']=='city_summary':rec['city'][norm(a['dim']['label'])]+=a['metric_value']
 if a['dimension_type']=='district_summary' and unmatched_county(a['dim']['label'].split('·')[-1]):
  excluded_counties.append({'source':'current_recovery','month':month,'label':a['dim']['label'],'recovered_quantity':a['metric_value']})
  continue
 if a['dimension_type']=='district_summary':rec['county'][norm(a['dim']['label'].split('·')[-1])]+=a['metric_value']
w=xlrd.open_workbook(str(args.opening_stock));s=w.sheet_by_name('拆回终端剔除三类标签');opening={norm(s.cell_value(i,0)):s.cell_value(i,1)-s.cell_value(i,2)+s.cell_value(i,3) for i in range(38,49)}
county_sheet=w.sheet_by_name('Sheet3')
county_opening={norm(county_sheet.cell_value(i,0)):county_sheet.cell_value(i,6)-county_sheet.cell_value(i,7)+county_sheet.cell_value(i,8) for i in range(101,192) if isinstance(county_sheet.cell_value(i,6),(int,float)) and str(county_sheet.cell_value(i,0)) not in ('总计','')}
result={'period':['2024-06',month],'source_installation_run':installation_run,'source_recovery_run':recovery_run,'blank_recovery_cells':blank,'city':[],'county':[]}
result['excluded_unmatched_counties']=excluded_counties
result['county_scope_note']='区县仅含有效标准区县；未匹配分组保留历史入库，地市及全省保留其数量，区县汇总可能与地市合计不同。'
for level in ('city','county'):
 for key,(n,d) in install[level].items():
  stock=opening.get(key,0) if level=='city' else county_opening.get(key)
  if stock is None:raise ValueError('期初库存缺少区县：'+key)
  den=rec[level].get(key,0)+(stock or 0)
  result[level].append({'label':key,'reuse':n,'outbound':d,'consumption':n/d if d else None,'recovered':rec[level].get(key,0),'opening_stock':stock,'utilization_denominator':den,'utilization':n/den if den else None})
result['summary']={level:{k:sum(x[k] for x in result[level]) for k in ('reuse','outbound','recovered','utilization_denominator')} for level in ('city','county')}
(OUT/f'独立计算结果_{month}.json').write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding='utf8');print(json.dumps(result['summary'],ensure_ascii=False));print('blank cells',len(blank));
import uuid
from datetime import datetime
run='terminal_reuse_cumulative_'+uuid.uuid4().hex
result['metric_run_id']=run
for level in ('city','county'):
 t=result['summary'][level];t['consumption']=t['reuse']/t['outbound'];t['utilization']=t['reuse']/t['utilization_denominator'];t['opening_stock']=t['utilization_denominator']-t['recovered']
result['city_chart']=sorted(result['city'],key=lambda r:-r['consumption'])
result['county_consumption_bottom10']=sorted(result['county'],key=lambda r:r['consumption'])[:10]
result['county_utilization_bottom10']=sorted(result['county'],key=lambda r:r['utilization'])[:10]
with connect() as c:
 c.execute('CREATE TABLE IF NOT EXISTS terminal_reuse_cumulative_audit (metric_run_id VARCHAR(80) PRIMARY KEY,report_month CHAR(7) NOT NULL,result_json JSON NOT NULL) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4')
 # Replace older county imports with blank city before saving canonical current-month rows.
 current_counties = {norm(row['区县']) for row in sept if row['统计层级']=='区县'}
 imported = c.execute("SELECT county FROM intermediate_terminal_reuse_history WHERE sheet_name='装机利旧数' AND report_month=? AND dimension_type='county' AND city=''", (month,)).fetchall()
 for old in imported:
  if norm(old['county']) in current_counties:
   c.execute("DELETE FROM intermediate_terminal_reuse_history WHERE sheet_name='装机利旧数' AND report_month=? AND dimension_type='county' AND city='' AND county=?", (month,old['county']))
 # Idempotently append current installation totals to the shared history table.
 for row in sept:
  level='city' if row['统计层级']=='地市' else 'county'
  c.execute("INSERT INTO intermediate_terminal_reuse_history (sheet_name,report_month,dimension_type,city,county,new_sn,repair_sn,recovery_sn,source_metadata) VALUES ('装机利旧数',?,?,?,?,?,?,?,?) ON DUPLICATE KEY UPDATE new_sn=VALUES(new_sn),repair_sn=VALUES(repair_sn),recovery_sn=VALUES(recovery_sn),source_metadata=VALUES(source_metadata)",(month,level,row['地市'],row.get('区县') or '',*[float(row[k] or 0) for k in ('新物资数量有SN','返修物资数量有SN','回收物资数量有SN')],json.dumps({'installation_run':installation_run},ensure_ascii=False)))
 # Persist September recovery from the confirmed recovery batch, by city and county.
 for a in recovery:
  if a['dim'].get('column')!='已拆回设备数量' or a['dimension_type'] not in ('city_summary','district_summary'):continue
  label=a['dim']['label'];level='city' if a['dimension_type']=='city_summary' else 'county';city=label.split('·')[0];county=label.split('·')[-1] if level=='county' else ''
  c.execute("INSERT INTO intermediate_terminal_reuse_history (sheet_name,report_month,dimension_type,city,county,new_sn,repair_sn,recovery_sn,recovered_quantity,source_metadata) VALUES ('拆回终端数',?,?,?,?,0,0,0,?,?) ON DUPLICATE KEY UPDATE recovered_quantity=VALUES(recovered_quantity),source_metadata=VALUES(source_metadata)",(month,level,city,county,a['metric_value'],json.dumps({'source_recovery_run':result['source_recovery_run']},ensure_ascii=False)))
 now=datetime.now().isoformat()
 c.execute("INSERT INTO metric_run(metric_run_id,metric_code,metric_version,period_start,period_end,started_at,finished_at,status,source_runs) VALUES (?,'terminal_reuse_cumulative','1.0','2024-06-01',?, ?,?,'success',?)",(run,end,now,now,json.dumps({'installation':result['source_installation_run'],'recovery':result['source_recovery_run'],'history':'intermediate_terminal_reuse_history'},ensure_ascii=False)))
 c.execute('INSERT INTO terminal_reuse_cumulative_audit VALUES (?,?,?)',(run,month,json.dumps(result,ensure_ascii=False)))
 for level in ('city','county'):
  for row in result[level]:
   for code,den in [('cumulative_consumption',row['outbound']),('cumulative_utilization',row['utilization_denominator'])]:
    c.execute('INSERT INTO result_terminal_reuse(metric_run_id,metric_code,dimension_type,dimension_value,numerator,denominator,metric_value) VALUES (?,?,?,?,?,?,?)',(run,code,level,json.dumps({'month':month,'label':row['label']},ensure_ascii=False),row['reuse'],den,row['reuse']/den if den else None))
(OUT/f'累计页填充数据_{month}.json').write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding='utf8')
print(run)
