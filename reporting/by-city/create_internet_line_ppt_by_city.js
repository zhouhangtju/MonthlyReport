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
  slide.addText(text, { x, y: y + 0.015, w, h: 0.24, fontFace: 'Microsoft YaHei', fontSize: 12.5, bold: true, color: C.white, align: 'center', margin: 0 });
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
  { text: `。其中悦享动态IP版 ${fmt(D.keyProducts['悦享专线动态IP版'])}单（同比`, options: { bold: true, color: C.ink } },
  { text: `${direction(D.keyProductYoy['悦享专线动态IP版'])}${pct(D.keyProductYoy['悦享专线动态IP版'])}`, options: { bold: true, color: changeColor(D.keyProductYoy['悦享专线动态IP版']) } },
  { text: `），互联网专线套餐 ${fmt(D.keyProducts['互联网专线套餐'])}单，商务专线套餐（2020版） ${fmt(D.keyProducts['商务专线套餐（2020版）'])}单。`, options: { bold: true, color: C.ink } },
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
  addPill(slide, `${D.city}各区县${businessLabel}产品开通情况`, 6.95, 1.42, 4.05);
  const values = group.products.map(item => item.value);
  slide.addChart(pptx.ChartType.bar, [{ name: '订单量', labels: productLabels, values }], barOptions(0.58, 1.85, 3.8, 1.65, [SINGLE], axisMax([{ values }]), false, 7));
  slide.addChart(pptx.ChartType.bar, group.countySeries.map(item => ({ name: item.name, labels: group.counties, values: item.values })), barOptions(5.02, 1.74, 7.73, 1.82, colors, axisMax(group.countySeries), true, group.counties.length > 12 ? 6 : 7));
  addPanel(slide, 0.35, 4.16, 12.63, 2.83); addPill(slide, `${group.periodShort} ${D.city}${businessLabel}开通情况`, 4.25, 4.03, 4.85);
  slide.addChart(pptx.ChartType.bar, [{ name: `${businessLabel}合计`, labels: group.months, values: group.trend }], barOptions(0.55, 4.4, 12.2, 2.3, [SINGLE], axisMax([{ values: group.trend }]), false, 8));
  addFootnote(slide, businessLabel.replace('开通', ''), page);
  return slide;
}

addLineOverview(D.mpls, 'MPLS-VPN专线', 5, ['地区内\nMPLSVPN套餐', '省内\nMPLSVPN套餐'], ['5B9BD5', 'E75B5B']);
addLineOverview(D.transmission, '传输专线', 6, ['光纤出租', '地区内数字电路', '地区间精品电路', '地区内SPN', '地区间数字电路', '地区内精品电路'], SERIES);

pptx.writeFile({ fileName: outputPath });
