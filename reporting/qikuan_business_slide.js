// Native, editable charts. Used by the monthly deck and by the isolated page preview.
const BLUE = '00A2E8', RED = 'D84949', GREEN = '00B050', INK = '252525';
const valid = v => typeof v === 'number' && Number.isFinite(v);
const num = v => valid(v) ? String(v) : '待补充';
const rate = v => !valid(v) ? '待补充' : v === 0 ? '持平' : `${v > 0 ? '上升' : '下降'}${(Math.abs(v) * 100).toFixed(2)}%`;

function citySummary(rows, key) {
  const known = rows.filter(r => valid(r[key]));
  if (!known.length) return '';
  if (known.every(r => r[key] > 0) && known.length === 11) return '所有地市均上升';
  if (known.every(r => r[key] < 0) && known.length === 11) return '所有地市均下降';
  if (known.every(r => r[key] === 0) && known.length === 11) return '所有地市均持平';
  const down = known.filter(r => r[key] < 0).map(r => `${r.city}下降${(Math.abs(r[key]) * 100).toFixed(2)}%`);
  const flat = known.filter(r => r[key] === 0).map(r => r.city);
  const up = known.filter(r => r[key] > 0).map(r => r.city);
  return [...(down.length ? [down.length <= 3 ? down.join('、') : `${down.slice(0, 3).join('、')}等${down.length}个地市下降`] : []),
    ...(flat.length ? [flat.join('、') + '持平'] : []),
    ...(up.length ? [up.length === 11 - down.length - flat.length && down.length + flat.length > 0
      ? '其余地市上升' : up.join('、') + '上升'] : []),
    ...(known.length < 11 ? ['部分地市待补充'] : [])].join('，');
}

function addQikuanBusinessSlide(pptx, Q, helpers, page = 7) {
  const slide = pptx.addSlide();
  helpers.addTemplateBackground(slide);
  const text = (value, x, y, w, h, extra = {}) => slide.addText(value, {
    x, y, w, h, fontFace: 'Microsoft YaHei', fontSize: 13, color: INK, margin: 0, breakLine: false, ...extra,
  });
  text('业务存量及发展量-企宽业务', .22, .14, 10.5, .45, {fontSize: 28, bold: true, color: 'FFFFFF'});
  const [year, month] = Q.month.split('-').map(Number);
  const previous = month === 1 ? `${String(year - 1).slice(2)}.12` : `${String(year).slice(2)}.${String(month - 1).padStart(2, '0')}`;
  const short = `${String(year).slice(2)}.${String(month).padStart(2, '0')}`;
  const yearAgo = `${String(year - 1).slice(2)}.${String(month).padStart(2, '0')}`;
  const s = Q.stock.province, o = Q.opening.province;
  const colored = (label, value, suffix = '') => [
    {text: label}, {text: rate(value), options: {color: valid(value) ? (value < 0 ? RED : GREEN) : '777777'}},
    {text: suffix},
  ];
  text([
    {text: `截至${month}月底，`}, {text: `企宽总存量数${num(s.current)}`, options: {color: '0070C0'}},
    ...colored('，环比（较上月）', s.mom, '；'),
    ...colored(`同比（较${String(year - 1).slice(2)}年${month}月）`, s.yoy, '。'),
    {text: '\n' + (!valid(s.yoy) || !valid(s.mom) ? '历史存量基数缺失或为0，对应同比、环比暂不可计算。' :
      `环比：${citySummary(Q.stock.cities, 'mom')}；同比：${citySummary(Q.stock.cities, 'yoy')}。`)},
  ], .3, .78, 12.65, .6, {bold: true, fontSize: 13});

  function panel(title, x, y, w, h, titleWidth) {
    helpers.addPanel(slide, x, y, w, h);
    helpers.addSectionPill(slide, title, x + (w - titleWidth) / 2, y - .13, titleWidth);
  }
  panel('全省企宽存量数', .3, 1.62, 4.25, 2.02, 2.35);
  panel('各地市企宽存量数同比、环比情况', 4.8, 1.62, 8.15, 2.02, 4.0);
  panel('全省企宽开通量', .3, 5.05, 4.25, 2.02, 2.5);
  panel('各地市企宽开通量同比', 4.8, 5.05, 8.15, 2.02, 3.5);

  function chart(series, box, percent = false, colors = null) {
    const values = series.flatMap(s => s.values).filter(valid);
    if (!values.length) {
      text(percent ? '比较基数待补充' : '开通量结果待补充', box.x, box.y + .5, box.w, .5,
        {fontSize: 14, color: '888888', align: 'center'});
      return;
    }
    const max = Math.max(percent ? .01 : 1, ...values);
    const min = Math.min(0, ...values);
    slide.addChart(pptx.ChartType.bar, series, {
      ...box, catAxisLabelFontFace: 'Microsoft YaHei', catAxisLabelFontSize: 9,
      catAxisLabelColor: '666666', catAxisLineColor: 'D9DEE5',
      catAxisLabelPos: 'low', valAxisMinVal: min < 0 ? min * 1.35 : 0, valAxisMaxVal: max * 1.3,
      valAxisLabelPos: 'none', valAxisLineShow: false, valAxisMajorTickMark: 'none',
      valAxisLineColor: 'FFFFFF', valGridLine: {color: 'FFFFFF', transparency: 100},
      showLegend: series.length > 1, legendPos: 't', legendFontSize: 9,
      legendFontFace: 'Microsoft YaHei', showValue: true, showTitle: false,
      dataLabelPosition: 'outEnd', dataLabelColor: '555555', dataLabelFontSize: 9,
      dataLabelFormatCode: percent ? '0.00%;-0.00%;0.00%' : '0',
      chartColors: colors || (percent ? [BLUE, RED] : [BLUE]), gapWidthPct: percent ? 85 : 110,
      showCatName: false, showBorder: false,
    });
  }
  const label = (name, value) => name + (valid(value) ? '\u200B' : '\n待补充');
  chart([{name: '企宽存量', labels: [label(yearAgo, s.year_ago), label(short, s.current), label(previous, s.previous)],
    values: [s.year_ago, s.current, s.previous]}], {x: .42, y: 1.92, w: 4.0, h: 1.58}, false, ['65BFEE', 'FFAA5A', '65BFEE']);
  const cities = Q.stock.cities.map(r => r.city);
  chart([{name: '同比', labels: cities, values: Q.stock.cities.map(r => r.yoy)},
    {name: '环比', labels: cities, values: Q.stock.cities.map(r => r.mom)}], {x: 4.95, y: 1.83, w: 7.85, h: 1.72}, true);

  text([
    {text: `${month}月`}, {text: valid(o.current_month) ? `企宽开通${num(o.current_month)}条` : '企宽开通量待补充', options: {color: '0070C0'}},
    ...colored(`，同比（较${String(year - 1).slice(2)}年${month}月）`, o.yoy, '。'),
    {text: citySummary(Q.opening.cities, 'yoy') + '\n'},
    {text: `1-${month}月`}, {text: valid(o.current_ytd) ? `累计开通${num(o.current_ytd)}条` : '累计开通量待补充', options: {color: '0070C0'}},
    ...colored('，累计同比', o.ytd_yoy, '。'),
    {text: citySummary(Q.opening.cities, 'ytd_yoy')},
  ], .3, 3.9, 12.65, .82, {bold: true, fontSize: 13});
  const openingLabels = [yearAgo, short, `${String(year - 1).slice(2)}.01-${String(month).padStart(2, '0')}`,
    `${String(year).slice(2)}.01-${String(month).padStart(2, '0')}`];
  const counts = [o.previous_month, o.current_month, o.previous_ytd, o.current_ytd];
  chart([{name: '企宽开通量', labels: openingLabels.map((v, i) => label(v, counts[i])), values: counts}],
    {x: .42, y: 5.35, w: 4.0, h: 1.58});
  chart([{name: '开通量同比', labels: cities, values: Q.opening.cities.map(r => r.yoy)},
    {name: '累计开通量同比', labels: cities, values: Q.opening.cities.map(r => r.ytd_yoy)}],
    {x: 4.95, y: 5.26, w: 7.85, h: 1.72}, true);
  if (process.env.PPT_TEMPLATE_MASTER !== '1')
    text(String(page), 12.6, 7.2, .3, .18, {fontSize: 8, align: 'right', color: '75C900'});
  slide.addNotes('企宽存量：手工Excel已计算结果。企宽开通量：已计算的有数报结结果。缺失值不替换为0。\n' +
    JSON.stringify({stock: Q.stock.source, opening: Q.opening.source}));
  return slide;
}

function addQikuanOpeningTrendSlide(pptx, Q, helpers, page = 8) {
  const slide = pptx.addSlide();
  helpers.addTemplateBackground(slide);
  const text = (value, x, y, w, h, extra = {}) => slide.addText(value, {
    x, y, w, h, fontFace: 'Microsoft YaHei', fontSize: 13, color: INK, margin: 0, ...extra,
  });
  text('业务存量及发展量-企宽业务', .22, .14, 10.5, .45,
    {fontSize: 28, bold: true, color: 'FFFFFF'});
  const trend = Q.opening.trend || {months: [], values: [], total: null, average: null};
  const months = trend.months || [];
  const values = trend.values || [];
  const complete = months.length === 12 && values.length === 12 && values.every(valid);
  const fullMonth = value => { const [year, month] = value.split('-'); return `${year}年${Number(month)}月`; };
  const period = months.length ? `${fullMonth(months[0])}-${fullMonth(months[months.length - 1])}` : '近12个月';
  text([
    {text: period + '，企宽'},
    {text: complete ? `累计开通${num(trend.total)}条` : '累计开通量待补充', options: {color: '0070C0'}},
    {text: '，'},
    {text: complete ? `平均月开通${Math.round(trend.average)}条` : '平均月开通量待补充', options: {color: complete ? '0070C0' : '777777'}},
    {text: '。'},
  ], .42, .82, 12.2, .42, {fontSize: 14, bold: true});
  helpers.addPanel(slide, .55, 1.52, 12.22, 5.45);
  helpers.addSectionPill(slide, '企宽开通量', 4.55, 1.28, 4.2);
  if (complete) {
    const labels = months.map(value => value.slice(2).replace('-', '.'));
    const max = Math.max(...values);
    slide.addChart(pptx.ChartType.bar, [{name: '企宽开通量', labels, values}], {
      x: .78, y: 1.78, w: 11.75, h: 4.82,
      catAxisLabelFontFace: 'Microsoft YaHei', catAxisLabelFontSize: 10,
      catAxisLabelColor: '666666', catAxisLineColor: 'D9DEE5', catAxisLabelPos: 'low',
      valAxisMinVal: 0, valAxisMaxVal: max * 1.22, valAxisLabelPos: 'none',
      valAxisLineShow: false, valAxisMajorTickMark: 'none',
      valGridLine: {color: 'FFFFFF', transparency: 100}, showLegend: false,
      showValue: true, showTitle: false, dataLabelPosition: 'outEnd',
      dataLabelColor: '555555', dataLabelFontFace: 'Microsoft YaHei', dataLabelFontSize: 9,
      dataLabelFormatCode: '0', chartColors: [BLUE], gapWidthPct: 72, showBorder: false,
    });
  } else {
    text('近12个月企宽开通量待补充', 1.0, 3.7, 11.3, .5,
      {fontSize: 18, color: '888888', align: 'center'});
  }
  if (process.env.PPT_TEMPLATE_MASTER !== '1')
    text(String(page), 12.6, 7.2, .3, .18, {fontSize: 8, align: 'right', color: '75C900'});
  slide.addNotes('企宽开通量近12个月趋势：数据库中有数装机报结量月度成功快照，按11地市合计。缺失月份不替换为0。\n' +
    JSON.stringify({opening: Q.opening.source, trendMonths: months}));
  return slide;
}
module.exports = {addQikuanBusinessSlide, addQikuanOpeningTrendSlide, rate, citySummary};

if (require.main === module) {
  const pptxgen = require('pptxgenjs');
  const fs = require('fs'), path = require('path');
  const data = JSON.parse(fs.readFileSync(process.argv[2], 'utf8'));
  const deck = new pptxgen();
  deck.layout = 'LAYOUT_WIDE';
  deck.theme = {headFontFace: 'Microsoft YaHei', bodyFontFace: 'Microsoft YaHei', lang: 'zh-CN'};
  const helpers = {
    addTemplateBackground(slide) {
      if (process.env.PPT_TEMPLATE_MASTER !== '1')
        slide.addImage({path: path.join(__dirname, 'templates/template_background_image1.jpeg'),
          x: 0, y: 0, w: 13.333333, h: 7.5});
    },
    addPanel(slide, x, y, w, h) {
      slide.addShape(deck.ShapeType.rect, {x, y, w, h, fill: {color: 'FFFFFF'}, line: {color: 'D9DEE5', width: .6}});
    },
    addSectionPill(slide, title, x, y, w) {
      slide.addShape(deck.ShapeType.roundRect, {x, y, w, h: .28, radius: .05,
        fill: {color: '0086D1'}, line: {color: '0086D1'}});
      slide.addText(title, {x, y: y + .015, w, h: .24, fontFace: 'Microsoft YaHei',
        fontSize: 12.5, bold: true, color: 'FFFFFF', align: 'center', margin: 0});
    },
  };
  addQikuanBusinessSlide(deck, data.qikuanBusiness, helpers);
  addQikuanOpeningTrendSlide(deck, data.qikuanBusiness, helpers);
  deck.writeFile({fileName: process.argv[3]}).catch(error => {console.error(error); process.exitCode = 1;});
}
