const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');
// Exercise the actual inline functions without starting PPT generation.
const source = fs.readFileSync(path.join(__dirname, '../reporting/create_internet_line_ppt.js'), 'utf8');
const block = source.split('// BEGIN REPORT NARRATIVES')[1]?.split('// END REPORT NARRATIVES')[0];
assert.ok(block, 'Inline narrative functions must be present');
const n = vm.runInNewContext(block + '\nnarratives;');
const cities = ['杭州', '宁波', '嘉兴', '绍兴'];
assert.equal(n.topCities(cities, [.1,.3,.4,.2]), '嘉兴、宁波、绍兴');
assert.equal(n.topCities(cities, [null,.3,.3,NaN]), '宁波、嘉兴');
assert.equal(n.period('2026-08', true), '26年6月至26年8月');
assert.equal(n.period('2026-01', false), '25年11月至26年1月');
const d = {currentMonth:'2026-08', displayMonth:'8月',
  dataAudit:{missing:[{ppt_field:'withdrawal.completionCount'}]},
  withdrawal:{completionCount:0, currentAcceptedCompletion:10, previousAcceptedCompletion:20,
    withdrawalCount:148, withdrawalRate:.0225},
  complaintFault:{repeat:{cities,lineRates:[.1,.3,.4,.2],qikuanRates:[.2,.5,.4,.1],
    lineAverage:.1,qikuanAverage:.2,totalAverage:.15},
    fault:{cities,totalRates:[.4,.2,.3,.1],totalAverage:.1,lineAverage:.1,broadbandAverage:.2}},
  internetAuto:{manualReasons:{cities,province:{'工程施工占比':.9,'空原因占比':.01},
    byCity:{'杭州':{'非自动工单数':10,'工程施工工单数':10},
      '宁波':{'非自动工单数':10,'工程施工工单数':8}}}}};
assert.match(n.withdrawal(d), /全省专线开通单竣工量待填充单/);
assert.match(n.withdrawal(d), /7月之前受理的竣工量20单/);
assert.match(n.repeat(d), /专线重复投诉率10.00%，嘉兴、宁波、绍兴较高/);
assert.match(n.repeat(d), /企宽重复投诉率20.00%，宁波、嘉兴、杭州较高/);
assert.match(n.fault(d), /新装报障率较高地市为杭州、嘉兴、宁波/);
const q={cities,rates:[.2,.1,.4,.3],overallRate:.25,withdrawalTotal:1234,
  reasons:Object.fromEntries(['customer','frontDesk','construction','other','network'].map(k=>[k,{count:1,share:.2}]))};
assert.match(n.qikuan(d,q,false), /含撤退单后重录并报结\)1234单，撤退率25.00%，其中嘉兴、绍兴、杭州撤退率较高/);
assert.match(n.qikuan(d,q,true), /不含一次性撤单）1234单，退单率25.00%/);
assert.equal(n.network(d).cities, '杭州');
assert.equal(n.network(d).summary, '主要非自动原因：工程施工（占比90.00%）、非自动原因为空（占比1.00%）');
console.log('Narrative templates, placeholders, month boundaries and city rankings passed.');
