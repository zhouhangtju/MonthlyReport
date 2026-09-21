const pptxgen = require('pptxgenjs');
const fs = require('fs');
// BEGIN REPORT NARRATIVES
const narratives = (() => {
// Presentation copy follows the approved template; all values come from the data model.
function num(value) {
  return typeof value === 'number' && Number.isFinite(value) ? String(value) : '待填充';
}
function percent(value) {
  return typeof value === 'number' && Number.isFinite(value) ? `${(value * 100).toFixed(2)}%` : '待填充';
}
function topCities(cities, rates) {
  return cities.map((city, i) => ({ city, rate: rates?.[i], i }))
    .filter(x => typeof x.rate === 'number' && Number.isFinite(x.rate))
    .sort((a, b) => b.rate - a.rate || a.i - b.i).slice(0, 3).map(x => x.city).join('、') || '待填充';
}
function period(month, repeatYear) {
  const [year, m] = month.split('-').map(Number);
  const start = new Date(Date.UTC(year, m - 3, 1));
  const startText = `${String(start.getUTCFullYear()).slice(-2)}年${start.getUTCMonth() + 1}月`;
  return `${startText}至${repeatYear || start.getUTCFullYear() !== year ? String(year).slice(-2) + '年' : ''}${m}月`;
}
function withdrawal(D) {
  const w = D.withdrawal;
  const missing = new Set((D.dataAudit?.missing || []).map(x => x.ppt_field));
  const value = key => missing.has('withdrawal.' + key) ? null : w[key];
  const [year, month] = D.currentMonth.split('-').map(Number);
  const previous = month === 1 ? `${year - 1}年12月` : `${month - 1}月`;
  return `${D.displayMonth}全省专线开通单竣工量${num(value('completionCount'))}单（其中${D.displayMonth}受理的竣工量${num(value('currentAcceptedCompletion'))}单，${previous}之前受理的竣工量${num(value('previousAcceptedCompletion'))}单），撤退单${num(value('withdrawalCount'))}单，撤退率${percent(value('withdrawalRate'))}。主要原因有网络建设原因${num(value('networkCount'))}单（${percent(value('networkShare'))}），用户原因${num(value('customerCount'))}单（${percent(value('customerShare'))}），前台原因${num(value('frontDeskCount'))}单（${percent(value('frontDeskShare'))}），其他原因${num(value('otherCount'))}单（${percent(value('otherShare'))}）。`;
}
function qikuan(D, data, isReturn) {
  const label = isReturn ? '企宽退单（不含一次性撤单）' : '企宽撤退单(含撤退单后重录并报结)';
  const rateLabel = isReturn ? '退单率' : '撤退率';
  const reasons = data?.reasons || {};
  const names = {customer: '用户原因', frontDesk: '前台原因', construction: '建设原因', other: '其它原因', network: '网络原因'};
  const detail = Object.entries(names).map(([key, name]) => `${name}${num(reasons[key]?.count)}单占比${percent(reasons[key]?.share)}`).join('，');
  return `${D.displayMonth}${label}${num(data?.withdrawalTotal)}单，${rateLabel}${percent(data?.overallRate)}，其中${topCities(data?.cities || [], data?.rates)}${rateLabel}较高。根据${D.displayMonth}编排原因数据，${detail}。`;
}
function repeat(D) {
  const r = D.complaintFault.repeat;
  const weightedHighNames = (r.weightedHighNames || []).join('、') || '待填充';
  return `${period(D.currentMonth, true)}，三个月内商客业务整体重复投诉率${percent(r.totalAverage)}，其中专线重复投诉率${percent(r.lineAverage)}，${topCities(r.cities, r.lineRates)}较高；千里眼重复投诉率${percent(r.broadbandAverage)}，${topCities(r.cities, r.broadbandRates)}较高；企宽重复投诉率${percent(r.qikuanAverage)}，${topCities(r.cities, r.qikuanRates)}较高；合计重复投诉率${percent(r.weightedTotalAverage)}，${weightedHighNames}较高。`;
}
function fault(D) {
  const f = D.complaintFault.fault;
  return `${period(D.currentMonth, false)}，三个月内商客业务整体新装报障率${percent(f.totalAverage)}，其中专线类新装报障率${percent(f.lineAverage)}，企宽新装报障率${percent(f.broadbandAverage)}。新装报障率较高地市为${topCities(f.cities, f.totalRates)}。`;
}
function network(D) {
  const reasons = D.internetAuto.manualReasons;
  const r = reasons?.province || {};
  const allConstruction = (reasons?.cities || []).filter(city => {
    const row = reasons.byCity?.[city];
    return row && row['非自动工单数'] > 0 && row['工程施工工单数'] === row['非自动工单数'];
  });
  return {
    title: '组网环节：',
    summary: `主要非自动原因：工程施工（占比${percent(r['工程施工占比'])}）、非自动原因为空（占比${percent(r['空原因占比'])}）`,
    cities: allConstruction.join('、'),
    suffix: allConstruction.length ? '非自动原因为工程施工（占比100%）' : '暂无地市的工程施工原因占比达到100%',
  };
}
return {num, percent, topCities, period, withdrawal, qikuan, repeat, fault, network};

})();
// END REPORT NARRATIVES
const path = require('path');

const dataFile = process.argv[2] || 'output/internet_line_ppt_data.json';
const outputFile = process.argv[3] || 'output/互联网专线产品开通情况_2026年7月.pptx';
const D = JSON.parse(fs.readFileSync(dataFile, 'utf8'));
const templateBackgroundPath = 'templates/template_background_image1.jpeg';
const useTemplateMaster = process.env.PPT_TEMPLATE_MASTER === '1';
fs.mkdirSync(path.dirname(outputFile), { recursive: true });

const pptx = new pptxgen();
pptx.layout = 'LAYOUT_WIDE';
pptx.author = 'Codex';
pptx.subject = `${D.displayMonthFull}互联网专线产品开通情况`;
pptx.title = '业务发展量-专线产品开通情况';
pptx.company = '中国移动';
pptx.lang = 'zh-CN';
pptx.theme = {
  headFontFace: 'Microsoft YaHei',
  bodyFontFace: 'Microsoft YaHei',
  lang: 'zh-CN',
};

const C = {
  blue: '0086D1',
  deepBlue: '006DB8',
  cyan: '11B6D8',
  green: '00B050',
  lime: '75C900',
  red: 'F04444',
  orange: 'F28E2B',
  purple: '9B7BC4',
  navy: '1F3A5F',
  ink: '252525',
  gray: '6B7280',
  lightGray: 'D9DEE5',
  panel: 'F9FBFD',
  white: 'FFFFFF',
};

// 与第3页单指标月度柱状图保持一致的统一主题蓝。
const SINGLE_METRIC_BLUE = '3D85C6';

const provinceNames = D.province.map(row => row.label);
const provinceValues = D.province.map(row => row.value);

const cities = D.cities;
const citySeries = D.citySeries;

const months = D.months;
const trendSeries = D.trendSeries;
const enjoySeries = [trendSeries.find(item => item.name === '悦享专线动态IP版')];
const packageSeries = [D.packageTrend];
const otherSeries = [D.otherTrend];

function fmt(value) { return value == null ? '待补充' : Number(value).toLocaleString('en-US'); }
function ceilFmt(value) { return value == null ? '待补充' : Math.ceil(Number(value)).toLocaleString('en-US'); }
function pct(value) { return value == null ? '无数据' : `${(Number(value) * 100).toFixed(2)}%`; }

// Manual metrics use their own order-level denominators; database stage rates remain unchanged.
function manualBar(slide, title, labels, values, box, percent = true) {
  if (!values) {
    slide.addText('待补充手工数据', { ...box, fontSize: 12, color: C.gray, align: 'center', valign: 'mid' });
    return;
  }
  slide.addChart(pptx.ChartType.bar, [{ name: title, labels, values }], {
    ...box, catAxisLabelFontFace: 'Microsoft YaHei', catAxisLabelFontSize: 8,
    catAxisLabelColor: C.ink, catAxisLineColor: C.lightGray,
    valAxisMinVal: 0, valAxisMaxVal: Math.max(percent ? .01 : 1, ...values.filter(v => v != null)) * 1.3,
    valAxisLabelPos: 'none', valAxisLineShow: false, valAxisMajorTickMark: 'none', valAxisMinorTickMark: 'none', valAxisLabelColor: C.white, valAxisLineColor: C.white,
    valGridLine: { color: C.white, transparency: 100 }, showLegend: false,
    showValue: true, dataLabelPosition: 'outEnd', dataLabelColor: SINGLE_METRIC_BLUE,
    dataLabelFontSize: 8, dataLabelFormatCode: percent ? '0.00%' : '0',
    chartColors: [SINGLE_METRIC_BLUE], gapWidthPct: 90,
  });
}

function nameList(values) { return values.join('、'); }
function deviceList(values) {
  return values.map(item => `${item.name} ${fmt(item.value)} 台`).join('；');
}
function direction(value) { return Number(value) >= 0 ? '上升' : '下降'; }
function changeColor(value) { return Number(value) >= 0 ? C.green : C.red; }
function dynamicAxisMax(series) {
  const maxValue = Math.max(1, ...series.flatMap(item => item.values));
  const padded = maxValue * 1.15;
  const step = maxValue >= 5000 ? 1000
    : maxValue >= 2000 ? 500
      : maxValue >= 1000 ? 250
        : maxValue >= 500 ? 100 : 50;
  return Math.ceil(padded / step) * step;
}

const cityAxisMax = dynamicAxisMax(citySeries);
const trendAxisMax = dynamicAxisMax(enjoySeries);
const packageAxisMax = dynamicAxisMax(packageSeries);
const otherAxisMax = dynamicAxisMax(otherSeries);
const mplsCityAxisMax = dynamicAxisMax(D.mpls.citySeries);
const mplsTrendSeries = [{ name: 'MPLS-VPN专线合计', values: D.mpls.trend }];
const mplsTrendAxisMax = dynamicAxisMax(mplsTrendSeries);
const transmissionCityAxisMax = dynamicAxisMax(D.transmission.citySeries);
const transmissionTrendSeries = [{ name: '传输专线合计', values: D.transmission.trend }];
const transmissionTrendAxisMax = dynamicAxisMax(transmissionTrendSeries);

function svgDataUri(svg) {
  return `data:image/svg+xml;base64,${Buffer.from(svg).toString('base64')}`;
}

const headerGradient = svgDataUri(`
  <svg xmlns="http://www.w3.org/2000/svg" width="1600" height="100" viewBox="0 0 1600 100">
    <defs>
      <linearGradient id="headerGradient" x1="0" y1="0" x2="1" y2="0">
        <stop offset="0%" stop-color="#70C800"/>
        <stop offset="24%" stop-color="#61BD43"/>
        <stop offset="48%" stop-color="#45AE7E"/>
        <stop offset="70%" stop-color="#22A3A4"/>
        <stop offset="86%" stop-color="#0797B9"/>
        <stop offset="100%" stop-color="#0086C9"/>
      </linearGradient>
    </defs>
    <rect width="1600" height="100" fill="url(#headerGradient)"/>
  </svg>
`);

const brandedHeader = svgDataUri(`
  <svg xmlns="http://www.w3.org/2000/svg" width="1600" height="100" viewBox="0 0 1600 100">
    <defs>
      <linearGradient id="brandedHeaderGradient" x1="0" y1="0" x2="1" y2="0">
        <stop offset="0%" stop-color="#70C800"/><stop offset="24%" stop-color="#61BD43"/>
        <stop offset="48%" stop-color="#45AE7E"/><stop offset="70%" stop-color="#22A3A4"/>
        <stop offset="86%" stop-color="#0797B9"/><stop offset="100%" stop-color="#0086C9"/>
      </linearGradient>
    </defs>
    <rect width="1600" height="100" fill="url(#brandedHeaderGradient)"/>
    <text x="34" y="66" fill="#FFFFFF" font-family="Microsoft YaHei, Microsoft YaHei, sans-serif" font-size="52" font-weight="700">业务发展量-专线产品开通情况</text>
    <text x="1565" y="59" text-anchor="end" fill="#FFFFFF" font-family="Microsoft YaHei, Microsoft YaHei, sans-serif" font-size="27" font-weight="700">中国移动  China Mobile</text>
  </svg>
`);

const coverDecoration = svgDataUri(`
  <svg xmlns="http://www.w3.org/2000/svg" width="1600" height="900" viewBox="0 0 1600 900">
    <defs>
      <linearGradient id="coverRibbon" x1="0" y1="0" x2="1" y2="1">
        <stop offset="0%" stop-color="#68D5EF" stop-opacity="0.16"/>
        <stop offset="100%" stop-color="#7ACF3A" stop-opacity="0.16"/>
      </linearGradient>
      <pattern id="coverDots" width="42" height="42" patternUnits="userSpaceOnUse">
        <circle cx="13" cy="13" r="9" fill="#51CBE7" fill-opacity="0.18"/>
      </pattern>
    </defs>
    <path d="M-70 40 C75 5 220 25 340 120 C230 80 135 92 20 165 Z" fill="url(#coverRibbon)"/>
    <path d="M-45 52 C85 20 210 44 315 126" fill="none" stroke="#7FCF3E" stroke-opacity="0.18" stroke-width="22"/>
    <path d="M-40 22 C100 0 240 35 360 145 L310 205 C190 103 85 92 -30 132 Z" fill="url(#coverDots)"/>
    <g transform="translate(1265 635) rotate(-12)">
      <path d="M0 145 C95 70 205 52 365 85 L365 220 L0 220 Z" fill="url(#coverRibbon)"/>
      <path d="M35 120 C130 75 230 72 355 105" fill="none" stroke="#7FCF3E" stroke-opacity="0.16" stroke-width="20"/>
      <rect x="20" y="65" width="360" height="180" fill="url(#coverDots)"/>
    </g>
  </svg>
`);

function addSectionPill(slide, text, x, y, w) {
  slide.addShape(pptx.ShapeType.roundRect, {
    x, y, w, h: 0.28,
    rectRadius: 0.06,
    fill: { color: C.blue },
    line: { color: C.blue },
  });
  slide.addText(text, {
    x, y: y + 0.015, w, h: 0.24,
    fontFace: 'Microsoft YaHei', fontSize: 12.5, bold: true,
    color: C.white, align: 'center', margin: 0,
  });
}

function addPanel(slide, x, y, w, h) {
  slide.addShape(pptx.ShapeType.rect, {
    x, y, w, h,
    fill: { color: C.white },
    line: { color: C.lightGray, width: 0.8 },
  });
}

function addTemplateBackground(slide) {
  if (useTemplateMaster) return;
  slide.background = { color: C.white };
  slide.addImage({ path: templateBackgroundPath, x: 0, y: 0, w: 13.333, h: 7.5 });
}

// Cover page.
const cover = pptx.addSlide();
addTemplateBackground(cover);
cover.addText('集客综调月报', {
  x: 3.7, y: 2.55, w: 5.95, h: 0.78,
  fontFace: 'Microsoft YaHei', fontSize: 38, bold: true, color: C.deepBlue,
  margin: 0, align: 'center', valign: 'mid',
});
cover.addText('浙江移动客响中心', {
  x: 4.6, y: 4.85, w: 4.15, h: 0.34,
  fontFace: 'Microsoft YaHei', fontSize: 20, bold: true, color: C.deepBlue,
  margin: 0, align: 'center',
});
cover.addText(D.displayMonthFull, {
  x: 4.6, y: 5.25, w: 4.15, h: 0.36,
  fontFace: 'Microsoft YaHei', fontSize: 21, bold: true, color: C.deepBlue,
  margin: 0, align: 'center',
});
cover.addNotes(`集客综调月报封面，统计月份：${D.displayMonthFull}。`);

// Fixed table-of-contents page.
const toc = pptx.addSlide();
addTemplateBackground(toc);
toc.addText('目  录', {
  x: 0.22, y: 0.14, w: 2.2, h: 0.4,
  fontFace: 'Microsoft YaHei', fontSize: 28, bold: true, color: C.white, margin: 0,
});

const tocItems = [
  ['01', '业务发展情况', '438FD8'],
  ['02', '专线自动情况', 'BDBDBD'],
  ['03', '终端回收情况', 'BDBDBD'],
  ['04', '业务支撑情况', 'BDBDBD'],
];
tocItems.forEach((item, index) => {
  const y = 1.9 + index * 0.9;
  toc.addText(item[0], {
    x: 3.45, y: y + 0.1, w: 0.5, h: 0.34,
    fontFace: 'Microsoft YaHei', fontSize: 20, bold: true, color: item[2],
    margin: 0, align: 'right', valign: 'mid',
  });
  toc.addShape(pptx.ShapeType.parallelogram, {
    x: 4.16, y: y, w: 4.95, h: 0.55,
    fill: { color: item[2] }, line: { color: item[2] },
  });
  toc.addText(item[1], {
    x: 4.42, y: y + 0.1, w: 4.25, h: 0.34,
    fontFace: 'Microsoft YaHei', fontSize: 22, bold: true,
    color: C.white, align: 'center', margin: 0,
  });
});
toc.addText('2', {
  x: 12.65, y: 7.18, w: 0.28, h: 0.18,
  fontFace: 'Microsoft YaHei', fontSize: 8, color: C.lime, align: 'right', margin: 0,
});
toc.addNotes('固定目录页：业务发展情况、专线自动情况、终端回收情况、业务支撑情况。');

const slide = pptx.addSlide();
addTemplateBackground(slide);
slide.addText('业务发展量-专线产品开通情况', {
  x: 0.28, y: 0.14, w: 7.4, h: 0.4,
  fontFace: 'Microsoft YaHei', fontSize: 27, bold: true, color: C.white, margin: 0,
});

// Headline narrative.
slide.addText([
  { text: `${D.displayMonth}互联网专线已完成 `, options: { bold: true, color: C.ink } },
  { text: `${fmt(D.currentTotal)}单`, options: { bold: true, color: C.deepBlue } },
  { text: '，同比 ', options: { bold: true, color: C.ink } },
  { text: `${direction(D.yoy)}${pct(D.yoy)}`, options: { bold: true, color: changeColor(D.yoy) } },
  { text: '，环比 ', options: { bold: true, color: C.ink } },
  { text: `${direction(D.mom)}${pct(D.mom)}`, options: { bold: true, color: changeColor(D.mom) } },
  { text: '。其中悦享动态IP版 ', options: { bold: true, color: C.ink } },
  { text: `${fmt(D.keyProducts['悦享专线动态IP版'])}单`, options: { bold: true, color: C.deepBlue } },
  { text: `（同比${direction(D.keyProductYoy['悦享专线动态IP版'])}`, options: { bold: true, color: C.ink } },
  { text: `${pct(D.keyProductYoy['悦享专线动态IP版'])}`, options: { bold: true, color: changeColor(D.keyProductYoy['悦享专线动态IP版']) } },
  { text: '）', options: { bold: true, color: C.ink } },
  { text: '，互联网专线套餐 ', options: { bold: true, color: C.ink } },
  { text: `${fmt(D.keyProducts['互联网专线套餐'])}单`, options: { bold: true, color: C.deepBlue } },
  { text: `（同比${direction(D.keyProductYoy['互联网专线套餐'])}`, options: { bold: true, color: C.ink } },
  { text: `${pct(D.keyProductYoy['互联网专线套餐'])}`, options: { bold: true, color: changeColor(D.keyProductYoy['互联网专线套餐']) } },
  { text: '）', options: { bold: true, color: C.ink } },
  { text: '，商务专线套餐（2020版） ', options: { bold: true, color: C.ink } },
  { text: `${fmt(D.keyProducts['商务专线套餐（2020版）'])}单`, options: { bold: true, color: C.deepBlue } },
  { text: `（同比${direction(D.keyProductYoy['商务专线套餐（2020版）'])}`, options: { bold: true, color: C.ink } },
  { text: `${pct(D.keyProductYoy['商务专线套餐（2020版）'])}`, options: { bold: true, color: changeColor(D.keyProductYoy['商务专线套餐（2020版）']) } },
  { text: '）', options: { bold: true, color: C.ink } },
  { text: '。', options: { bold: true, color: C.ink } },
], {
  x: 0.35, y: 0.77, w: 12.6, h: 0.7,
  fontFace: 'Microsoft YaHei', fontSize: 14.5, breakLine: false,
  margin: 0, valign: 'mid', fit: 'shrink',
});

// Mid panels.
addPanel(slide, 0.35, 1.63, 5.35, 2.22);
addPanel(slide, 5.83, 1.63, 7.15, 2.22);
addSectionPill(slide, '全省互联网专线产品开通情况', 1.65, 1.50, 2.75);
addSectionPill(slide, '各地市互联网专线产品开通情况', 8.05, 1.50, 3.05);

slide.addChart(pptx.ChartType.bar, [{ name: '订单量', labels: provinceNames, values: provinceValues }], {
  x: 0.36, y: 1.82, w: 5.12, h: 1.96,
  catAxisLabelFontFace: 'Microsoft YaHei', catAxisLabelFontSize: 8,
  catAxisLabelRotate: 0,
  catAxisLabelColor: C.ink, catAxisLineColor: C.lightGray,
  valAxisLabelPos: 'none', valAxisLineShow: false, valAxisMajorTickMark: 'none', valAxisMinorTickMark: 'none', valAxisLabelColor: C.gray, valAxisLabelFontSize: 8, valAxisLineColor: C.lightGray,
  valGridLine: { color: C.white, transparency: 100 },
  showLegend: false, showTitle: false,
  showValue: true, dataLabelPosition: 'outEnd', dataLabelColor: C.ink,
  dataLabelFontFace: 'Microsoft YaHei', dataLabelFontSize: 8, dataLabelFormatCode: '0',
  chartColors: [SINGLE_METRIC_BLUE],
  showCatName: false,
  showValue: true,
  gapWidthPct: 85,
  border: { color: C.white, transparency: 100 },
});

slide.addChart(pptx.ChartType.bar, citySeries.map(s => ({ name: s.name, labels: cities, values: s.values })), {
  x: 5.94, y: 1.74, w: 6.96, h: 2.06,
  catAxisLabelFontFace: 'Microsoft YaHei', catAxisLabelFontSize: 8,
  catAxisLabelColor: C.ink, catAxisLineColor: C.lightGray,
  valAxisMinVal: 0, valAxisMaxVal: cityAxisMax,
  valAxisLabelPos: 'none', valAxisLineShow: false, valAxisMajorTickMark: 'none', valAxisMinorTickMark: 'none', valAxisLabelColor: C.gray, valAxisLabelFontSize: 8, valAxisLineColor: C.lightGray,
  valGridLine: { color: C.white, transparency: 100 },
  showLegend: true, legendPos: 't', legendFontFace: 'Microsoft YaHei', legendFontSize: 8,
  showTitle: false, showValue: true,
  dataLabelPosition: 'outEnd', dataLabelColor: C.ink,
  dataLabelFontFace: 'Microsoft YaHei', dataLabelFormatCode: '0', dataLabelFontSize: 6,
  chartColors: ['11B6D8', 'E75B5B', '86C85B', '9B7BC4', 'F28E2B', '3572B0'],
  gapWidthPct: 45, overlap: 0,
  border: { color: C.white, transparency: 100 },
});

// Trend narrative and chart.
slide.addText([
  { text: `${D.trendPeriodText}，悦享专线动态IP版累计 `, options: { bold: true, color: C.ink } },
  { text: `${fmt(D.trendSummary['悦享专线动态IP版'].sum)}单`, options: { bold: true, color: C.deepBlue } },
  { text: '，月均 ', options: { bold: true, color: C.ink } },
  { text: `${ceilFmt(D.trendSummary['悦享专线动态IP版'].average)}单`, options: { bold: true, color: C.deepBlue } },
  { text: '；互联网专线套餐累计开通 ', options: { bold: true, color: C.ink } },
  { text: `${fmt(D.trendSummary['互联网专线套餐'].sum)}单`, options: { bold: true, color: C.deepBlue } },
  { text: '，平均月开通 ', options: { bold: true, color: C.ink } },
  { text: `${ceilFmt(D.trendSummary['互联网专线套餐'].average)}单`, options: { bold: true, color: C.deepBlue } },
  { text: '；其他产品累计开通 ', options: { bold: true, color: C.ink } },
  { text: `${fmt(D.otherTrendSummary.sum)}单`, options: { bold: true, color: C.deepBlue } },
  { text: '，平均月开通 ', options: { bold: true, color: C.ink } },
  { text: `${ceilFmt(D.otherTrendSummary.average)}单`, options: { bold: true, color: C.deepBlue } },
  { text: '。', options: { bold: true, color: C.ink } },
], {
  x: 0.38, y: 3.98, w: 12.5, h: 0.56,
  fontFace: 'Microsoft YaHei', fontSize: 14, margin: 0, valign: 'mid', fit: 'shrink',
});

addPanel(slide, 0.35, 4.81, 12.63, 2.20);
addSectionPill(slide, `${D.trendPeriodShort} 悦享专线动态IP版开通情况`, 4.75, 4.68, 3.9);
slide.addChart(pptx.ChartType.bar, enjoySeries.map(s => ({ name: s.name, labels: months, values: s.values })), {
  x: 0.55, y: 4.91, w: 12.2, h: 1.92,
  catAxisLabelFontFace: 'Microsoft YaHei', catAxisLabelFontSize: 8,
  catAxisLabelColor: C.gray, catAxisLineColor: C.lightGray,
  valAxisMinVal: 0, valAxisMaxVal: trendAxisMax,
  valAxisLabelPos: 'none', valAxisLineShow: false, valAxisMajorTickMark: 'none', valAxisMinorTickMark: 'none', valAxisLabelColor: C.gray, valAxisLabelFontSize: 8, valAxisLineColor: C.lightGray,
  valGridLine: { color: C.white, transparency: 100 },
  showLegend: false,
  showTitle: false, showValue: true, dataLabelPosition: 'outEnd',
  dataLabelColor: C.ink, dataLabelFontFace: 'Microsoft YaHei', dataLabelFormatCode: '0', dataLabelFontSize: 8,
  chartColors: [SINGLE_METRIC_BLUE],
  gapWidthPct: 55, overlap: 0,
  border: { color: C.white, transparency: 100 },
});

slide.addText(`口径：订单创建时间；订单状态=已完成；业务类型=互联网专线；按订单号去重。数据源：${D.sourceFileName}`, {
  x: 0.38, y: 7.21, w: 11.9, h: 0.16,
  fontFace: 'Microsoft YaHei', fontSize: 7.5, color: C.gray, margin: 0,
});
slide.addText('3', { x: 12.65, y: 7.18, w: 0.28, h: 0.18, fontFace: 'Microsoft YaHei', fontSize: 8, color: C.gray, align: 'right', margin: 0 });

slide.addNotes(`本页数据来自${D.sourceFileName}。同比为当月对比上年同月；环比为当月对比上月。`);

// Page 2: Internet package and other-product 12-month trends.
const slide2 = pptx.addSlide();
addTemplateBackground(slide2);
slide2.addText('业务发展量-专线产品开通情况', {
  x: 0.28, y: 0.14, w: 7.4, h: 0.4,
  fontFace: 'Microsoft YaHei', fontSize: 27, bold: true, color: C.white, margin: 0,
});

addPanel(slide2, 0.35, 0.98, 12.63, 2.83);
addSectionPill(slide2, `${D.trendPeriodShort} 互联网专线套餐开通情况`, 4.75, 0.85, 3.9);
slide2.addChart(pptx.ChartType.bar, packageSeries.map(s => ({ name: s.name, labels: months, values: s.values })), {
  x: 0.55, y: 1.2, w: 12.2, h: 2.3,
  catAxisLabelFontFace: 'Microsoft YaHei', catAxisLabelFontSize: 8,
  catAxisLabelColor: C.gray, catAxisLineColor: C.lightGray,
  valAxisMinVal: 0, valAxisMaxVal: packageAxisMax,
  valAxisLabelPos: 'none', valAxisLineShow: false, valAxisMajorTickMark: 'none', valAxisMinorTickMark: 'none', valAxisLabelColor: C.gray, valAxisLabelFontSize: 8, valAxisLineColor: C.lightGray,
  valGridLine: { color: C.white, transparency: 100 },
  showLegend: false, showTitle: false,
  showValue: true, dataLabelPosition: 'outEnd', dataLabelColor: C.ink,
  dataLabelFontFace: 'Microsoft YaHei', dataLabelFormatCode: '0', dataLabelFontSize: 8,
  chartColors: [SINGLE_METRIC_BLUE], gapWidthPct: 95,
  border: { color: C.white, transparency: 100 },
});

addPanel(slide2, 0.35, 4.16, 12.63, 2.83);
addSectionPill(slide2, `${D.trendPeriodShort} 互联网专线其他产品开通情况`, 4.75, 4.03, 3.9);
slide2.addChart(pptx.ChartType.bar, otherSeries.map(s => ({ name: s.name, labels: months, values: s.values })), {
  x: 0.55, y: 4.38, w: 12.2, h: 2.3,
  catAxisLabelFontFace: 'Microsoft YaHei', catAxisLabelFontSize: 8,
  catAxisLabelColor: C.gray, catAxisLineColor: C.lightGray,
  valAxisMinVal: 0, valAxisMaxVal: otherAxisMax,
  valAxisLabelPos: 'none', valAxisLineShow: false, valAxisMajorTickMark: 'none', valAxisMinorTickMark: 'none', valAxisLabelColor: C.gray, valAxisLabelFontSize: 8, valAxisLineColor: C.lightGray,
  valGridLine: { color: C.white, transparency: 100 },
  showLegend: false, showTitle: false,
  showValue: true, dataLabelPosition: 'outEnd', dataLabelColor: C.ink,
  dataLabelFontFace: 'Microsoft YaHei', dataLabelFormatCode: '0', dataLabelFontSize: 8,
  chartColors: [SINGLE_METRIC_BLUE], gapWidthPct: 95,
  border: { color: C.white, transparency: 100 },
});

slide2.addText('口径：订单创建时间；订单状态=已完成；业务类型=互联网专线；订单类型=开通；按订单号去重。', {
  x: 0.38, y: 7.21, w: 11.9, h: 0.16,
  fontFace: 'Microsoft YaHei', fontSize: 7.5, color: C.gray, margin: 0,
});
slide2.addText('4', { x: 12.65, y: 7.18, w: 0.28, h: 0.18, fontFace: 'Microsoft YaHei', fontSize: 8, color: C.gray, align: 'right', margin: 0 });
slide2.addNotes('上图为互联网专线套餐近12个月开通情况；下图为商务专线套餐（2020版）、直播专线、网吧专线套餐（2019版）和高品质互联网专线合计。');

// Page 3: MPLS-VPN overview, city distribution, and monthly trend.
const slide3 = pptx.addSlide();
addTemplateBackground(slide3);
slide3.addText('业务发展量-专线产品开通情况', {
  x: 0.28, y: 0.14, w: 7.4, h: 0.4,
  fontFace: 'Microsoft YaHei', fontSize: 27, bold: true, color: C.white, margin: 0,
});

const mplsDistrict = D.mpls.products.find(item => item.name === '地区内MPLSVPN套餐');
const mplsProvince = D.mpls.products.find(item => item.name === '省内MPLSVPN套餐');
slide3.addText([
  { text: `${D.displayMonth}MPLS-VPN专线开通 `, options: { bold: true, color: C.ink } },
  { text: `${fmt(D.mpls.currentTotal)}单`, options: { bold: true, color: C.deepBlue } },
  { text: '，同比 ', options: { bold: true, color: C.ink } },
  { text: `${direction(D.mpls.totalYoy)}${pct(D.mpls.totalYoy)}`, options: { bold: true, color: changeColor(D.mpls.totalYoy) } },
  { text: '。其中地区内MPLS-VPN套餐 ', options: { bold: true, color: C.ink } },
  { text: `${fmt(mplsDistrict.value)}单`, options: { bold: true, color: C.deepBlue } },
  { text: '（同比 ', options: { bold: true, color: C.ink } },
  { text: `${direction(mplsDistrict.yoy)}${pct(mplsDistrict.yoy)}`, options: { bold: true, color: changeColor(mplsDistrict.yoy) } },
  { text: '），省内MPLS-VPN套餐 ', options: { bold: true, color: C.ink } },
  { text: `${fmt(mplsProvince.value)}单`, options: { bold: true, color: C.deepBlue } },
  { text: `（同比新增${fmt(mplsProvince.increase)}单）。`, options: { bold: true, color: C.green } },
], {
  x: 0.35, y: 0.82, w: 12.6, h: 0.55,
  fontFace: 'Microsoft YaHei', fontSize: 15.5, margin: 0, valign: 'mid', fit: 'shrink',
});

addPanel(slide3, 0.35, 1.55, 4.25, 2.2);
addPanel(slide3, 4.72, 1.55, 8.26, 2.2);
addSectionPill(slide3, '全省MPLS-VPN专线产品开通情况', 1.02, 1.42, 2.9);
addSectionPill(slide3, '各地市MPLS-VPN专线产品开通情况', 7.35, 1.42, 3.1);

slide3.addChart(pptx.ChartType.bar, [{
  name: '订单量',
  labels: ['地区内\nMPLSVPN套餐', '省内\nMPLSVPN套餐'],
  values: [mplsDistrict.value, mplsProvince.value],
}], {
  x: 0.58, y: 1.85, w: 3.8, h: 1.65,
  catAxisLabelFontFace: 'Microsoft YaHei', catAxisLabelFontSize: 8,
  catAxisLabelColor: C.ink, catAxisLineColor: C.lightGray,
  valAxisLabelPos: 'none', valAxisLineShow: false, valAxisMajorTickMark: 'none', valAxisMinorTickMark: 'none', valAxisLabelColor: C.gray, valAxisLabelFontSize: 8, valAxisLineColor: C.lightGray,
  valGridLine: { color: C.white, transparency: 100 },
  showLegend: false, showTitle: false, showValue: true,
  dataLabelPosition: 'outEnd', dataLabelColor: C.ink,
  dataLabelFontFace: 'Microsoft YaHei', dataLabelFormatCode: '0', dataLabelFontSize: 8,
  chartColors: [SINGLE_METRIC_BLUE], gapWidthPct: 120,
  border: { color: C.white, transparency: 100 },
});

slide3.addChart(pptx.ChartType.bar, D.mpls.citySeries.map(s => ({ name: s.name, labels: D.mpls.cities, values: s.values })), {
  x: 5.02, y: 1.74, w: 7.73, h: 1.82,
  catAxisLabelFontFace: 'Microsoft YaHei', catAxisLabelFontSize: 8,
  catAxisLabelColor: C.ink, catAxisLineColor: C.lightGray,
  valAxisMinVal: 0, valAxisMaxVal: mplsCityAxisMax,
  valAxisLabelPos: 'none', valAxisLineShow: false, valAxisMajorTickMark: 'none', valAxisMinorTickMark: 'none', valAxisLabelColor: C.gray, valAxisLabelFontSize: 8, valAxisLineColor: C.lightGray,
  valGridLine: { color: C.white, transparency: 100 },
  showLegend: true, legendPos: 't', legendFontFace: 'Microsoft YaHei', legendFontSize: 8,
  showTitle: false, showValue: true, dataLabelPosition: 'outEnd',
  dataLabelColor: C.ink, dataLabelFontFace: 'Microsoft YaHei', dataLabelFormatCode: '0', dataLabelFontSize: 8,
  chartColors: ['5B9BD5', 'E75B5B'], gapWidthPct: 60,
  border: { color: C.white, transparency: 100 },
});

addPanel(slide3, 0.35, 4.16, 12.63, 2.83);
addSectionPill(slide3, `${D.mpls.periodShort} MPLS-VPN专线开通情况`, 4.75, 4.03, 3.9);
slide3.addChart(pptx.ChartType.bar, [{ name: 'MPLS-VPN专线合计', labels: D.mpls.months, values: D.mpls.trend }], {
  x: 0.55, y: 4.4, w: 12.2, h: 2.3,
  catAxisLabelFontFace: 'Microsoft YaHei', catAxisLabelFontSize: 8,
  catAxisLabelColor: C.gray, catAxisLineColor: C.lightGray,
  valAxisMinVal: 0, valAxisMaxVal: mplsTrendAxisMax,
  valAxisLabelPos: 'none', valAxisLineShow: false, valAxisMajorTickMark: 'none', valAxisMinorTickMark: 'none', valAxisLabelColor: C.gray, valAxisLabelFontSize: 8, valAxisLineColor: C.lightGray,
  valGridLine: { color: C.white, transparency: 100 },
  showLegend: false, showTitle: false, showValue: true,
  dataLabelPosition: 'outEnd', dataLabelColor: C.ink,
  dataLabelFontFace: 'Microsoft YaHei', dataLabelFormatCode: '0', dataLabelFontSize: 8,
  chartColors: [SINGLE_METRIC_BLUE], gapWidthPct: 95,
  border: { color: C.white, transparency: 100 },
});

slide3.addText('口径：订单创建时间；订单状态=已完成；业务类型=MPLS-VPN专线；订单类型=开通；按订单号去重。', {
  x: 0.38, y: 7.21, w: 11.9, h: 0.16,
  fontFace: 'Microsoft YaHei', fontSize: 7.5, color: C.gray, margin: 0,
});
slide3.addText('5', { x: 12.65, y: 7.18, w: 0.28, h: 0.18, fontFace: 'Microsoft YaHei', fontSize: 8, color: C.gray, align: 'right', margin: 0 });
slide3.addNotes('本页数据来自MPLS-VPN指标汇总、动态月份地市表和MPLS-VPN月度分布。省内套餐上年同期为0，因此使用同比新增量表述。');

// Page 4: Transmission-line overview, city distribution, and monthly trend.
const slide4 = pptx.addSlide();
addTemplateBackground(slide4);
slide4.addText('业务发展量-专线产品开通情况', {
  x: 0.28, y: 0.14, w: 7.4, h: 0.4,
  fontFace: 'Microsoft YaHei', fontSize: 27, bold: true, color: C.white, margin: 0,
});

const transmissionFiber = D.transmission.products.find(item => item.name === '光纤出租套餐');
const transmissionDigital = D.transmission.products.find(item => item.name === '地区内数字电路出租套餐');
const transmissionSpn = D.transmission.products.find(item => item.name === '地区内SPN电路出租');
slide4.addText([
  { text: `${D.displayMonth}传输专线开通 `, options: { bold: true, color: C.ink } },
  { text: `${fmt(D.transmission.currentTotal)}单`, options: { bold: true, color: C.deepBlue } },
  { text: '，同比 ', options: { bold: true, color: C.ink } },
  { text: `${direction(D.transmission.totalYoy)}${pct(D.transmission.totalYoy)}`, options: { bold: true, color: changeColor(D.transmission.totalYoy) } },
  { text: '。其中光纤出租套餐 ', options: { bold: true, color: C.ink } },
  { text: `${fmt(transmissionFiber.value)}单`, options: { bold: true, color: C.deepBlue } },
  { text: '（同比 ', options: { bold: true, color: C.ink } },
  { text: `${direction(transmissionFiber.yoy)}${pct(transmissionFiber.yoy)}`, options: { bold: true, color: changeColor(transmissionFiber.yoy) } },
  { text: '），地区内数字电路出租套餐 ', options: { bold: true, color: C.ink } },
  { text: `${fmt(transmissionDigital.value)}单`, options: { bold: true, color: C.deepBlue } },
  { text: '（同比 ', options: { bold: true, color: C.ink } },
  { text: `${direction(transmissionDigital.yoy)}${pct(transmissionDigital.yoy)}`, options: { bold: true, color: changeColor(transmissionDigital.yoy) } },
  { text: '），地区内SPN电路出租 ', options: { bold: true, color: C.ink } },
  { text: `${fmt(transmissionSpn.value)}单`, options: { bold: true, color: C.deepBlue } },
  { text: '（同比 ', options: { bold: true, color: C.ink } },
  { text: `${direction(transmissionSpn.yoy)}${pct(transmissionSpn.yoy)}`, options: { bold: true, color: changeColor(transmissionSpn.yoy) } },
  { text: '）。', options: { bold: true, color: C.ink } },
], {
  x: 0.35, y: 0.79, w: 12.6, h: 0.65,
  fontFace: 'Microsoft YaHei', fontSize: 14.5, margin: 0, valign: 'mid', fit: 'shrink',
});

addPanel(slide4, 0.35, 1.91, 4.7, 2.2);
addPanel(slide4, 5.17, 1.91, 7.81, 2.2);
addSectionPill(slide4, '全省传输专线产品开通情况', 1.3, 1.78, 2.8);
addSectionPill(slide4, '各地市传输专线产品开通情况', 7.55, 1.78, 3.0);

slide4.addChart(pptx.ChartType.bar, [{
  name: '订单量',
  labels: D.transmission.products.map(item => item.name
    .replace('光纤出租套餐', '光纤出租\n套餐')
    .replace('地区内数字电路出租套餐', '地区内数字\n电路出租')
    .replace('地区间精品电路', '地区间\n精品电路')
    .replace('地区内SPN电路出租', '地区内SPN\n电路出租')
    .replace('地区间数字电路出租套餐', '地区间数字\n电路出租')
    .replace('地区内精品电路', '地区内\n精品电路')),
  values: D.transmission.products.map(item => item.value),
}], {
  x: 0.46, y: 2.10, w: 4.45, h: 1.96,
  catAxisLabelFontFace: 'Microsoft YaHei', catAxisLabelFontSize: 8,
  catAxisLabelRotate: 0,
  catAxisLabelColor: C.ink, catAxisLineColor: C.lightGray,
  valAxisLabelPos: 'none', valAxisLineShow: false, valAxisMajorTickMark: 'none', valAxisMinorTickMark: 'none', valAxisLabelColor: C.gray, valAxisLabelFontSize: 8, valAxisLineColor: C.lightGray,
  valGridLine: { color: C.white, transparency: 100 },
  showLegend: false, showTitle: false, showValue: true,
  dataLabelPosition: 'outEnd', dataLabelColor: C.ink,
  dataLabelFontFace: 'Microsoft YaHei', dataLabelFormatCode: '0', dataLabelFontSize: 8,
  chartColors: [SINGLE_METRIC_BLUE], gapWidthPct: 65,
  border: { color: C.white, transparency: 100 },
});

slide4.addChart(pptx.ChartType.bar, D.transmission.citySeries.map(s => ({ name: s.name, labels: D.transmission.cities, values: s.values })), {
  x: 5.30, y: 2.06, w: 7.58, h: 2.06,
  catAxisLabelFontFace: 'Microsoft YaHei', catAxisLabelFontSize: 8,
  catAxisLabelColor: C.ink, catAxisLineColor: C.lightGray,
  valAxisMinVal: 0, valAxisMaxVal: transmissionCityAxisMax,
  valAxisLabelPos: 'none', valAxisLineShow: false, valAxisMajorTickMark: 'none', valAxisMinorTickMark: 'none', valAxisLabelColor: C.gray, valAxisLabelFontSize: 8, valAxisLineColor: C.lightGray,
  valGridLine: { color: C.white, transparency: 100 },
  showLegend: true, legendPos: 't', legendFontFace: 'Microsoft YaHei', legendFontSize: 8,
  showTitle: false, showValue: true,
  dataLabelPosition: 'outEnd', dataLabelColor: C.ink,
  dataLabelFontFace: 'Microsoft YaHei', dataLabelFormatCode: '0', dataLabelFontSize: 6,
  chartColors: ['F28E2B', 'E75B5B', '86C85B', '9B7BC4', '11B6D8', '3572B0'],
  gapWidthPct: 42, border: { color: C.white, transparency: 100 },
});

addPanel(slide4, 0.35, 4.81, 12.63, 2.20);
addSectionPill(slide4, `${D.transmission.periodShort} 传输专线开通情况`, 4.75, 4.68, 3.9);
slide4.addChart(pptx.ChartType.bar, [{ name: '传输专线合计', labels: D.transmission.months, values: D.transmission.trend }], {
  x: 0.55, y: 4.91, w: 12.2, h: 1.92,
  catAxisLabelFontFace: 'Microsoft YaHei', catAxisLabelFontSize: 8,
  catAxisLabelColor: C.gray, catAxisLineColor: C.lightGray,
  valAxisMinVal: 0, valAxisMaxVal: transmissionTrendAxisMax,
  valAxisLabelPos: 'none', valAxisLineShow: false, valAxisMajorTickMark: 'none', valAxisMinorTickMark: 'none', valAxisLabelColor: C.gray, valAxisLabelFontSize: 8, valAxisLineColor: C.lightGray,
  valGridLine: { color: C.white, transparency: 100 },
  showLegend: false, showTitle: false, showValue: true,
  dataLabelPosition: 'outEnd', dataLabelColor: C.ink,
  dataLabelFontFace: 'Microsoft YaHei', dataLabelFormatCode: '0', dataLabelFontSize: 8,
  chartColors: [SINGLE_METRIC_BLUE], gapWidthPct: 95,
  border: { color: C.white, transparency: 100 },
});

slide4.addText('口径：订单创建时间；订单状态=已完成；业务类型=传输专线；订单类型=开通；按订单号去重。', {
  x: 0.38, y: 7.21, w: 11.9, h: 0.16,
  fontFace: 'Microsoft YaHei', fontSize: 7.5, color: C.gray, margin: 0,
});
slide4.addText('6', { x: 12.65, y: 7.18, w: 0.28, h: 0.18, fontFace: 'Microsoft YaHei', fontSize: 8, color: C.gray, align: 'right', margin: 0 });
slide4.addNotes('本页数据来自传输专线指标汇总、动态月份地市表和传输专线月度分布。');

// Section divider inserted between business development and automation pages.
const automationToc = pptx.addSlide();
addTemplateBackground(automationToc);
automationToc.addText('目  录', {
  x: 0.22, y: 0.14, w: 2.2, h: 0.4,
  fontFace: 'Microsoft YaHei', fontSize: 28, bold: true, color: C.white, margin: 0,
});
const automationTocItems = [
  ['01', '业务发展情况', 'BDBDBD'],
  ['02', '专线自动情况', '438FD8'],
  ['03', '终端回收情况', 'BDBDBD'],
  ['04', '业务支撑情况', 'BDBDBD'],
];
automationTocItems.forEach((item, index) => {
  const y = 1.9 + index * 0.9;
  automationToc.addText(item[0], {
    x: 3.45, y: y + 0.1, w: 0.5, h: 0.34,
    fontFace: 'Microsoft YaHei', fontSize: 20, bold: true, color: item[2],
    margin: 0, align: 'right', valign: 'mid',
  });
  automationToc.addShape(pptx.ShapeType.parallelogram, {
    x: 4.16, y, w: 4.95, h: 0.55,
    fill: { color: item[2] }, line: { color: item[2] },
  });
  automationToc.addText(item[1], {
    x: 4.42, y: y + 0.1, w: 4.25, h: 0.34,
    fontFace: 'Microsoft YaHei', fontSize: 22, bold: true,
    color: C.white, align: 'center', margin: 0,
  });
});
automationToc.addText('7', {
  x: 12.65, y: 7.18, w: 0.28, h: 0.18,
  fontFace: 'Microsoft YaHei', fontSize: 8, color: C.lime, align: 'right', margin: 0,
});
automationToc.addNotes('章节目录页：高亮“02 专线自动情况”，承接后续自动率页面。');

// Page 8: Internet-line opening automation. Only the first chart has source data.
const slide5 = pptx.addSlide();
addTemplateBackground(slide5);
slide5.addText('专线自动率（互联网专线-开通）', {
  x: 0.23, y: 0.16, w: 7.8, h: 0.45,
  fontFace: 'Microsoft YaHei', fontSize: 28, bold: true, color: C.white, margin: 0,
});
slide5.addText([
  { text: `${D.displayMonthFull}，互联网专线开通工单`, options: { bold: true, color: C.ink } },
  { text: `整体自动率${pct(D.internetAuto.overallRate)}`, options: { bold: true, color: C.green } },
  { text: `（自动环节数${fmt(D.internetAuto.automaticCount)}，总环节数${fmt(D.internetAuto.totalCount)}）。`, options: { bold: true, color: C.ink } },
], {
  x: 0.52, y: 0.89, w: 12.2, h: 0.42,
  fontFace: 'Microsoft YaHei', fontSize: 16, margin: 0, valign: 'mid', fit: 'shrink',
});

addPanel(slide5, 0.48, 1.42, 5.82, 1.96);
addPanel(slide5, 6.38, 1.42, 6.25, 1.96);
addPanel(slide5, 0.58, 4.18, 5.82, 2.55);
slide5.addText('开通各环节自动率', {
  x: 2.15, y: 1.53, w: 2.7, h: 0.24, fontFace: 'Microsoft YaHei', fontSize: 11,
  bold: true, color: C.ink, align: 'center', margin: 0,
});
slide5.addText('各地市组网环节自动率', {
  x: 8.25, y: 1.53, w: 2.7, h: 0.24, fontFace: 'Microsoft YaHei', fontSize: 11,
  bold: true, color: C.ink, align: 'center', margin: 0,
});
slide5.addText('非自动原因工单数（工程施工）', {
  x: 1.68, y: 4.31, w: 3.65, h: 0.24, fontFace: 'Microsoft YaHei', fontSize: 11,
  bold: true, color: C.ink, align: 'center', margin: 0,
});
slide5.addChart(pptx.ChartType.bar, [{
  name: '自动率', labels: D.internetAuto.labels, values: D.internetAuto.rates,
}], {
  x: 0.67, y: 1.72, w: 5.42, h: 1.50,
  catAxisLabelFontFace: 'Microsoft YaHei', catAxisLabelFontSize: 8,
  catAxisLabelColor: C.gray, catAxisLineColor: C.lightGray,
  valAxisMinVal: 0, valAxisMaxVal: 1.08,
  valAxisLabelPos: 'none', valAxisLineShow: false, valAxisMajorTickMark: 'none', valAxisMinorTickMark: 'none', valAxisLabelColor: C.gray, valAxisLabelFontSize: 8, valAxisLineColor: C.lightGray,
  valGridLine: { color: C.white, transparency: 100 },
  showLegend: false, showTitle: false, showValue: true,
  dataLabelPosition: 'outEnd', dataLabelColor: '4472C4', dataLabelFontFace: 'Microsoft YaHei', dataLabelFontSize: 8,
  dataLabelFormatCode: '0.00%', chartColors: [SINGLE_METRIC_BLUE], gapWidthPct: 95,
  border: { color: C.white, transparency: 100 },
});
manualBar(slide5, '组网方案自动率', D.cities, D.internetAuto.network?.rates,
  { x: 6.57, y: 1.72, w: 5.85, h: 1.50 });
manualBar(slide5, '工程施工工单数', D.cities, D.internetAuto.manualReasons?.constructionCounts,
  { x: 0.77, y: 4.61, w: 5.42, h: 1.78 }, false);
const networkCopy = narratives.network(D);
slide5.addText([
  { text: networkCopy.title, options: { bold: true, breakLine: true } },
  { text: networkCopy.summary, options: { breakLine: true } },
  { text: networkCopy.cities, options: { color: 'FF0000', bold: true } },
  { text: networkCopy.suffix, options: { color: '000000' } },
], { x: .43, y: 3.52, w: 6.3, h: .65, fontFace: 'Microsoft YaHei',
     fontSize: 11.5, color: '000000', margin: 0, valign: 'top', breakLine: false });
slide5.addText('口径：自动率=自动环节数/总环节数；组网方案按去重工单计算，目标环节全部记录自动才计为自动。', {
  x: 0.45, y: 7.16, w: 11.9, h: 0.18, fontFace: 'Microsoft YaHei', fontSize: 7.5,
  color: C.gray, margin: 0,
});
slide5.addText('8', { x: 12.65, y: 7.18, w: 0.28, h: 0.18, fontFace: 'Microsoft YaHei', fontSize: 8, color: C.gray, align: 'right', margin: 0 });
slide5.addNotes('本页数据来自动态工作表“互联网自动率YYYY年M月”。地市组网自动率与工程施工原因来自手工资管统计。');

// Page 9: Internet-line move automation. Two of the four panels have source data.
const slide6 = pptx.addSlide();
addTemplateBackground(slide6);
slide6.addText('专线自动率（互联网专线-移机）', {
  x: 0.23, y: 0.16, w: 7.8, h: 0.45,
  fontFace: 'Microsoft YaHei', fontSize: 28, bold: true, color: C.white, margin: 0,
});
slide6.addText([
  { text: `${D.displayMonthFull}，互联网专线移机工单`, options: { bold: true, color: C.ink } },
  { text: `整体自动率${pct(D.internetMoveAuto.overallRate)}`, options: { bold: true, color: C.green } },
  { text: `（自动环节数${fmt(D.internetMoveAuto.automaticCount)}，总环节数${fmt(D.internetMoveAuto.totalCount)}）。`, options: { bold: true, color: C.ink } },
], {
  x: 0.52, y: 0.89, w: 12.2, h: 0.42,
  fontFace: 'Microsoft YaHei', fontSize: 16, margin: 0, valign: 'mid', fit: 'shrink',
});

const movePanels = [
  [0.75, 1.42, 6.02, 2.43], [6.84, 1.42, 6.02, 2.43],
  [0.75, 3.91, 6.02, 2.43], [6.84, 3.91, 6.02, 2.43],
];
movePanels.forEach(([x, y, w, h]) => addPanel(slide6, x, y, w, h));
[
  ['移机各环节自动率', 2.35, 1.55, 2.8],
  ['各地市组网环节自动率', 8.45, 1.55, 2.8],
  ['各地市资源反馈环节自动率', 2.18, 4.04, 3.2],
  ['各地市配置激活环节自动率', 8.27, 4.04, 3.2],
].forEach(([label, x, y, w]) => slide6.addText(label, {
  x, y, w, h: 0.24, fontFace: 'Microsoft YaHei', fontSize: 11,
  bold: true, color: C.ink, align: 'center', margin: 0,
}));

const moveChartBase = {
  catAxisLabelFontFace: 'Microsoft YaHei', catAxisLabelFontSize: 8,
  catAxisLabelColor: C.gray, catAxisLineColor: C.lightGray,
  valAxisMinVal: 0, valAxisMaxVal: 1.08,
  valAxisLabelPos: 'none', valAxisLineShow: false, valAxisMajorTickMark: 'none', valAxisMinorTickMark: 'none', valAxisLabelColor: C.gray, valAxisLabelFontSize: 8, valAxisLineColor: C.lightGray,
  valGridLine: { color: C.white, transparency: 100 },
  showLegend: false, showTitle: false, showValue: true,
  dataLabelPosition: 'outEnd', dataLabelColor: SINGLE_METRIC_BLUE, dataLabelFontFace: 'Microsoft YaHei', dataLabelFontSize: 8,
  dataLabelFormatCode: '0.00%', chartColors: [SINGLE_METRIC_BLUE], gapWidthPct: 90,
  border: { color: C.white, transparency: 100 },
};
slide6.addChart(pptx.ChartType.bar, [{
  name: '自动率', labels: D.internetMoveAuto.labels, values: D.internetMoveAuto.rates,
}], { ...moveChartBase, x: 0.94, y: 1.82, w: 5.63, h: 1.76 });
slide6.addChart(pptx.ChartType.bar, [{
  name: '配置激活自动率', labels: D.internetMoveAuto.cities, values: D.internetMoveAuto.activationRates,
}], { ...moveChartBase, x: 7.03, y: 4.31, w: 5.63, h: 1.76, catAxisLabelFontSize: 8 });

manualBar(slide6, '组网方案自动率', D.cities, D.internetMoveAuto.network?.rates,
  { x: 7.03, y: 1.82, w: 5.63, h: 1.76 });
manualBar(slide6, '资源反馈自动率', D.cities, D.internetMoveAuto.resource?.rates,
  { x: 0.94, y: 4.31, w: 5.63, h: 1.76 });
slide6.addText('口径：整体自动率=各环节自动数之和/各环节总数之和；地市配置激活自动率=配置激活自动数/移机订单总数；手工组网和资源反馈按工单计算，变更暂按移机统计。', {
  x: 0.45, y: 7.13, w: 12.0, h: 0.2, fontFace: 'Microsoft YaHei', fontSize: 7.5,
  color: C.gray, margin: 0,
});
slide6.addText('9', { x: 12.65, y: 7.18, w: 0.28, h: 0.18, fontFace: 'Microsoft YaHei', fontSize: 8, color: C.gray, align: 'right', margin: 0 });
slide6.addNotes('本页来自互联网专线移机自动率和互联网专线移机地市自动率工作表。组网方案与资源反馈地市图来自手工资管统计，变更暂按移机统计。');

// Page 10: Internet-line removal automation. The third panel is intentionally blank.
const slide7 = pptx.addSlide();
addTemplateBackground(slide7);
slide7.addText('专线自动率（互联网专线-拆机）', {
  x: 0.23, y: 0.16, w: 7.8, h: 0.45,
  fontFace: 'Microsoft YaHei', fontSize: 28, bold: true, color: C.white, margin: 0,
});
slide7.addText([
  { text: `${D.displayMonthFull}，互联网专线拆机工单`, options: { bold: true, color: C.ink } },
  { text: `整体自动率${pct(D.internetRemovalAuto.overallRate)}`, options: { bold: true, color: C.green } },
  { text: `（自动环节数${fmt(D.internetRemovalAuto.automaticCount)}，总环节数${fmt(D.internetRemovalAuto.totalCount)}）。`, options: { bold: true, color: C.ink } },
], {
  x: 0.52, y: 0.89, w: 12.2, h: 0.42,
  fontFace: 'Microsoft YaHei', fontSize: 16, margin: 0, valign: 'mid', fit: 'shrink',
});

addPanel(slide7, 0.52, 1.42, 5.82, 2.28);
addPanel(slide7, 6.43, 1.42, 6.38, 2.28);
addPanel(slide7, 0.52, 3.82, 5.82, 2.58);
[
  ['拆机各环节自动率', 2.08, 1.55, 2.7],
  ['地市配置激活环节自动率', 8.15, 1.55, 3.0],
  ['地市组织资源释放环节自动率', 1.77, 3.95, 3.35],
].forEach(([label, x, y, w]) => slide7.addText(label, {
  x, y, w, h: 0.24, fontFace: 'Microsoft YaHei', fontSize: 11,
  bold: true, color: C.ink, align: 'center', margin: 0,
}));

slide7.addChart(pptx.ChartType.bar, [{
  name: '自动率', labels: D.internetRemovalAuto.labels, values: D.internetRemovalAuto.rates,
}], { ...moveChartBase, x: 0.72, y: 1.82, w: 5.42, h: 1.62 });
slide7.addChart(pptx.ChartType.bar, [{
  name: '配置激活自动率', labels: D.internetRemovalAuto.cities, values: D.internetRemovalAuto.activationRates,
}], { ...moveChartBase, x: 6.64, y: 1.82, w: 5.94, h: 1.62, catAxisLabelFontSize: 8 });

manualBar(slide7, '组织资源释放自动率', D.cities, D.internetRemovalAuto.release?.rates,
  { x: 0.72, y: 4.26, w: 5.42, h: 1.82 });
slide7.addText('口径：整体自动率=各环节自动数之和/各环节总数之和；地市配置激活自动率=配置激活自动数/拆机订单总数；组织资源释放按包含该环节的去重工单计算。', {
  x: 0.45, y: 7.13, w: 12.0, h: 0.2, fontFace: 'Microsoft YaHei', fontSize: 7.5,
  color: C.gray, margin: 0,
});
slide7.addText('10', { x: 12.58, y: 7.18, w: 0.35, h: 0.18, fontFace: 'Microsoft YaHei', fontSize: 8, color: C.gray, align: 'right', margin: 0 });
slide7.addNotes('本页来自互联网专线拆机自动率和互联网专线拆机地市自动率工作表。地市组织资源释放自动率来自手工资管统计。');

// Page 11: Terminal recovery section divider.
const terminal = D.terminalRecovery;
const terminalSectionSlide = pptx.addSlide();
addTemplateBackground(terminalSectionSlide);
terminalSectionSlide.addText('目  录', {
  x: 0.22, y: 0.14, w: 2.2, h: 0.4,
  fontFace: 'Microsoft YaHei', fontSize: 28, bold: true, color: C.white, margin: 0,
});
const terminalTocItems = [
  ['01', '业务发展情况', 'BDBDBD'],
  ['02', '专线自动情况', 'BDBDBD'],
  ['03', '终端回收情况', '438FD8'],
  ['04', '业务支撑情况', 'BDBDBD'],
];
terminalTocItems.forEach((item, index) => {
  const y = 1.9 + index * 0.9;
  terminalSectionSlide.addText(item[0], {
    x: 3.45, y: y + 0.1, w: 0.5, h: 0.34,
    fontFace: 'Microsoft YaHei', fontSize: 20, bold: true, color: item[2],
    margin: 0, align: 'right', valign: 'mid',
  });
  terminalSectionSlide.addShape(pptx.ShapeType.parallelogram, {
    x: 4.16, y, w: 4.95, h: 0.55,
    fill: { color: item[2] }, line: { color: item[2] },
  });
  terminalSectionSlide.addText(item[1], {
    x: 4.42, y: y + 0.1, w: 4.25, h: 0.34,
    fontFace: 'Microsoft YaHei', fontSize: 22, bold: true,
    color: C.white, align: 'center', margin: 0,
  });
});
terminalSectionSlide.addText('11', {
  x: 12.65, y: 7.18, w: 0.28, h: 0.18,
  fontFace: 'Microsoft YaHei', fontSize: 8, color: C.lime, align: 'right', margin: 0,
});
terminalSectionSlide.addNotes('新增章节页：终端回收情况。');

// Page 12: Terminal recovery rate overview.
const terminalOverviewSlide = pptx.addSlide();
addTemplateBackground(terminalOverviewSlide);
terminalOverviewSlide.addText('终端回收情况', {
  x: 0.18, y: 0.15, w: 2.29, h: 0.48,
  fontFace: 'Microsoft YaHei', fontSize: 24, bold: true, color: C.white,
  margin: 0, fit: 'shrink',
});
terminalOverviewSlide.addText([
  { text: '终端回收（装维设备配置完成量）\n', options: { bold: true, color: '0B336F' } },
  { text: `      ${D.displayMonth}全省拆机应回收设备数${fmt(terminal.city.expectedTotal)}台，已拆机设备数${fmt(terminal.city.completedTotal)}台，全省终端回收率${pct(terminal.city.rate)}，${nameList(terminal.city.bottomRankNames)}排名靠后。`, options: { color: '0B336F' } },
], {
  x: 0.05, y: 0.76, w: 13.11, h: 0.76,
  fontFace: 'Microsoft YaHei', fontSize: 12, margin: 0.02, fit: 'shrink',
});
addPanel(terminalOverviewSlide, 0.29, 1.54, 12.73, 2.39);
terminalOverviewSlide.addChart([
  {
    type: pptx.ChartType.bar,
    data: [
      { name: '应拆回设备数', labels: terminal.city.labels, values: terminal.city.expected },
      { name: '已拆回设备数量', labels: terminal.city.labels, values: terminal.city.completed },
    ],
    options: {
      showValue: true,
      dataLabelPosition: 'outEnd',
      dataLabelFontFace: 'Microsoft YaHei',
      dataLabelFontSize: 6.5,
      gapWidthPct: 45,
      overlap: 0,
    },
  },
  {
    type: pptx.ChartType.line,
    data: [{ name: '终端回收率', labels: terminal.city.labels, values: terminal.city.rates }],
    options: {
      secondaryValAxis: true,
      secondaryCatAxis: true,
      showValue: true,
      dataLabelPosition: 'above',
      dataLabelFontFace: 'Microsoft YaHei',
      dataLabelFontSize: 7,
      dataLabelFormatCode: '0.00%',
      lineSize: 1.5,
      lineDataSymbolLineColor: '9BBB59',
      lineDataSymbolLineSize: 1.0,
      showMarker: true,
      markerSize: 5,
    },
  },
], {
  x: 0.29, y: 1.54, w: 12.73, h: 2.39,
  catAxisLabelFontFace: 'Microsoft YaHei', catAxisLabelFontSize: 8,
  catAxisLabelColor: C.ink, catAxisLineColor: C.lightGray,
  catAxes: [{}, { catAxisLabelPos: 'none', catAxisLineColor: C.white }],
  valAxes: [
    { valAxisMinVal: 0, valAxisMaxVal: 5000, valAxisLabelFontSize: 7, valAxisLabelPos: 'none', valAxisLineShow: false, valAxisMajorTickMark: 'none', valAxisMinorTickMark: 'none', valAxisLabelColor: C.gray, valAxisLineColor: C.lightGray, valGridLine: { color: 'E6EAF0', transparency: 20 } },
    { valAxisMinVal: 0, valAxisMaxVal: 1, valAxisLabelFormatCode: '0%', valAxisLabelPos: 'none', valAxisLineShow: false, valAxisMajorTickMark: 'none', valAxisMinorTickMark: 'none', valAxisLabelColor: C.white, valAxisLineColor: C.white, valGridLine: { color: C.white, transparency: 100 } },
  ],
  showLegend: true, legendPos: 't', legendFontFace: 'Microsoft YaHei', legendFontSize: 8,
  chartColors: ['4F81BD', 'C0504D', '9BBB59'],
  border: { color: C.white, transparency: 100 },
});
terminalOverviewSlide.addText([
  { text: '终端回收率（后 TOP10 区县）\n', options: { bold: true, color: '0B336F' } },
  { text: `      ${D.displayMonth}全省终端回收率${pct(terminal.city.rate)}，各区县终端回收情况对比，${nameList(terminal.topInstaller.bottomRankNames)}排名靠后。`, options: { color: '0B336F' } },
], {
  x: 0.05, y: 4.06, w: 13.11, h: 0.79,
  fontFace: 'Microsoft YaHei', fontSize: 12, margin: 0.02, fit: 'shrink',
});
addPanel(terminalOverviewSlide, 0.29, 4.77, 12.73, 2.13);
terminalOverviewSlide.addChart([
  {
    type: pptx.ChartType.bar,
    data: [
      { name: '应拆回设备数', labels: terminal.topInstaller.labels, values: terminal.topInstaller.expected },
      { name: '已拆回设备数量', labels: terminal.topInstaller.labels, values: terminal.topInstaller.completed },
    ],
    options: {
      showValue: true,
      dataLabelPosition: 'outEnd',
      dataLabelFontFace: 'Microsoft YaHei',
      dataLabelFontSize: 6.5,
      gapWidthPct: 45,
      overlap: 0,
    },
  },
  {
    type: pptx.ChartType.line,
    data: [{ name: '终端回收率', labels: terminal.topInstaller.labels, values: terminal.topInstaller.rates }],
    options: {
      secondaryValAxis: true,
      secondaryCatAxis: true,
      showValue: true,
      dataLabelPosition: 'above',
      dataLabelFontFace: 'Microsoft YaHei',
      dataLabelFontSize: 7,
      dataLabelFormatCode: '0.00%',
      lineSize: 1.5,
      lineDataSymbolLineColor: '9BBB59',
      lineDataSymbolLineSize: 1.0,
      showMarker: true,
      markerSize: 5,
    },
  },
], {
  x: 0.29, y: 4.77, w: 12.73, h: 2.13,
  catAxisLabelFontFace: 'Microsoft YaHei', catAxisLabelFontSize: 8,
  catAxisLabelColor: C.ink, catAxisLineColor: C.lightGray,
  catAxes: [{}, { catAxisLabelPos: 'none', catAxisLineColor: C.white }],
  valAxes: [
    { valAxisMinVal: 0, valAxisMaxVal: 800, valAxisLabelFontSize: 7, valAxisLabelPos: 'none', valAxisLineShow: false, valAxisMajorTickMark: 'none', valAxisMinorTickMark: 'none', valAxisLabelColor: C.gray, valAxisLineColor: C.lightGray, valGridLine: { color: 'E6EAF0', transparency: 20 } },
    { valAxisMinVal: 0, valAxisMaxVal: 1, valAxisLabelFormatCode: '0%', valAxisLabelPos: 'none', valAxisLineShow: false, valAxisMajorTickMark: 'none', valAxisMinorTickMark: 'none', valAxisLabelColor: C.white, valAxisLineColor: C.white, valGridLine: { color: C.white, transparency: 100 } },
  ],
  showLegend: true, legendPos: 't', legendFontFace: 'Microsoft YaHei', legendFontSize: 8,
  chartColors: ['4F81BD', 'C0504D', '9BBB59'],
  border: { color: C.white, transparency: 100 },
});
terminalOverviewSlide.addText('注1：终端回收率=拆机设备回收单量/拆机工单竣工量；注2：后TOP10终端回收率=拆机设备回收单量/拆机工单竣工量。', {
  x: 0.18, y: 6.90, w: 12.62, h: 0.41,
  fontFace: 'Microsoft YaHei', fontSize: 7.5, color: C.gray, margin: 0, fit: 'shrink',
});
terminalOverviewSlide.addText('12', { x: 12.58, y: 7.18, w: 0.35, h: 0.18, fontFace: 'Microsoft YaHei', fontSize: 8, color: C.gray, align: 'right', margin: 0 });
terminalOverviewSlide.addNotes('新增内容页：终端回收率概况，数据来自终端回收概况结果表。');

// Page 13: Terminal recovery detail by device type.
const terminalDetailSlide = pptx.addSlide();
addTemplateBackground(terminalDetailSlide);
terminalDetailSlide.addText('终端回收情况', {
  x: 0.18, y: 0.15, w: 2.29, h: 0.48,
  fontFace: 'Microsoft YaHei', fontSize: 24, bold: true, color: C.white,
  margin: 0, fit: 'shrink',
});
terminalDetailSlide.addText([
  { text: '终端回收数量（按业务类型展示）\n', options: { bold: true, color: '0B336F' } },
  { text: `      ${D.displayMonth}全省终端已完成设备${fmt(terminal.city.completedTotal)}台，设备回收TOP3为：${deviceList(terminal.topDevices)}。`, options: { color: '0B336F' } },
], {
  x: 0.13, y: 0.75, w: 13.11, h: 0.79,
  fontFace: 'Microsoft YaHei', fontSize: 12, margin: 0.02, fit: 'shrink',
});
const terminalStackedChartBase = {
  catAxisLabelFontFace: 'Microsoft YaHei',
  catAxisLabelFontSize: 8,
  catAxisLabelColor: C.ink,
  catAxisLineColor: C.lightGray,
  valAxisMinVal: 0,
  valAxisLabelFontSize: 7,
  valAxisLabelPos: 'none', valAxisLineShow: false, valAxisMajorTickMark: 'none', valAxisMinorTickMark: 'none', valAxisLabelColor: C.gray,
  valAxisLineColor: C.lightGray,
  valGridLine: { color: 'E6EAF0', transparency: 20 },
  showLegend: true,
  legendPos: 't',
  legendFontFace: 'Microsoft YaHei',
  legendFontSize: 8,
  showValue: true,
  dataLabelPosition: 'outEnd',
  dataLabelFontFace: 'Microsoft YaHei',
  dataLabelFontSize: 6,
  grouping: 'stacked',
  chartColors: ['4F81BD', 'C0504D', '9BBB59', 'F28E2B', '8064A2'],
  border: { color: C.white, transparency: 100 },
};
addPanel(terminalDetailSlide, 0.24, 1.39, 12.70, 1.53);
terminalDetailSlide.addChart(pptx.ChartType.bar, terminal.business.series.map(item => ({
  name: item.name, labels: terminal.business.labels, values: item.values,
})), {
  ...terminalStackedChartBase,
  x: 0.24, y: 1.39, w: 12.70, h: 1.53,
  valAxisMaxVal: 8000,
});
terminalDetailSlide.addText('终端回收数量（按地市和区县后 TOP10 展示）', {
  x: 0.13, y: 2.95, w: 13.11, h: 0.32,
  fontFace: 'Microsoft YaHei', fontSize: 12, bold: true, color: '0B336F',
  margin: 0, fit: 'shrink',
});
addPanel(terminalDetailSlide, 0.24, 3.36, 12.70, 1.83);
terminalDetailSlide.addChart(pptx.ChartType.bar, terminal.cityDevices.series.map(item => ({
  name: item.name, labels: terminal.cityDevices.labels, values: item.values,
})), {
  ...terminalStackedChartBase,
  x: 0.24, y: 3.36, w: 12.70, h: 1.83,
  valAxisMaxVal: 3500,
});
addPanel(terminalDetailSlide, 0.24, 5.25, 12.70, 1.88);
terminalDetailSlide.addChart(pptx.ChartType.bar, terminal.installerDevices.series.map(item => ({
  name: item.name, labels: terminal.installerDevices.labels, values: item.values,
})), {
  ...terminalStackedChartBase,
  x: 0.24, y: 5.25, w: 12.70, h: 1.88,
  valAxisMaxVal: 360,
});
terminalDetailSlide.addText('13', { x: 12.58, y: 7.18, w: 0.35, h: 0.18, fontFace: 'Microsoft YaHei', fontSize: 8, color: C.gray, align: 'right', margin: 0 });
terminalDetailSlide.addNotes('新增内容页：终端回收数量拆分，数据来自终端回收明细结果表。');

// Page 14: Business support section divider.
const businessSupportToc = pptx.addSlide();
addTemplateBackground(businessSupportToc);
businessSupportToc.addText('目  录', {
  x: 0.22, y: 0.14, w: 2.2, h: 0.4,
  fontFace: 'Microsoft YaHei', fontSize: 28, bold: true, color: C.white, margin: 0,
});
const businessSupportTocItems = [
  ['01', '业务发展情况', 'BDBDBD'],
  ['02', '专线自动情况', 'BDBDBD'],
  ['03', '终端回收情况', 'BDBDBD'],
  ['04', '业务支撑情况', '438FD8'],
];
businessSupportTocItems.forEach((item, index) => {
  const y = 1.9 + index * 0.9;
  businessSupportToc.addText(item[0], {
    x: 3.45, y: y + 0.1, w: 0.5, h: 0.34,
    fontFace: 'Microsoft YaHei', fontSize: 20, bold: true, color: item[2],
    margin: 0, align: 'right', valign: 'mid',
  });
  businessSupportToc.addShape(pptx.ShapeType.parallelogram, {
    x: 4.16, y, w: 4.95, h: 0.55,
    fill: { color: item[2] }, line: { color: item[2] },
  });
  businessSupportToc.addText(item[1], {
    x: 4.42, y: y + 0.1, w: 4.25, h: 0.34,
    fontFace: 'Microsoft YaHei', fontSize: 22, bold: true,
    color: C.white, align: 'center', margin: 0,
  });
});
businessSupportToc.addText('14', {
  x: 12.65, y: 7.18, w: 0.28, h: 0.18,
  fontFace: 'Microsoft YaHei', fontSize: 8, color: C.lime, align: 'right', margin: 0,
});
businessSupportToc.addNotes('章节目录页：高亮“04 业务支撑情况”，承接后续业务支撑页面。');

// Page 15: Dedicated-line and enterprise-broadband withdrawal metrics.
const withdrawal = D.withdrawal;
const withdrawalSlide = pptx.addSlide();
addTemplateBackground(withdrawalSlide);
withdrawalSlide.addText('业务情况-集团撤退单', {
  x: 0.16, y: 0.14, w: 8.0, h: 0.48, fontFace: 'Microsoft YaHei',
  fontSize: 24, bold: true, color: C.white, margin: 0,
});
const withdrawalText = { x: 0.36, w: 12.55, fontFace: 'Microsoft YaHei', fontSize: 11.5, color: '0B336F', margin: 0 };
function withdrawalCombo(title, labels, bars, rates, y) {
  addPanel(withdrawalSlide, 0.36, y, 12.55, 1.28);
  withdrawalSlide.addChart([
    { type: pptx.ChartType.bar, data: bars.map(b => ({name: b.name, labels, values: b.values})),
      options: { showValue: true, dataLabelPosition: 'outEnd', dataLabelFontSize: 8,
        dataLabelFormatCode: '0', gapWidthPct: 65 } },
    { type: pptx.ChartType.line, data: [{ name: '撤退单率', labels, values: rates }],
      options: { secondaryValAxis: true, secondaryCatAxis: true, showValue: true,
        dataLabelPosition: 'above', dataLabelFontSize: 8, dataLabelColor: '2EA8CB',
        dataLabelFormatCode: '0.00%', lineSize: 1.0, showMarker: true, markerSize: 4,
        lineDataSymbolLineColor: '43B0CD', lineDataSymbolLineSize: 1 } },
  ], {
    x: 0.36, y, w: 12.55, h: 1.28,
    catAxisLabelFontFace: 'Microsoft YaHei', catAxisLabelFontSize: 8,
    catAxisLabelColor: C.ink, catAxisLineColor: C.lightGray,
    catAxes: [{}, { catAxisLabelPos: 'none', catAxisLineColor: C.white }],
    valAxes: [
      { valAxisMinVal: 0, valAxisMaxVal: Math.max(1, ...bars.flatMap(b => b.values).filter(v => v != null)) * 1.6,
        valAxisLabelPos: 'none', valAxisLineShow: false, valAxisMajorTickMark: 'none', valAxisMinorTickMark: 'none', valAxisLabelColor: C.white, valAxisLineColor: C.white, valGridLine: { color: C.white, transparency: 100 } },
      { valAxisMinVal: 0, valAxisMaxVal: Math.max(.01, ...rates.filter(v => v != null)) * 1.6,
        valAxisLabelPos: 'none', valAxisLineShow: false, valAxisMajorTickMark: 'none', valAxisMinorTickMark: 'none', valAxisLabelColor: C.white, valAxisLineColor: C.white, valGridLine: { color: C.white, transparency: 100 } },
    ],
    showLegend: true, legendPos: 't', legendFontFace: 'Microsoft YaHei', legendFontSize: 8,
    showTitle: true, title, titleFontFace: 'Microsoft YaHei', titleFontSize: 10, titleBold: true,
    chartColors: bars.length === 2 ? ['C0504D', '9BBB59', '43B0CD'] : ['4F81BD', 'C0504D', '9BBB59', '43B0CD'],
  });
}
function sortedCityData(data, ascending = false) {
  const indexes = data.cities.map((_,i) => i).sort((a,b) =>
    ((data.rates[a] ?? -1) - (data.rates[b] ?? -1)) * (ascending ? 1 : -1));
  return { labels: indexes.map(i => data.cities[i]), pick: values => indexes.map(i => values[i]) };
}
withdrawalSlide.addText(narratives.withdrawal(D),
  { ...withdrawalText, y: .77, h: .53, valign: 'top' });
const lineOrder = sortedCityData(withdrawal);
withdrawalCombo('专线开通报结撤退率情况', lineOrder.labels,
  [{name: '网络建设原因', values: lineOrder.pick(withdrawal.networkReasons)},
   {name: '用户原因', values: lineOrder.pick(withdrawal.customerReasons)},
   {name: '前台原因', values: lineOrder.pick(withdrawal.frontDeskReasons)}], lineOrder.pick(withdrawal.rates), 1.32);
withdrawalSlide.addText('注：专线撤退率取数据库指标；原因来自手工反馈样本，样本周期和全量撤退单范围可能不同。',
  { ...withdrawalText, y: 2.64, h: .19, fontSize: 8, color: C.ink });
const qikuan = D.qikuanWithdrawal;
withdrawalSlide.addText(narratives.qikuan(D, qikuan, false), { ...withdrawalText, y: 2.87, h: .48 });
if (qikuan) {
  const order = sortedCityData(qikuan);
  withdrawalCombo(`${D.displayMonth}企宽撤退单率`, order.labels,
    [{name: '退单量', values: order.pick(qikuan.returnCounts)}, {name: '撤单量', values: order.pick(qikuan.cancellationCounts)}], order.pick(qikuan.rates), 3.41);
}
withdrawalSlide.addText('注：撤退率=（退单完成+撤单完成）/提供文件的全部受理明细；每行计1单，按文件指定周期统计。',
  { ...withdrawalText, y: 4.73, h: .19, fontSize: 8, color: C.ink });
const qikuanReturn = D.qikuanReturn;
withdrawalSlide.addText(narratives.qikuan(D, qikuanReturn, true), { ...withdrawalText, y: 4.96, h: .48 });
if (qikuanReturn) {
  const order = sortedCityData(qikuanReturn, true);
  addPanel(withdrawalSlide, .36, 5.5, 12.55, 1.27);
  withdrawalSlide.addText(`${D.displayMonth}企宽退单率（不含一次性撤单）`, {
    x: 3.5, y: 5.55, w: 6.2, h: .22, fontSize: 11, bold: true, align: 'center', margin: 0 });
  manualBar(withdrawalSlide, '企宽退单率', order.labels, order.pick(qikuanReturn.rates),
    {x: .5, y: 5.81, w: 12.2, h: .91});
}
withdrawalSlide.addText('注：退单率=退单完成/提供文件的全部受理明细；撤单完成不计入分子。',
  { ...withdrawalText, y: 6.84, h: .21, fontSize: 8, color: C.ink });
withdrawalSlide.addText('15', { x: 12.58, y: 7.18, w: .35, h: .18, fontSize: 8, color: C.gray, margin: 0 });
withdrawalSlide.addNotes('专线原因、企宽撤退与企宽退单分别来自标准化手工结果；企宽两个口径分别存储，不互相覆盖。');

// Page 16: Repeat complaint and new-install fault report.
const complaintFault = D.complaintFault;
const repeat = complaintFault.repeat;
const fault = complaintFault.fault;
// Keep both axes aligned and leave headroom for values above the old fixed limits.
const repeatAxisMax = Math.max(0.04, ...repeat.lineRates, ...repeat.broadbandRates, ...(repeat.qikuanRates || []), ...repeat.totalRates) * 1.2;
const faultAxisMax = Math.max(0.008, ...fault.lineRates, ...fault.broadbandRates, ...fault.totalRates) * 1.2;
const repeatBox = { x: 0.53, y: 1.25, w: 12.17, h: 2.49 };
const faultBox = { x: 0.53, y: 4.56, w: 12.17, h: 2.57 };
const complaintFaultSlide = pptx.addSlide();
addTemplateBackground(complaintFaultSlide);
complaintFaultSlide.addText('业务情况-商客业务重复投诉与新装报障', {
  x: 0.12, y: 0.14, w: 11.07, h: 0.54,
  fontFace: 'Microsoft YaHei', fontSize: 24, bold: true, color: C.white,
  margin: 0, fit: 'shrink',
});
complaintFaultSlide.addText(narratives.repeat(D), {
  x: 0.33, y: 0.76, w: 12.64, h: 0.45,
  fontFace: 'Microsoft YaHei', fontSize: 12, color: '0B336F',
  margin: 0.02, fit: 'shrink',
});
addPanel(complaintFaultSlide, repeatBox.x, repeatBox.y, repeatBox.w, repeatBox.h);
complaintFaultSlide.addChart([
  {
    type: pptx.ChartType.bar,
    data: [
      { name: '专线重复投诉率', labels: repeat.cities, values: repeat.lineRates },
      { name: '千里眼重复投诉率', labels: repeat.cities, values: repeat.broadbandRates },
      { name: '企宽重复投诉率', labels: repeat.cities, values: repeat.qikuanRates || repeat.cities.map(() => null) },
    ],
    options: {
      showValue: true,
      dataLabelPosition: 'outEnd',
      dataLabelColor: C.ink,
      dataLabelFontFace: 'Microsoft YaHei',
      dataLabelFontSize: 8,
      dataLabelFormatCode: '0.00%',
      gapWidthPct: 60,
      overlap: 0,
    },
  },
  {
    type: pptx.ChartType.line,
    data: [{ name: '商客合计（专线+企宽）', labels: repeat.cities, values: repeat.totalRates }],
    options: {
      secondaryValAxis: true,
      secondaryCatAxis: true,
      showValue: true,
      dataLabelPosition: 'above',
      dataLabelColor: '2EA8CB',
      dataLabelFontFace: 'Microsoft YaHei',
      dataLabelFontSize: 8,
      dataLabelFormatCode: '0.00%',
      lineSize: 1.5,
      lineDataSymbolLineColor: '43B0CD',
      lineDataSymbolLineSize: 1.0,
      showMarker: true,
      markerSize: 5,
    },
  },
], {
  ...repeatBox,
  catAxisLabelFontFace: 'Microsoft YaHei', catAxisLabelFontSize: 8.5,
  catAxisLabelColor: C.ink, catAxisLineColor: C.lightGray,
  catAxes: [{}, { catAxisLabelPos: 'none', catAxisLineColor: C.white }],
  valAxes: [
    { valAxisMinVal: 0, valAxisMaxVal: repeatAxisMax, valAxisLabelPos: 'none', valAxisLineShow: false, valAxisMajorTickMark: 'none', valAxisMinorTickMark: 'none', valAxisLabelColor: C.white, valAxisLineColor: C.white, valGridLine: { color: C.white, transparency: 100 } },
    { valAxisMinVal: 0, valAxisMaxVal: repeatAxisMax, valAxisLabelPos: 'none', valAxisLineShow: false, valAxisMajorTickMark: 'none', valAxisMinorTickMark: 'none', valAxisLabelColor: C.white, valAxisLineColor: C.white, valGridLine: { color: C.white, transparency: 100 } },
  ],
  showLegend: true, legendPos: 't', legendFontFace: 'Microsoft YaHei', legendFontSize: 9,
  showTitle: true, title: '重复投诉率', titleFontFace: 'Microsoft YaHei', titleFontSize: 11, titleBold: true,
  showValue: true,
  chartColors: ['4F81BD', 'C0504D', '8064A2', '9BBB59'],
  border: { color: C.white, transparency: 100 },
});
complaintFaultSlide.addText('注：商客合计=(专线分子+企宽分子)/(专线分母+企宽分母)，千里眼不参与；合计=专线重复投诉率*0.4+企宽重复投诉率*0.4+千里眼重复投诉率*0.2；按指定口径合并各自周期。企宽含历史判重，省级含“其他”地市。', {
  x: 0.41, y: 3.81, w: 10.32, h: 0.25,
  fontFace: 'Microsoft YaHei', fontSize: 8.5, color: C.gray,
  margin: 0, fit: 'shrink',
});
complaintFaultSlide.addText(narratives.fault(D), {
  x: 0.33, y: 4.07, w: 12.53, h: 0.45,
  fontFace: 'Microsoft YaHei', fontSize: 12, color: '0B336F',
  margin: 0.02, fit: 'shrink',
});
addPanel(complaintFaultSlide, faultBox.x, faultBox.y, faultBox.w, faultBox.h);
complaintFaultSlide.addChart([
  {
    type: pptx.ChartType.bar,
    data: [
      { name: '专线类新装报障率', labels: fault.cities, values: fault.lineRates },
      { name: '小微宽带新装报障率', labels: fault.cities, values: fault.broadbandRates },
    ],
    options: {
      showValue: true,
      dataLabelPosition: 'outEnd',
      dataLabelColor: C.ink,
      dataLabelFontFace: 'Microsoft YaHei',
      dataLabelFontSize: 8,
      dataLabelFormatCode: '0.00%',
      gapWidthPct: 60,
      overlap: 0,
    },
  },
  {
    type: pptx.ChartType.line,
    data: [{ name: '合计', labels: fault.cities, values: fault.totalRates }],
    options: {
      secondaryValAxis: true,
      secondaryCatAxis: true,
      showValue: true,
      dataLabelPosition: 'above',
      dataLabelColor: '2EA8CB',
      dataLabelFontFace: 'Microsoft YaHei',
      dataLabelFontSize: 8,
      dataLabelFormatCode: '0.00%',
      lineSize: 1.0,
      lineDataSymbolLineColor: '9BBB59',
      lineDataSymbolLineSize: 1.0,
      showMarker: true,
      markerSize: 5,
    },
  },
], {
  ...faultBox,
  catAxisLabelFontFace: 'Microsoft YaHei', catAxisLabelFontSize: 8.5,
  catAxisLabelColor: C.ink, catAxisLineColor: C.lightGray,
  catAxes: [{}, { catAxisLabelPos: 'none', catAxisLineColor: C.white }],
  valAxes: [
    { valAxisMinVal: 0, valAxisMaxVal: faultAxisMax, valAxisLabelPos: 'none', valAxisLineShow: false, valAxisMajorTickMark: 'none', valAxisMinorTickMark: 'none', valAxisLabelColor: C.white, valAxisLineColor: C.white, valGridLine: { color: C.white, transparency: 100 } },
    { valAxisMinVal: 0, valAxisMaxVal: faultAxisMax, valAxisLabelPos: 'none', valAxisLineShow: false, valAxisMajorTickMark: 'none', valAxisMinorTickMark: 'none', valAxisLabelColor: C.white, valAxisLineColor: C.white, valGridLine: { color: C.white, transparency: 100 } },
  ],
  showLegend: true, legendPos: 't', legendFontFace: 'Microsoft YaHei', legendFontSize: 9,
  showTitle: true, title: '新装报障率', titleFontFace: 'Microsoft YaHei', titleFontSize: 11, titleBold: true,
  showValue: true,
  chartColors: ['4F81BD', 'C0504D', '9BBB59'],
  border: { color: C.white, transparency: 100 },
});
complaintFaultSlide.addText('16', { x: 12.58, y: 7.18, w: 0.35, h: 0.18, fontFace: 'Microsoft YaHei', fontSize: 8, color: C.gray, align: 'right', margin: 0 });
complaintFaultSlide.addNotes('业务情况-商客业务重复投诉与新装报障，页面数据来自重复投诉与新装报障结果表。');

pptx.writeFile({ fileName: outputFile });
