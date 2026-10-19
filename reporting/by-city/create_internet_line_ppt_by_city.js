const pptxgen = require('pptxgenjs');
const fs = require('fs');

const dataPath = process.argv[2];
const outputPath = process.argv[3];
if (!dataPath || !outputPath) {
  throw new Error('用法：node create_internet_line_ppt_by_city.js data.json output.pptx');
}
const D = JSON.parse(fs.readFileSync(dataPath, 'utf8'));
const pptx = new pptxgen();
pptx.layout = 'LAYOUT_WIDE';
pptx.author = '浙江移动客响中心';
pptx.subject = `${D.city}业务发展情况`;
pptx.title = `${D.city}业务发展量-专线产品开通情况`;
pptx.company = '中国移动';
pptx.lang = 'zh-CN';
pptx.theme = {
  headFontFace: 'Microsoft YaHei', bodyFontFace: 'Microsoft YaHei', lang: 'zh-CN',
};

const C = {
  blue: '078CCA', deepBlue: '0070C0', ink: '222222', gray: '666666',
  lightGray: 'CBD4DF', white: 'FFFFFF', green: '00B050', red: 'FF1F3D', lime: '70C800',
};
const SERIES = ['11B6D8', 'E75B5B', '86C85B', '9B7BC4', 'F28E2B', '3572B0'];
const SINGLE = '168BC2';

function finite(value) { return typeof value === 'number' && Number.isFinite(value); }
function fmt(value) { return finite(value) ? Math.round(value).toLocaleString('zh-CN') : '待填充'; }
function ceilFmt(value) { return finite(value) ? Math.ceil(value).toLocaleString('zh-CN') : '待填充'; }
function pct(value) { return finite(value) ? `${Math.abs(value * 100).toFixed(2)}%` : '待填充'; }
function direction(value) { return !finite(value) ? '' : value > 0 ? '上升' : value < 0 ? '下降-' : '持平'; }
function changeColor(value) { return !finite(value) ? C.gray : value >= 0 ? C.green : C.red; }
function axisMax(series) {
  const values = series.flatMap(item => item.values || []).filter(finite);
  const top = Math.max(1, ...values);
  return Math.ceil(top * 1.25 / 10) * 10;
}
function addBackground(slide) { slide.background = { color: C.white }; }
function addHeader(slide) {
  slide.addText('业务发展量-专线产品开通情况', {
    x: 0.28, y: 0.14, w: 7.4, h: 0.4, fontFace: 'Microsoft YaHei',
    fontSize: 27, bold: true, color: C.white, margin: 0,
  });
}
function addPanel(slide, x, y, w, h) {
  slide.addShape(pptx.ShapeType.rect, { x, y, w, h, fill: { color: C.white }, line: { color: C.lightGray, width: 0.8 } });
}
function addPill(slide, text, x, y, w) {
  slide.addShape(pptx.ShapeType.roundRect, { x, y, w, h: 0.28, rectRadius: 0.06, fill: { color: C.blue }, line: { color: C.blue } });
  slide.addText(text, { x, y: y + 0.015, w, h: 0.24, fontFace: 'Microsoft YaHei', fontSize: 12, bold: true, color: C.white, align: 'center', margin: 0, fit: 'shrink' });
}
function addPage(slide, page) {
  slide.addText(String(page), { x: 12.65, y: 7.18, w: 0.28, h: 0.18, fontFace: 'Microsoft YaHei', fontSize: 8, color: C.gray, align: 'right', margin: 0 });
}
function addFootnote(slide, business, page) {
  slide.addText(`口径：订单结束时间；订单状态=已完成；业务类型=${business}；订单类型=开通；按订单号去重。数据源：${D.sourceFileName}`, {
    x: 0.38, y: 7.21, w: 11.9, h: 0.16, fontFace: 'Microsoft YaHei', fontSize: 7.5, color: C.gray, margin: 0,
  });
  addPage(slide, page);
}
function barOptions(x, y, w, h, colors, maxValue, legend = false, labelSize = 8) {
  return {
    x, y, w, h,
    catAxisLabelFontFace: 'Microsoft YaHei', catAxisLabelFontSize: labelSize,
    catAxisLabelColor: C.ink, catAxisLineColor: C.lightGray,
    catAxisLabelRotate: 0,
    valAxisMinVal: 0, valAxisMaxVal: maxValue,
    valAxisLabelPos: 'none', valAxisLineShow: false,
    valAxisMajorTickMark: 'none', valAxisMinorTickMark: 'none',
    valGridLine: { color: C.white, transparency: 100 },
    showLegend: legend, legendPos: 't', legendFontFace: 'Microsoft YaHei', legendFontSize: 8,
    showTitle: false, showValue: true, dataLabelPosition: 'outEnd', dataLabelColor: C.ink,
    dataLabelFontFace: 'Microsoft YaHei', dataLabelFormatCode: '0', dataLabelFontSize: 7,
    chartColors: colors, gapWidthPct: legend ? 45 : 85, overlap: 0,
    border: { color: C.white, transparency: 100 },
  };
}

// 1. 封面
const cover = pptx.addSlide();
addBackground(cover);
cover.addText('集客综调月报', { x: 3.7, y: 2.45, w: 5.95, h: 0.78, fontFace: 'Microsoft YaHei', fontSize: 38, bold: true, color: C.deepBlue, margin: 0, align: 'center' });
cover.addText(`${D.city}业务发展情况`, { x: 4.1, y: 3.42, w: 5.15, h: 0.48, fontFace: 'Microsoft YaHei', fontSize: 24, bold: true, color: C.blue, margin: 0, align: 'center' });
cover.addText('浙江移动客响中心', { x: 4.6, y: 4.85, w: 4.15, h: 0.34, fontFace: 'Microsoft YaHei', fontSize: 20, bold: true, color: C.deepBlue, margin: 0, align: 'center' });
cover.addText(D.displayMonthFull, { x: 4.6, y: 5.25, w: 4.15, h: 0.36, fontFace: 'Microsoft YaHei', fontSize: 21, bold: true, color: C.deepBlue, margin: 0, align: 'center' });
cover.addNotes(`${D.city}业务发展情况，统计月份：${D.displayMonthFull}。`);

// 2. 目录
const toc = pptx.addSlide();
addBackground(toc);
toc.addText('目  录', { x: 0.22, y: 0.14, w: 2.2, h: 0.4, fontFace: 'Microsoft YaHei', fontSize: 28, bold: true, color: C.white, margin: 0 });
[
  ['01', '业务发展情况', '438FD8'], ['02', '专线自动情况', 'BDBDBD'],
  ['03', '终端回收情况', 'BDBDBD'], ['04', '业务支撑情况', 'BDBDBD'],
].forEach((item, index) => {
  const y = 1.9 + index * 0.9;
  toc.addText(item[0], { x: 3.45, y: y + 0.1, w: 0.5, h: 0.34, fontFace: 'Microsoft YaHei', fontSize: 20, bold: true, color: item[2], margin: 0, align: 'right' });
  toc.addShape(pptx.ShapeType.parallelogram, { x: 4.16, y, w: 4.95, h: 0.55, fill: { color: item[2] }, line: { color: item[2] } });
  toc.addText(item[1], { x: 4.42, y: y + 0.1, w: 4.25, h: 0.34, fontFace: 'Microsoft YaHei', fontSize: 22, bold: true, color: C.white, align: 'center', margin: 0 });
});
toc.addText(`${D.city} · ${D.displayMonthFull}`, { x: 4.1, y: 5.9, w: 5.2, h: 0.3, fontFace: 'Microsoft YaHei', fontSize: 14, color: C.deepBlue, align: 'center', margin: 0 });
addPage(toc, 2);

// 3. 互联网专线总览
const internet = pptx.addSlide();
addBackground(internet); addHeader(internet);
internet.addText([
  { text: `${D.displayMonth}${D.city}互联网专线已完成 `, options: { bold: true, color: C.ink } },
  { text: `${fmt(D.currentTotal)}单`, options: { bold: true, color: C.deepBlue } },
  { text: '，同比 ', options: { bold: true, color: C.ink } },
  { text: `${direction(D.yoy)}${pct(D.yoy)}`, options: { bold: true, color: changeColor(D.yoy) } },
  { text: '，环比 ', options: { bold: true, color: C.ink } },
  { text: `${direction(D.mom)}${pct(D.mom)}`, options: { bold: true, color: changeColor(D.mom) } },
  { text: '。其中悦享动态IP版 ', options: { bold: true, color: C.ink } },
  { text: `${fmt(D.keyProducts['悦享专线动态IP版'])}单`, options: { bold: true, color: C.deepBlue } },
  { text: '（同比', options: { bold: true, color: C.ink } },
  { text: `${direction(D.keyProductYoy['悦享专线动态IP版'])}${pct(D.keyProductYoy['悦享专线动态IP版'])}`, options: { bold: true, color: changeColor(D.keyProductYoy['悦享专线动态IP版']) } },
  { text: '），互联网专线套餐 ', options: { bold: true, color: C.ink } },
  { text: `${fmt(D.keyProducts['互联网专线套餐'])}单`, options: { bold: true, color: C.deepBlue } },
  { text: '，商务专线套餐（2020版） ', options: { bold: true, color: C.ink } },
  { text: `${fmt(D.keyProducts['商务专线套餐（2020版）'])}单`, options: { bold: true, color: C.deepBlue } },
  { text: '。', options: { bold: true, color: C.ink } },
], { x: 0.35, y: 0.77, w: 12.6, h: 0.7, fontFace: 'Microsoft YaHei', fontSize: 14.5, margin: 0, valign: 'mid', fit: 'shrink' });
addPanel(internet, 0.35, 1.63, 5.35, 2.22); addPanel(internet, 5.83, 1.63, 7.15, 2.22);
addPill(internet, `${D.city}互联网专线产品开通情况`, 1.55, 1.50, 3.05);
addPill(internet, `${D.city}各区县互联网专线产品开通情况`, 7.75, 1.50, 3.65);
const cityProductValues = D.cityProducts.map(item => item.value);
internet.addChart(pptx.ChartType.bar, [{ name: '订单量', labels: D.cityProducts.map(item => item.label), values: cityProductValues }], barOptions(0.36, 1.82, 5.12, 1.96, [SINGLE], axisMax([{ values: cityProductValues }]), false, 8));
internet.addChart(pptx.ChartType.bar, D.countySeries.map(item => ({ name: item.name, labels: D.counties, values: item.values })), barOptions(5.94, 1.74, 6.96, 2.06, SERIES, axisMax(D.countySeries), true, D.counties.length > 12 ? 6 : 7));
internet.addText([
  { text: `${D.trendPeriodText}，悦享专线动态IP版累计 `, options: { bold: true, color: C.ink } },
  { text: `${fmt(D.trendSummary['悦享专线动态IP版'].sum)}单`, options: { bold: true, color: C.deepBlue } },
  { text: `，月均 ${ceilFmt(D.trendSummary['悦享专线动态IP版'].average)}单；互联网专线套餐累计 `, options: { bold: true, color: C.ink } },
  { text: `${fmt(D.trendSummary['互联网专线套餐'].sum)}单`, options: { bold: true, color: C.deepBlue } },
  { text: `，月均 ${ceilFmt(D.trendSummary['互联网专线套餐'].average)}单；其他产品累计 ${fmt(D.otherTrendSummary.sum)}单，月均 ${ceilFmt(D.otherTrendSummary.average)}单。`, options: { bold: true, color: C.ink } },
], { x: 0.38, y: 3.98, w: 12.5, h: 0.56, fontFace: 'Microsoft YaHei', fontSize: 14, margin: 0, fit: 'shrink' });
addPanel(internet, 0.35, 4.81, 12.63, 2.2);
addPill(internet, `${D.trendPeriodShort} ${D.city}悦享专线动态IP版开通情况`, 4.35, 4.68, 4.65);
const enjoy = D.trendSeries.find(item => item.name === '悦享专线动态IP版');
internet.addChart(pptx.ChartType.bar, [{ name: enjoy.name, labels: D.months, values: enjoy.values }], barOptions(0.55, 4.91, 12.2, 1.92, [SINGLE], axisMax([enjoy]), false, 8));
addFootnote(internet, '互联网专线', 3);

// 4. 互联网套餐和其他产品趋势
const trends = pptx.addSlide(); addBackground(trends); addHeader(trends);
addPanel(trends, 0.35, 0.98, 12.63, 2.83); addPill(trends, `${D.trendPeriodShort} ${D.city}互联网专线套餐开通情况`, 4.35, 0.85, 4.65);
trends.addChart(pptx.ChartType.bar, [{ name: D.packageTrend.name, labels: D.months, values: D.packageTrend.values }], barOptions(0.55, 1.2, 12.2, 2.3, [SINGLE], axisMax([D.packageTrend]), false, 8));
addPanel(trends, 0.35, 4.16, 12.63, 2.83); addPill(trends, `${D.trendPeriodShort} ${D.city}互联网专线其他产品开通情况`, 4.2, 4.03, 4.95);
trends.addChart(pptx.ChartType.bar, [{ name: D.otherTrend.name, labels: D.months, values: D.otherTrend.values }], barOptions(0.55, 4.38, 12.2, 2.3, [SINGLE], axisMax([D.otherTrend]), false, 8));
addFootnote(trends, '互联网专线', 4);

function addLineOverview(group, businessLabel, page, productLabels, colors) {
  const slide = pptx.addSlide(); addBackground(slide); addHeader(slide);
  slide.addText([
    { text: `${D.displayMonth}${D.city}${businessLabel}开通 `, options: { bold: true, color: C.ink } },
    { text: `${fmt(group.currentTotal)}单`, options: { bold: true, color: C.deepBlue } },
    { text: '，同比 ', options: { bold: true, color: C.ink } },
    { text: `${direction(group.totalYoy)}${pct(group.totalYoy)}`, options: { bold: true, color: changeColor(group.totalYoy) } },
    { text: `。${group.products.map(item => `${item.name}${fmt(item.value)}单`).join('，')}。`, options: { bold: true, color: C.ink } },
  ], { x: 0.35, y: 0.82, w: 12.6, h: 0.55, fontFace: 'Microsoft YaHei', fontSize: 15, margin: 0, fit: 'shrink' });
  addPanel(slide, 0.35, 1.55, 4.25, 2.2); addPanel(slide, 4.72, 1.55, 8.26, 2.2);
  addPill(slide, `${D.city}${businessLabel}产品开通情况`, 0.95, 1.42, 3.05);
  addPill(slide, `各区县${businessLabel}产品开通情况`, 6.95, 1.42, 4.05);
  const values = group.products.map(item => item.value);
  const productChartOptions = barOptions(
    0.58, 1.85, 3.8, businessLabel === '传输专线' ? 1.34 : 1.65,
    [SINGLE], axisMax([{ values }]), false, 7,
  );
  if (businessLabel === '传输专线') productChartOptions.catAxisLabelPos = 'none';
  slide.addChart(pptx.ChartType.bar, [{ name: '订单量', labels: productLabels, values }], productChartOptions);
  if (businessLabel === '传输专线') {
    const labelWidth = 3.8 / productLabels.length;
    productLabels.forEach((label, index) => {
      slide.addText(label, {
        x: 0.58 + index * labelWidth, y: 3.22, w: labelWidth, h: 0.42,
        fontFace: 'Microsoft YaHei', fontSize: 6.5, color: C.ink,
        align: 'center', valign: 'top', margin: 0, breakLine: false,
        fit: 'shrink',
      });
    });
  }
  slide.addChart(pptx.ChartType.bar, group.countySeries.map(item => ({ name: item.name, labels: group.counties, values: item.values })), barOptions(5.02, 1.74, 7.73, 1.82, colors, axisMax(group.countySeries), true, group.counties.length > 12 ? 6 : 7));
  addPanel(slide, 0.35, 4.16, 12.63, 2.83); addPill(slide, `${group.periodShort} ${D.city}${businessLabel}开通情况`, 4.25, 4.03, 4.85);
  slide.addChart(pptx.ChartType.bar, [{ name: `${businessLabel}合计`, labels: group.months, values: group.trend }], barOptions(0.55, 4.4, 12.2, 2.3, [SINGLE], axisMax([{ values: group.trend }]), false, 8));
  addFootnote(slide, businessLabel.replace('开通', ''), page);
  return slide;
}

addLineOverview(D.mpls, 'MPLS-VPN专线', 5, ['地区内\nMPLSVPN套餐', '省内\nMPLSVPN套餐'], ['5B9BD5', 'E75B5B']);
addLineOverview(D.transmission, '传输专线', 6, [
  '光纤出租\n套餐', '地区内数字\n电路出租套餐', '地区间\n精品电路',
  '地区内SPN\n电路出租', '地区间数字\n电路出租套餐', '地区内\n精品电路',
], SERIES);

// 7. 专线自动情况目录
const autoToc = pptx.addSlide();
addBackground(autoToc);
autoToc.addText('目  录', { x: 0.22, y: 0.14, w: 2.2, h: 0.4, fontFace: 'Microsoft YaHei', fontSize: 28, bold: true, color: C.white, margin: 0 });
[
  ['01', '业务发展情况', 'BDBDBD'], ['02', '专线自动情况', '438FD8'],
  ['03', '终端回收情况', 'BDBDBD'], ['04', '业务支撑情况', 'BDBDBD'],
].forEach((item, index) => {
  const y = 1.9 + index * 0.9;
  autoToc.addText(item[0], { x: 3.45, y: y + 0.1, w: 0.5, h: 0.34, fontFace: 'Microsoft YaHei', fontSize: 20, bold: true, color: item[2], margin: 0, align: 'right' });
  autoToc.addShape(pptx.ShapeType.parallelogram, { x: 4.16, y, w: 4.95, h: 0.55, fill: { color: item[2] }, line: { color: item[2] } });
  autoToc.addText(item[1], { x: 4.42, y: y + 0.1, w: 4.25, h: 0.34, fontFace: 'Microsoft YaHei', fontSize: 22, bold: true, color: C.white, align: 'center', margin: 0 });
});
autoToc.addText(`${D.city} · ${D.displayMonthFull}`, { x: 4.1, y: 5.9, w: 5.2, h: 0.3, fontFace: 'Microsoft YaHei', fontSize: 14, color: C.deepBlue, align: 'center', margin: 0 });
addPage(autoToc, 7);

function rateOptions(x, y, w, h, maxValue = 1, labelSize = 8) {
  const options = barOptions(x, y, w, h, [SINGLE], maxValue, false, labelSize);
  options.dataLabelFormatCode = '0.00%';
  return options;
}

function addAutoHeader(slide, title) {
  slide.addText(title, { x: 0.28, y: 0.14, w: 8.2, h: 0.4, fontFace: 'Microsoft YaHei', fontSize: 27, bold: true, color: C.white, margin: 0 });
}

function stageSeries(group, stage) {
  return group.countyStageSeries.find(item => item.name === stage)?.values || group.counties.map(() => 0);
}
function addRateChart(slide, labels, values, x, y, w, h, labelSize = 8) {
  slide.addChart(pptx.ChartType.bar, [{ name: '自动率', labels, values }], rateOptions(x, y, w, h, 1.08, labelSize));
}
function addAutoSummary(slide, group, orderLabel) {
  slide.addText([
    { text: `${D.displayMonthFull}，${D.city}互联网专线${orderLabel}工单`, options: { bold: true, color: C.ink } },
    { text: `整体自动率${pct(group.overall)}`, options: { bold: true, color: C.green } },
    { text: `（自动环节数${fmt(group.automaticCount)}，总环节数${fmt(group.totalCount)}）。`, options: { bold: true, color: C.ink } },
  ], { x: 0.52, y: 0.89, w: 12.2, h: 0.42, fontFace: 'Microsoft YaHei', fontSize: 16, margin: 0, valign: 'mid', fit: 'shrink' });
}

// Page 8：完全沿用省级开通自动率页框架，地市维度替换为标准区县。
const openingAuto = pptx.addSlide(); addBackground(openingAuto); addAutoHeader(openingAuto, '专线自动率（互联网专线-开通）');
addAutoSummary(openingAuto, D.internetAuto, '开通');
addPanel(openingAuto, 0.48, 1.42, 5.82, 1.96);
addPanel(openingAuto, 6.38, 1.42, 6.25, 1.96);
addPanel(openingAuto, 0.58, 4.18, 5.82, 2.55);
openingAuto.addText('开通各环节自动率', { x: 2.15, y: 1.53, w: 2.7, h: 0.24, fontFace: 'Microsoft YaHei', fontSize: 11, bold: true, color: C.ink, align: 'center', margin: 0 });
openingAuto.addText('各区县组网环节自动率', { x: 8.25, y: 1.53, w: 2.7, h: 0.24, fontFace: 'Microsoft YaHei', fontSize: 11, bold: true, color: C.ink, align: 'center', margin: 0 });
openingAuto.addText('非自动原因工单数（工程施工）', { x: 1.68, y: 4.31, w: 3.65, h: 0.24, fontFace: 'Microsoft YaHei', fontSize: 11, bold: true, color: C.ink, align: 'center', margin: 0 });
addRateChart(openingAuto, D.internetAuto.stages.map(x => x.name === '开通结果审核' ? '开通结果\n审核' : x.name), D.internetAuto.stages.map(x => x.value), 0.67, 1.72, 5.42, 1.50, 8);
addRateChart(openingAuto, D.internetAuto.counties, stageSeries(D.internetAuto, '组网方案'), 6.57, 1.72, 5.85, 1.50, D.internetAuto.counties.length > 12 ? 6 : 8);
openingAuto.addChart(pptx.ChartType.bar, [{ name: '工程施工工单数', labels: D.internetAuto.counties, values: D.internetAuto.engineeringCounts }], barOptions(0.77, 4.61, 5.42, 1.78, [SINGLE], axisMax([{ values: D.internetAuto.engineeringCounts }]), false, D.internetAuto.counties.length > 12 ? 6 : 8));
const networkReasons = D.internetAuto.manualReasons || {};
const constructionCounties = networkReasons.allEngineeringCounties || [];
openingAuto.addText([
  { text: '组网环节：', options: { bold: true, breakLine: true } },
  { text: `主要非自动原因：工程施工（占比${pct(networkReasons.engineeringShare)}）、非自动原因为空（占比${pct(networkReasons.blankShare)}）`, options: { breakLine: true } },
  { text: constructionCounties.join('、'), options: { color: C.red, bold: true } },
  { text: constructionCounties.length ? '非自动原因为工程施工（占比100%）' : '暂无区县的工程施工原因占比达到100%', options: { color: C.ink } },
], { x: 0.43, y: 3.52, w: 6.3, h: 0.65, fontFace: 'Microsoft YaHei', fontSize: 11.5, color: C.ink, margin: 0, valign: 'top' });
openingAuto.addText('口径：自动率按清洗后工单统计，共9个环节；处理人含“自动”即自动，资管同一环节取结束时间最新记录。原因说明沿用资管原因结果。', { x: 0.45, y: 7.16, w: 11.9, h: 0.18, fontFace: 'Microsoft YaHei', fontSize: 7.5, color: C.gray, margin: 0 });
addPage(openingAuto, 8);

// Page 9：完全沿用省级移机自动率页四面板框架。
const moveAuto = pptx.addSlide(); addBackground(moveAuto); addAutoHeader(moveAuto, '专线自动率（互联网专线-移机）');
addAutoSummary(moveAuto, D.internetMoveAuto, '移机');
[[0.75,1.42,6.02,2.43],[6.84,1.42,6.02,2.43],[0.75,3.91,6.02,2.43],[6.84,3.91,6.02,2.43]].forEach(v => addPanel(moveAuto, ...v));
[['移机各环节自动率',2.35,1.55,2.8],['各区县组网环节自动率',8.45,1.55,2.8],['各区县资源反馈环节自动率',2.18,4.04,3.2],['各区县配置激活环节自动率',8.27,4.04,3.2]].forEach(([label,x,y,w]) => moveAuto.addText(label,{x,y,w,h:0.24,fontFace:'Microsoft YaHei',fontSize:11,bold:true,color:C.ink,align:'center',margin:0}));
addRateChart(moveAuto, D.internetMoveAuto.stages.map(x => x.name === '开通结果审核' ? '开通结果\n审核' : x.name), D.internetMoveAuto.stages.map(x => x.value), 0.94, 1.82, 5.63, 1.76, 8);
addRateChart(moveAuto, D.internetMoveAuto.counties, stageSeries(D.internetMoveAuto, '组网方案'), 7.03, 1.82, 5.63, 1.76, D.internetMoveAuto.counties.length > 12 ? 6 : 8);
addRateChart(moveAuto, D.internetMoveAuto.counties, stageSeries(D.internetMoveAuto, '资源反馈'), 0.94, 4.31, 5.63, 1.76, D.internetMoveAuto.counties.length > 12 ? 6 : 8);
addRateChart(moveAuto, D.internetMoveAuto.counties, stageSeries(D.internetMoveAuto, '配置激活'), 7.03, 4.31, 5.63, 1.76, D.internetMoveAuto.counties.length > 12 ? 6 : 8);
moveAuto.addText('口径：整体自动率=9个环节自动数之和/(清洗后变更工单数×9)；处理人含“自动”即自动，资管环节取最新记录；变更按移机统计。', { x: 0.45, y: 7.13, w: 12.0, h: 0.2, fontFace: 'Microsoft YaHei', fontSize: 7.5, color: C.gray, margin: 0 });
addPage(moveAuto, 9);

// Page 10：完全沿用省级拆机自动率页三面板框架。
const removalAuto = pptx.addSlide(); addBackground(removalAuto); addAutoHeader(removalAuto, '专线自动率（互联网专线-拆机）');
addAutoSummary(removalAuto, D.internetRemovalAuto, '拆机');
addPanel(removalAuto, 0.52, 1.42, 5.82, 2.28); addPanel(removalAuto, 6.43, 1.42, 6.38, 2.28); addPanel(removalAuto, 0.52, 3.82, 5.82, 2.58);
[['拆机各环节自动率',2.08,1.55,2.7],['各区县配置激活环节自动率',8.15,1.55,3.0],['各区县组织资源释放环节自动率',1.77,3.95,3.35]].forEach(([label,x,y,w]) => removalAuto.addText(label,{x,y,w,h:0.24,fontFace:'Microsoft YaHei',fontSize:11,bold:true,color:C.ink,align:'center',margin:0}));
addRateChart(removalAuto, D.internetRemovalAuto.stages.map(x => x.name === '开通结果审核' ? '开通结果\n审核' : x.name), D.internetRemovalAuto.stages.map(x => x.value), 0.72, 1.82, 5.42, 1.62, 8);
addRateChart(removalAuto, D.internetRemovalAuto.counties, stageSeries(D.internetRemovalAuto, '配置激活'), 6.64, 1.82, 5.94, 1.62, D.internetRemovalAuto.counties.length > 12 ? 6 : 8);
addRateChart(removalAuto, D.internetRemovalAuto.counties, stageSeries(D.internetRemovalAuto, '组织资源释放'), 0.72, 4.26, 5.42, 1.82, D.internetRemovalAuto.counties.length > 12 ? 6 : 8);
removalAuto.addText('口径：整体自动率=6个环节自动数之和/(清洗后拆除工单数×6)；处理人含“自动”即自动，组织资源释放取最新记录，未匹配计非自动。', { x: 0.45, y: 7.13, w: 12.0, h: 0.2, fontFace: 'Microsoft YaHei', fontSize: 7.5, color: C.gray, margin: 0 });
addPage(removalAuto, 10);

// 11. 终端回收情况目录。第12、13页在 Python 构建阶段由省级终端回收模板替换。
const terminalToc = pptx.addSlide();
addBackground(terminalToc);
terminalToc.addText('目  录', { x: 0.22, y: 0.14, w: 2.2, h: 0.4, fontFace: 'Microsoft YaHei', fontSize: 28, bold: true, color: C.white, margin: 0 });
[
  ['01', '业务发展情况', 'BDBDBD'], ['02', '专线自动情况', 'BDBDBD'],
  ['03', '终端回收情况', '438FD8'], ['04', '业务支撑情况', 'BDBDBD'],
].forEach((item, index) => {
  const y = 1.9 + index * 0.9;
  terminalToc.addText(item[0], { x: 3.45, y: y + 0.1, w: 0.5, h: 0.34, fontFace: 'Microsoft YaHei', fontSize: 20, bold: true, color: item[2], margin: 0, align: 'right' });
  terminalToc.addShape(pptx.ShapeType.parallelogram, { x: 4.16, y, w: 4.95, h: 0.55, fill: { color: item[2] }, line: { color: item[2] } });
  terminalToc.addText(item[1], { x: 4.42, y: y + 0.1, w: 4.25, h: 0.34, fontFace: 'Microsoft YaHei', fontSize: 22, bold: true, color: C.white, align: 'center', margin: 0 });
});
terminalToc.addText(`${D.city} · ${D.displayMonthFull}`, { x: 4.1, y: 5.9, w: 5.2, h: 0.3, fontFace: 'Microsoft YaHei', fontSize: 14, color: C.deepBlue, align: 'center', margin: 0 });
addPage(terminalToc, 11);

for (const page of [12, 13]) {
  const placeholder = pptx.addSlide();
  addBackground(placeholder);
  addAutoHeader(placeholder, '终端回收情况');
  placeholder.addText('终端回收模板内容将在构建阶段写入', { x: 3.2, y: 3.2, w: 6.9, h: 0.4, fontFace: 'Microsoft YaHei', fontSize: 18, color: C.gray, align: 'center', margin: 0 });
  addPage(placeholder, page);
}

// 14. 业务支撑情况目录。
const supportToc = pptx.addSlide();
addBackground(supportToc);
supportToc.addText('目  录', { x: 0.22, y: 0.14, w: 2.2, h: 0.4, fontFace: 'Microsoft YaHei', fontSize: 28, bold: true, color: C.white, margin: 0 });
[
  ['01', '业务发展情况', 'BDBDBD'], ['02', '专线自动情况', 'BDBDBD'],
  ['03', '终端回收情况', 'BDBDBD'], ['04', '业务支撑情况', '438FD8'],
].forEach((item, index) => {
  const y = 1.9 + index * 0.9;
  supportToc.addText(item[0], { x: 3.45, y: y + 0.1, w: 0.5, h: 0.34, fontFace: 'Microsoft YaHei', fontSize: 20, bold: true, color: item[2], margin: 0, align: 'right' });
  supportToc.addShape(pptx.ShapeType.parallelogram, { x: 4.16, y, w: 4.95, h: 0.55, fill: { color: item[2] }, line: { color: item[2] } });
  supportToc.addText(item[1], { x: 4.42, y: y + 0.1, w: 4.25, h: 0.34, fontFace: 'Microsoft YaHei', fontSize: 22, bold: true, color: C.white, align: 'center', margin: 0 });
});
supportToc.addText(`${D.city} · ${D.displayMonthFull}`, { x: 4.1, y: 5.9, w: 5.2, h: 0.3, fontFace: 'Microsoft YaHei', fontSize: 14, color: C.deepBlue, align: 'center', margin: 0 });
addPage(supportToc, 14);

// 15. 集团撤退单：省级页面三段框架，横轴改为标准区县。
const W = D.withdrawal;
const supportSlide = pptx.addSlide(); addBackground(supportSlide);
addAutoHeader(supportSlide, '业务情况-集团撤退单');
const supportText = { x: 0.36, w: 12.55, fontFace: 'Microsoft YaHei', fontSize: 11.5, color: '0B336F', margin: 0 };
const share = (count, total) => total ? pct(count / total) : '0.00%';
function reasonText(reasons, total, labels) {
  return labels.map(([key, label]) => `${label}${fmt(reasons[key] || 0)}单（${share(reasons[key] || 0, total)}）`).join('，');
}
function orderByRate(rates, descending = true) {
  return W.counties.map((_, index) => index).sort((a, b) =>
    (rates[a] - rates[b]) * (descending ? -1 : 1) || a - b);
}
function supportCombo(title, bars, rates, y, descending = true) {
  const order = orderByRate(rates, descending);
  const labels = order.map(i => W.counties[i]);
  const barData = bars.map(bar => ({ name: bar.name, labels, values: order.map(i => bar.values[i]) }));
  const rateData = order.map(i => rates[i]);
  addPanel(supportSlide, .36, y, 12.55, 1.28);
  supportSlide.addChart([
    { type: pptx.ChartType.bar, data: barData, options: { showValue: true, dataLabelPosition: 'outEnd', dataLabelFontSize: 8, dataLabelFormatCode: '0', gapWidthPct: 65 } },
    { type: pptx.ChartType.line, data: [{ name: '撤退单率', labels, values: rateData }], options: { secondaryValAxis: true, secondaryCatAxis: true, showValue: true, dataLabelPosition: 'above', dataLabelFontSize: 8, dataLabelColor: '2EA8CB', dataLabelFormatCode: '0.00%', lineSize: 1, showMarker: true, markerSize: 4 } },
  ], { x: .36, y, w: 12.55, h: 1.28,
    catAxisLabelFontFace: 'Microsoft YaHei', catAxisLabelFontSize: W.counties.length > 12 ? 6 : 8,
    catAxisLabelColor: C.ink, catAxisLineColor: C.lightGray,
    catAxes: [{}, { catAxisLabelPos: 'none', catAxisLineColor: C.white }],
    valAxes: [
      { valAxisMinVal: 0, valAxisMaxVal: Math.max(1, ...barData.flatMap(b => b.values)) * 1.6, valAxisLabelPos: 'none', valAxisLineShow: false, valAxisMajorTickMark: 'none', valAxisMinorTickMark: 'none', valAxisLabelColor: C.white, valAxisLineColor: C.white, valGridLine: { color: C.white, transparency: 100 } },
      { valAxisMinVal: 0, valAxisMaxVal: Math.max(.01, ...rateData) * 1.6, valAxisLabelPos: 'none', valAxisLineShow: false, valAxisMajorTickMark: 'none', valAxisMinorTickMark: 'none', valAxisLabelColor: C.white, valAxisLineColor: C.white, valGridLine: { color: C.white, transparency: 100 } },
    ],
    showLegend: true, legendPos: 't', legendFontFace: 'Microsoft YaHei', legendFontSize: 8,
    showTitle: true, title, titleFontFace: 'Microsoft YaHei', titleFontSize: 10, titleBold: true,
    chartColors: bars.length === 2 ? ['C0504D', '9BBB59', '43B0CD'] : ['4F81BD', 'C0504D', '9BBB59', '43B0CD'],
  });
}
const L = W.line, Q = W.qikuan;
const previousMonth = Number(D.currentMonth.slice(5)) - 1 || 12;
const lineReasonTotal = Object.values(L.reasons).reduce((a, b) => a + b, 0);
supportSlide.addText(`${D.displayMonth}${D.city}专线开通单竣工量${fmt(L.completed)}单（其中${D.displayMonth}受理的竣工量${fmt(L.current)}单，${previousMonth}月之前受理的竣工量${fmt(L.previous)}单），撤退单${fmt(L.count)}单，撤退率${pct(L.rate)}。主要原因有${reasonText(L.reasons, lineReasonTotal, [['network','网络建设原因'],['customer','用户原因'],['frontDesk','前台原因'],['other','其他原因']])}。`,
  { ...supportText, y: .77, h: .53, valign: 'top', fit: 'shrink' });
supportCombo('专线开通报结撤退率情况', [
  { name: '网络建设原因', values: L.reasonSeries.network },
  { name: '用户原因', values: L.reasonSeries.customer },
  { name: '前台原因', values: L.reasonSeries.frontDesk },
], L.rates, 1.32);
supportSlide.addText('注：专线撤退率取数据库指标；原因来自手工反馈样本，样本周期和全量撤退单范围可能不同。', { ...supportText, y: 2.64, h: .19, fontSize: 8, color: C.ink });
const qReasons = [['customer','用户原因'],['frontDesk','前台原因'],['construction','建设原因'],['other','其它原因'],['network','网络原因']];
supportSlide.addText(`${D.displayMonth}${D.city}企宽撤退单（含撤退单后重录并报结）${fmt(Q.count)}单，撤退率${pct(Q.rate)}，其中${Q.topRateCounties.join('、')}撤退率较高。根据${D.displayMonth}编排原因数据，${reasonText(Q.reasons, Q.count, qReasons)}。`,
  { ...supportText, y: 2.87, h: .48, fit: 'shrink' });
supportCombo(`${D.displayMonth}企宽撤退单率`, [
  { name: '退单量', values: Q.returnSeries }, { name: '撤单量', values: Q.cancellationSeries },
], Q.rates, 3.41);
supportSlide.addText('注：撤退率=（退单完成+撤单完成）/提供文件的全部受理明细；每行计1单，按文件指定周期统计。', { ...supportText, y: 4.73, h: .19, fontSize: 8, color: C.ink });
supportSlide.addText(`${D.displayMonth}${D.city}企宽退单（不含一次性撤单）${fmt(Q.returned)}单，退单率${pct(Q.returnRate)}，其中${Q.topReturnCounties.join('、')}退单率较高。根据${D.displayMonth}编排原因数据，${reasonText(Q.returnReasons, Q.returned, qReasons)}。`,
  { ...supportText, y: 4.96, h: .48, fit: 'shrink' });
addPanel(supportSlide, .36, 5.5, 12.55, 1.27);
supportSlide.addText(`${D.displayMonth}企宽退单率（不含一次性撤单）`, { x: 3.5, y: 5.55, w: 6.2, h: .22, fontSize: 11, bold: true, align: 'center', margin: 0 });
const returnOrder = orderByRate(Q.returnRates, false);
supportSlide.addChart(pptx.ChartType.bar, [{ name: '企宽退单率', labels: returnOrder.map(i => W.counties[i]), values: returnOrder.map(i => Q.returnRates[i]) }], rateOptions(.5, 5.81, 12.2, .91, Math.max(.01, ...Q.returnRates) * 1.3, W.counties.length > 12 ? 6 : 8));
supportSlide.addText('注：退单率=退单完成/提供文件的全部受理明细；撤单完成不计入分子。', { ...supportText, y: 6.84, h: .21, fontSize: 8, color: C.ink });
addPage(supportSlide, 15);

pptx.writeFile({ fileName: outputPath });
