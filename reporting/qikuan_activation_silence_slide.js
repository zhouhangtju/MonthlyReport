// Native PowerPoint shapes keep the three ranking charts editable.
const BLUE = '4F81BD';
const INK = '252525';
const RED = 'E33B3B';

function addQikuanActivationSilenceSlide(pptx, data, helpers, page) {
  const slide = pptx.addSlide();
  helpers.addTemplateBackground(slide);
  const text = (value, x, y, w, h, opts = {}) => slide.addText(value, {
    x, y, w, h, fontFace: 'Microsoft YaHei', fontSize: 13, color: INK,
    margin: 0, breakLine: false, ...opts,
  });
  text('业务情况-企宽业务激活即沉默', .22, .14, 10.4, .45,
    {fontSize: 28, bold: true, color: 'FFFFFF'});
  if (!data?.available) {
    text(`${data?.month || ''}企宽激活即沉默指标尚未计算`, .5, 2.8, 12.3, .6,
      {fontSize: 22, align: 'center', color: '777777'});
  } else {
    const percent = value => `${(value * 100).toFixed(2)}%`;
    const top = names => names.length ? names.join('、') : '暂无';
    const monthNo = Number(data.month.slice(5));
    const title1 = [
      {text: `•  ${monthNo}月全省企宽激活即沉默占比${percent(data.province.rate)}，`},
      {text: top(data.cityTopNames), options: {color: RED}},
      {text: '较高。'},
    ];
    text(title1, .39, .83, 12.5, .34, {fontSize: 14});
    helpers.addPanel(slide, .36, 1.27, 12.62, 2.5);
    helpers.addSectionPill(slide, '企宽激活即沉默占比', 4.88, 1.13, 3.5);

    const cities = data.cities;
    const maxRate = Math.max(.01, ...cities.map(row => row.rate));
    const barBase = 3.42;
    const chartLeft = .73;
    const chartWidth = 11.95;
    const step = chartWidth / cities.length;
    slide.addShape(pptx.ShapeType.line, {x: chartLeft, y: barBase, w: chartWidth, h: 0,
      line: {color: 'D9DEE5', width: .8}});
    cities.forEach((row, index) => {
      const height = Math.max(.015, 1.42 * row.rate / maxRate);
      const x = chartLeft + step * (index + .5) - .18;
      slide.addShape(pptx.ShapeType.rect, {x, y: barBase - height, w: .36, h: height,
        line: {color: BLUE, transparency: 100}, fill: {color: BLUE}});
      text(percent(row.rate), x - .2, barBase - height - .25, .76, .2,
        {fontSize: 10, align: 'center'});
      text(row.city, chartLeft + index * step, barBase + .11, step, .18,
        {fontSize: 10, color: '666666', align: 'center'});
    });

    const title2 = [
      {text: '•  企宽激活即沉默最高的区县为'},
      {text: top(data.districtTopNames), options: {color: RED}},
      {text: '，网格为'},
      {text: top(data.gridTopNames), options: {color: RED}},
      {text: '。'},
    ];
    text(title2, .39, 3.9, 12.6, .33, {fontSize: 13});
    helpers.addPanel(slide, .36, 4.29, 12.62, 2.58);
    slide.addShape(pptx.ShapeType.line, {x: 6.67, y: 4.29, w: 0, h: 2.58,
      line: {color: 'D9DEE5', width: .8}});
    text('■ 激活即沉默占比 TOP10 区县', .85, 4.42, 5.3, .23,
      {fontSize: 11, color: BLUE, align: 'center'});
    text('■ 激活即沉默占比 TOP10 网格', 7.15, 4.42, 5.3, .23,
      {fontSize: 11, color: BLUE, align: 'center'});

    function horizontal(rows, x, width) {
      const largest = Math.max(.01, ...rows.map(row => row.rate));
      rows.forEach((row, index) => {
        const y = 4.73 + index * .204;
        text(row.label, x, y, 1.43, .18, {fontSize: 9, color: '666666', align: 'right'});
        const length = Math.max(.01, (width - 2.24) * row.rate / largest);
        slide.addShape(pptx.ShapeType.rect, {x: x + 1.53, y: y + .025,
          w: length, h: .12, line: {color: BLUE, transparency: 100}, fill: {color: BLUE}});
        text(percent(row.rate), x + 1.62 + length, y, .62, .18, {fontSize: 9});
      });
    }
    horizontal(data.districtTop, .39, 6.08);
    horizontal(data.gridTop, 6.7, 6.08);
    text(`注：${monthNo}月手工沉默清单工单号与T-3（${data.denominatorMonth || '未注明'}）全量企宽工单id匹配数／该月全量企宽工单数；网格排名仅统计分母≥5单。`,
      .4, 7.08, 12.25, .19, {fontSize: 8.2});
  }
  text(String(page), 12.58, 7.18, .35, .18,
    {fontSize: 8, color: '6B7280', align: 'right'});
  slide.addNotes(`企宽激活即沉默；数据来自数据库成功计算批次：${data?.source || '缺失'}。`);
}

module.exports = {addQikuanActivationSilenceSlide};
