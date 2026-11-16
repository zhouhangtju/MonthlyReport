"""从数据库中间结果计算终端利旧页数据，不读取人工核验表。"""
import argparse
import calendar
from collections import defaultdict
from datetime import datetime
import json
from pathlib import Path
import sys
import uuid

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
from storage.database import connect

CODE = 'terminal_reuse'


def ratio(n, d):
    return {'numerator': n, 'denominator': d, 'rate': n / d if d else None}


def calculate(month, inventory_run, inventory_data_month=None, source_note=None):
    with connect() as c:
        install = c.execute('''SELECT a.metric_run_id,a.report_month,a.sheet_headers FROM
            terminal_installation_reuse_audit a JOIN metric_run m ON m.metric_run_id COLLATE utf8mb4_unicode_ci=a.metric_run_id COLLATE utf8mb4_unicode_ci
            WHERE a.report_month=? AND m.status='success'
            AND EXISTS(SELECT 1 FROM intermediate_terminal_installation_reuse i WHERE i.metric_run_id COLLATE utf8mb4_unicode_ci=a.metric_run_id COLLATE utf8mb4_unicode_ci)
            ORDER BY m.started_at DESC,m.metric_run_id DESC LIMIT 1''', (month,)).fetchone()
        if not install:
            raise ValueError('缺少该月成功装机中间批次')
        inv = c.execute('SELECT * FROM terminal_inventory_reuse_audit WHERE metric_run_id=?', (inventory_run,)).fetchone()
        if not inv:
            raise ValueError('库存批次不存在')
        data_month = inventory_data_month or inv['report_month']
        if data_month != month:
            raise ValueError('库存数据所属月与报告月份不一致')
        if inv['report_month'] != data_month and not source_note:
            raise ValueError('库存入库月份与数据所属月不一致时，必须提供 --source-note 记录确认依据')
        ih = json.loads(install['sheet_headers'])['匹配']
        rows = c.execute("SELECT row_data FROM intermediate_terminal_installation_reuse WHERE metric_run_id=? AND sheet_name='匹配' ORDER BY source_row_number", (install['metric_run_id'],)).fetchall()
        vh = json.loads(inv['sheet_headers'])
        stock = c.execute("SELECT sheet_name,row_data FROM intermediate_terminal_inventory_reuse WHERE metric_run_id=? AND sheet_name IN ('sheet1','sheet2')", (inventory_run,)).fetchall()
    device_rows = defaultdict(list)
    device_stock = defaultdict(lambda: defaultdict(float))
    totals = [0., 0.]
    onu = defaultdict(lambda: [0., 0.])
    groups = defaultdict(lambda: [0., 0.])
    for item in rows:
        r = dict(zip(ih, json.loads(item['row_data'])))
        if not r.get('物料名称匹配') or not r.get('关联单据号匹配'):
            raise ValueError('匹配sheet存在不符合双重匹配条件的记录，请重算中间表')
        reuse = float(r.get('返修物资数量有SN') or 0) + float(r.get('回收物资数量有SN') or 0)
        total = float(r.get('新物资数量有SN') or 0) + reuse
        totals[0] += reuse; totals[1] += total
        device_rows[r.get('型号匹配')].append((str(r['地市']).strip().removesuffix('市'), r.get('业务类别'), reuse, total))
        if r.get('型号匹配') == 'ONU':
            city = str(r['地市']).removesuffix('市')
            for bucket in [onu[city], groups[city, r.get('业务类别')]]:
                bucket[0] += reuse; bucket[1] += total
    stock_total = 0.
    onu_stock = defaultdict(float)
    for item in stock:
        r = dict(zip(vh[item['sheet_name']], json.loads(item['row_data'])))
        n = float(r.get('可利旧数量') or 0) * (1 if item['sheet_name'] == 'sheet1' else -1)
        stock_total += n
        device_stock[r.get('物料分类')][str(r['地市']).strip().removesuffix('市')] += n
        if r.get('物料分类') == 'ONU':
            onu_stock[str(r['地市']).removesuffix('市')] += n
    charts = {}
    for business in ['MPLS VPN专线', '互联网专线', '视频监控']:
        charts[business] = [dict(city=city, **ratio(*v)) for (city, b), v in groups.items() if b == business]
    charts['ONU利用率'] = [dict(city=city, **ratio(v[0], onu_stock[city])) for city, v in onu.items()]
    for rs in charts.values():
        rs.sort(key=lambda r: (r['rate'] is None, -(r['rate'] or 0), r['city']))
    devices = {}
    for device, business in [('摄像头','视频监控'),('WIFI路由器','服务类'),('FTTO','服务类'),('专线卫士','服务类')]:
        city_all = defaultdict(lambda:[0.,0.]); city_business = defaultdict(lambda:[0.,0.])
        for city,b,n,d in device_rows[device]:
            city_all[city][0]+=n; city_all[city][1]+=d
            if b==business:
                city_business[city][0]+=n; city_business[city][1]+=d
        for city in sorted(set(onu) | set(device_stock[device])):
            city_all[city]; city_business[city]
        consumption=[dict(city=c,**ratio(*v)) for c,v in city_business.items()]
        utilization=[dict(city=c,**ratio(v[0],device_stock[device][c])) for c,v in city_all.items()]
        for values in (consumption,utilization):
            for value in values:
                if value['numerator'] == 0 and value['denominator'] == 0:
                    value['rate'] = 1.0
            values.sort(key=lambda r:(r['rate'] is None,-(r['rate'] or 0),r['city']))
        n=sum(v[0] for v in city_all.values()); d=sum(v[1] for v in city_all.values())
        devices[device]={'business':business,'consumption':ratio(n,d),
            'utilization':ratio(n,sum(device_stock[device].values())),
            'consumption_chart':consumption,'utilization_chart':utilization,
            'low_cities':[r['city'] for r in sorted((r for r in consumption if r['rate'] is not None),key=lambda r:(r['rate'],r['city']))[:3]]}
    ono_n = sum(v[0] for v in onu.values())
    return {'metric_set': CODE, 'schema_version': '1.1', 'report_month': month,
            'overall_consumption': ratio(*totals), 'overall_utilization': ratio(totals[0], stock_total),
            'devices': devices, 'onu_consumption': ratio(ono_n, sum(v[1] for v in onu.values())),
            'onu_utilization': ratio(ono_n, sum(onu_stock.values())), 'charts': charts,
            'low_onu_cities': [c for c,v in sorted(((c,v) for c,v in onu.items() if v[1]>0), key=lambda x: (x[1][0]/x[1][1],x[0]))[:3]],
            'sources': {'installation_run': install['metric_run_id'], 'inventory_run': inventory_run,
                        'inventory_recorded_month': inv['report_month'], 'inventory_data_month': data_month,
                        'month_confirmation': source_note},
            'rules': {'reuse': '返修有SN+回收有SN', 'outbound': '新物资有SN+返修有SN+回收有SN',
                      'stock': '库存sheet1减sheet2，包含未分类库存', 'onu': '型号匹配=ONU；库存物料分类=ONU',
                      'utilization': '当月利旧数量/月底可利旧库存；不封顶', 'sort': '比例降序，零分母为null置后', 'device_zero_zero': '新增设备图表0/0按用户要求标100%，属于展示约定', 'device_scope':'设备正文和库存利用率统计全部业务；摄像头耗用图限视频监控，WIFI路由器/FTTO/专线卫士耗用图限服务类；靠后地市按对应耗用图升序取三名'}}



def save(r, now):
    schema = (ROOT/'sql/create_terminal_reuse_results.sql').read_text(encoding='utf-8')
    with connect() as c:
        for statement in schema.split(';'):
            if statement.strip(): c.execute(statement)
    month=r['report_month']; dt=datetime.strptime(month,'%Y-%m')
    with connect() as c:
        c.execute('''INSERT INTO metric_run(metric_run_id,metric_code,metric_version,period_start,period_end,started_at,finished_at,status,source_runs)
            VALUES (?,?,?,?,?,?,?,?,?)''', (r['metric_run_id'], CODE, '1.1', month+'-01',
            f'{month}-{calendar.monthrange(dt.year,dt.month)[1]:02d}',now,now,'success',json.dumps(r['sources'],ensure_ascii=False)))
        results=[]
        for key in ['overall_consumption','overall_utilization','onu_consumption','onu_utilization']:
            value=r[key]
            results.append((r['metric_run_id'],key,'province',json.dumps({'month':month,'scope':'全省'},ensure_ascii=False),value['numerator'],value['denominator'],value['rate']))
        for business,rows in r['charts'].items():
            for value in rows:
                results.append((r['metric_run_id'],'onu_utilization' if business=='ONU利用率' else 'onu_business_consumption',
                    'city',json.dumps({'month':month,'city':value['city'],'business':business},ensure_ascii=False),value['numerator'],value['denominator'],value['rate']))
        for device, item in r.get('devices',{}).items():
            for key in ['consumption','utilization']:
                v=item[key]
                results.append((r['metric_run_id'],'device_'+key,'province',json.dumps({'month':month,'device':device},ensure_ascii=False),v['numerator'],v['denominator'],v['rate']))
                for v in item[key+'_chart']:
                    results.append((r['metric_run_id'],'device_'+key,'city',json.dumps({'month':month,'device':device,'city':v['city'],'business':item['business'] if key=='consumption' else '全部业务'},ensure_ascii=False),v['numerator'],v['denominator'],v['rate']))
        c.executemany('''INSERT INTO result_terminal_reuse
            (metric_run_id,metric_code,dimension_type,dimension_value,numerator,denominator,metric_value)
            VALUES (?,?,?,?,?,?,?)''',results)
        c.execute('INSERT INTO terminal_reuse_result_audit (metric_run_id,report_month,result_json) VALUES (?,?,?)',
                  (r['metric_run_id'],month,json.dumps(r,ensure_ascii=False,allow_nan=False)))

def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--month', required=True)
    p.add_argument('--inventory-run', required=True)
    p.add_argument('--inventory-data-month', help='原始库存所属月；与入库月份不同时须说明依据')
    p.add_argument('--source-note', help='库存月份确认依据，不修改原批次')
    p.add_argument('--output-dir', type=Path, default=ROOT/'outputs/terminal_reuse')
    args = p.parse_args()
    dt = datetime.strptime(args.month, '%Y-%m')
    r = calculate(args.month, args.inventory_run, args.inventory_data_month, args.source_note)
    r['metric_run_id'] = 'terminal_reuse_' + uuid.uuid4().hex
    now = datetime.now().isoformat()
    save(r, now)
    args.output_dir.mkdir(parents=True,exist_ok=True)
    path=args.output_dir/f'终端利旧指标_{args.month}.json'
    path.write_text(json.dumps(r,ensure_ascii=False,indent=2),encoding='utf-8')
    print(json.dumps({'file':str(path),'metric_run_id':r['metric_run_id'],'summary':r['overall_consumption']},ensure_ascii=False))


if __name__ == '__main__':
    main()
