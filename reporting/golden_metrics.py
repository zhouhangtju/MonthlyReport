"""点金全省指标：按26日至25日的完整周期快照读取。"""
import calendar
import math
import re
from datetime import date, timedelta
from storage.database import connect
from storage.raw_tables import read_records

METRICS = [
    ('退撤单率', '≤5%', 5, 'max', '业务开通前端退单率', '业务开通前端退单率(%)'),
    ('开通配置平均时长(工作小时)', '4小时内', 4, 'max', '线上配置环节平均时长', '开通配置平均时长(小时)'),
    ('资源分配成功率(%)', '≥90%', 90, 'min', '资源分配成功率', '资源分配成功率（%）'),
    ('业务开通装机一次上门率(%)', '≥95%', 95, 'min', '装机一次上门率', '业务开通装机一次上门率(%)'),
]

def number(value):
    if value is None or str(value).strip() == '':
        return None
    match = re.fullmatch(r'\s*(\d+(?:\.\d+)?)\s*(?:%|\([^)]*\))?\s*', str(value))
    if not match:
        raise ValueError(f'点金指标格式无法识别：{value!r}')
    result = float(match[1])
    if not math.isfinite(result):
        raise ValueError('点金指标不是有限数值')
    return result


def province(rows, kind):
    rows = [r for r in rows if r.get('地市') == '全省' and
            (kind == 'cloud' or all(r.get(k) == '不区分' for k in ('有无资源开通场景', '接入方式')))]
    if len(rows) > 1:
        raise ValueError('点金报表全省行不唯一')
    return rows[0] if rows else {}


def build_golden(month, connection=None):
    year, end_month = map(int, str(month).split('-'))
    if connection is None:
        with connect(None) as connection:
            return build_golden(month, connection)
    months = [f'{year}-{m:02d}' for m in range(1, end_month + 1)]
    groups=[]
    missing=[]
    for kind, title in [('cloud','云专线业务开通'),('transport','数据专线业务开通'),('internet','互联网专线业务开通')]:
        records=[]
        for m in range(1,end_month+1):
            previous=date(year,m,1)-timedelta(days=1)
            start=date(previous.year,previous.month,26).isoformat()
            end=date(year,m,25).isoformat()
            code='orch_golden_'+kind
            snapshot=connection.execute('SELECT run_id FROM raw_period_batch WHERE dataset_code=? AND period_start=? AND period_end=?',(code,start,end)).fetchone()
            row=province(read_records(connection,code,start,end),kind) if snapshot else {}
            if not row:
                missing.append({'dataset':code,'start':start,'end':end})
            records.append(row)
        metrics=[]
        for i,(label,target,limit,direction,cloud,other) in enumerate(METRICS):
            values=[number(r.get(cloud if kind=='cloud' else other)) for r in records]
            metrics.append({'label':label,'target':target,'values':values,'hours':i==1,
                            'failed':[v is not None and (v>limit if direction=='max' else v<limit) for v in values]})
        groups.append({'title':title,'metrics':metrics})
    return {'months':months,'groups':groups,'missing':missing}
