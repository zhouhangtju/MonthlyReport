'use strict';

function addTerminalReuseSlide(pptx, data, background, page = 29) {
  const slide = pptx.addSlide();
  background(slide);
  const font = 'Microsoft YaHei';
  const text = (value, box, options = {}) => slide.addText(value, {
    ...box, fontFace: font, fontSize: 12, color: '163F78', margin: 0,
    breakLine: false, ...options,
  });
  const num = value => String(Number(value));
  const percent = value => value == null ? '暂无数据' : `${(100 * value).toFixed(2)}%`;
  text('各业务旧终端耗用与利旧情况（一）', {x:.28,y:.14,w:12.5,h:.48}, {fontSize:27,bold:true,color:'FFFFFF'});
  if (!data) {
    text('该月终端利旧指标尚未计算入库', {x:.5,y:1.6,w:12,h:1}, {fontSize:22});
    return slide;
  }
  const month = Number(data.report_month.slice(5));
  const all = data.overall_consumption, utilization = data.overall_utilization;
  const onu = data.onu_consumption, onuUtil = data.onu_utilization;
  text('每装机工单旧终端耗用占比与旧终端利用率', {x:.38,y:.85,w:12,h:.28}, {fontSize:14,bold:true,color:'111111'});
  text(`${month}月利旧设备${num(all.numerator)}台，装机出库${num(all.denominator)}台，每装机工单旧终端耗用占比${percent(all.rate)}。截至${month}月底旧终端可利旧库存总数${num(utilization.denominator)}台，旧终端利用率${percent(utilization.rate)}。`,
    {x:.4,y:1.16,w:12.5,h:.34}, {fontSize:12});
  text('按设备类型情况分析', {x:.4,y:1.55,w:12,h:.25}, {fontSize:12,bold:true,color:'111111'});
  text([
    {text:'ONU情况：',options:{bold:true,color:'111111'}},
    {text:`${month}月ONU利旧设备${num(onu.numerator)}台，ONU装机出库${num(onu.denominator)}台，每装机工单旧终端耗用占比${percent(onu.rate)}；截至${month}月底ONU旧终端库存${num(onuUtil.denominator)}台，旧终端利用率${percent(onuUtil.rate)}。ONU每装机工单旧终端耗用占比较差地市有`},
    {text:data.low_onu_cities.join('、'),options:{color:'C84343'}},
    {text:'，但实际库存旧终端数充足。'},
  ], {x:.4,y:1.86,w:12.5,h:.62}, {fontSize:12});
  function chart(key, title, x, y) {
    const rows = data.charts[key];
    const scale = 1.025;
    const visualScale = 1.15;
    const box = {x,y,w:6.23*scale,h:1.98*scale};
    slide.addShape(pptx.ShapeType.rect, {...box,line:{color:'D5D5D5',width:.7},fill:{color:'FFFFFF',transparency:100}});
    text(title, {x:x+.06*scale,y:y+.08*scale,w:6.11*scale,h:.22*scale}, {fontSize:11*visualScale,bold:true,color:'555555',align:'center'});
    const labels = rows.map(r=>r.city);
    const utilization = key === 'ONU利用率';
    slide.addChart([
      {type:pptx.ChartType.bar, data:[
        {name:'ONU利旧数',labels,values:rows.map(r=>r.numerator)},
        {name:utilization?'ONU可利旧库存':'ONU装机出库数',labels,values:rows.map(r=>r.denominator)},
      ],options:{barDir:'col',grouping:'clustered',gapWidthPct:80,chartColors:['4F81BD','F79646'],showValue:true,dataLabelPosition:'outEnd',dataLabelFormatCode:'0',dataLabelColor:'4F81BD',dataLabelFontSize:7*visualScale}},
      {type:pptx.ChartType.line,data:[{name:utilization?'旧终端利用率':'旧终端耗用占比',labels,values:rows.map(r=>r.rate)}],
        options:{chartColors:['C84343'],secondaryValAxis:true,secondaryCatAxis:true,showValue:true,dataLabelPosition:'t',dataLabelFormatCode:'0.00%',dataLabelColor:'C84343',dataLabelFontSize:7*visualScale,lineSize:1.5*visualScale,showMarker:true,markerSize:2,lineDataSymbol:'circle',lineDataSymbolSize:3,lineDataSymbolFillColor:'FFFFFF',lineDataSymbolLineColor:'C84343',lineDataSymbolLineSize:.8}},
    ], {
      x:x+.12*scale,y:y+.35*scale,w:5.99*scale,h:1.57*scale,
      catAxisLabelFontFace:font,catAxisLabelFontSize:7.5*visualScale,catAxisLineColor:'CCCCCC',
      catAxes:[{}, {catAxisLabelPos:'none',catAxisLineColor:'FFFFFF'}],
      valAxes:[{valAxisMinVal:0,valAxisMaxVal:Math.max(1,...rows.map(r=>Math.max(r.numerator,r.denominator)))*1.8,valAxisLabelPos:'none',valAxisLineShow:false,valGridLine:{color:'FFFFFF',transparency:100}},
        {valAxisMinVal:0,valAxisMaxVal:Math.max(1.05,...rows.map(r=>r.rate || 0))*1.65,valAxisLabelPos:'none',valAxisLineShow:false,valGridLine:{color:'FFFFFF',transparency:100}}],
      chartColors:['4F81BD','F79646','C84343'],showLegend:true,legendPos:'t',legendFontSize:7*visualScale,legendFontFace:font,
      showBorder:false,showCatName:false,showTitle:false,
    });

  }
  chart('MPLS VPN专线','MPLS-VPN每装机工单旧终端耗用占比',.22,2.58);
  chart('互联网专线','互联网每装机工单旧终端耗用占比',6.64,2.58);
  chart('视频监控','视频监控ONU每装机工单旧终端耗用占比',.22,4.64);
  chart('ONU利用率','ONU旧终端利用率',6.64,4.64);
  text('注：利旧数=返修有SN+回收有SN；耗用占比=利旧数/装机出库数；利用率=当月利旧数/月底可利旧库存。库存剔除不可利旧型号，比例不封顶。',
    {x:.4,y:6.90,w:12.4,h:.21},{fontSize:7.5,color:'555555'});
  text(String(page),{x:12.55,y:7.18,w:.35,h:.18},{fontSize:8,color:'777777',align:'right'});
  slide.addNotes(JSON.stringify({report_month:data.report_month,metric_run_id:data.metric_run_id,sources:data.sources,rules:data.rules},null,2));
  return slide;
}


function addTerminalReuseDeviceSlides(pptx,data,background,page=30) {
  const num=v=>String(Number(v));
  const percent=v=>v==null?'暂无数据':`${(v*100).toFixed(2)}%`;
  for (const [index,devices] of [['摄像头','WIFI路由器'],['FTTO','专线卫士']].entries()) {
    const slide=pptx.addSlide(); background(slide);
    const font='Microsoft YaHei';
    const text=(v,box,opts={})=>slide.addText(v,{...box,fontFace:font,fontSize:12,color:'163F78',margin:0,...opts});
    text(`各业务旧终端耗用与利旧情况（${index===0?'二':'三'}）`,{x:.28,y:.14,w:12.5,h:.48},{fontSize:27,bold:true,color:'FFFFFF'});
    if (!data || !data.devices) {text('该月设备利旧指标尚未计算入库',{x:.4,y:1,w:12,h:.5});continue;}
    const month=Number(data.report_month.slice(5));
  function chart(rows, title, device, utilization, x, y) {
    const scale = 1.025;
    const visualScale = 1.15;
    const box = {x,y,w:6.23*scale,h:2.12*scale};
    slide.addShape(pptx.ShapeType.rect, {...box,line:{color:'D5D5D5',width:.7},fill:{color:'FFFFFF',transparency:100}});
    text(title, {x:x+.06*scale,y:y+.08*scale,w:6.11*scale,h:.22*scale}, {fontSize:11*visualScale,bold:true,color:'555555',align:'center'});
    const labels = rows.map(r=>r.city);
    slide.addChart([
      {type:pptx.ChartType.bar, data:[
        {name:device+'利旧数',labels,values:rows.map(r=>r.numerator)},
        {name:utilization?device+'库存旧终端数':device+'装机出库总数',labels,values:rows.map(r=>r.denominator)},
      ],options:{barDir:'col',grouping:'clustered',gapWidthPct:80,chartColors:['4F81BD','F79646'],showValue:true,dataLabelPosition:'outEnd',dataLabelFormatCode:'0',dataLabelColor:'4F81BD',dataLabelFontSize:7*visualScale}},
      {type:pptx.ChartType.line,data:[{name:utilization?'旧终端利用率':'旧终端耗用占比',labels,values:rows.map(r=>r.rate)}],
        options:{chartColors:['C84343'],secondaryValAxis:true,secondaryCatAxis:true,showValue:true,dataLabelPosition:'t',dataLabelFormatCode:'0.00%',dataLabelColor:'C84343',dataLabelFontSize:7*visualScale,lineSize:1.5*visualScale,showMarker:true,markerSize:2,lineDataSymbol:'circle',lineDataSymbolSize:3,lineDataSymbolFillColor:'FFFFFF',lineDataSymbolLineColor:'C84343',lineDataSymbolLineSize:.8}},
    ], {
      x:x+.12*scale,y:y+.35*scale,w:5.99*scale,h:1.71*scale,
      catAxisLabelFontFace:font,catAxisLabelFontSize:7.5*visualScale,catAxisLineColor:'CCCCCC',
      catAxes:[{}, {catAxisLabelPos:'none',catAxisLineColor:'FFFFFF'}],
      valAxes:[{valAxisMinVal:0,valAxisMaxVal:Math.max(1,...rows.map(r=>Math.max(r.numerator,r.denominator)))*1.8,valAxisLabelPos:'none',valAxisLineShow:false,valGridLine:{color:'FFFFFF',transparency:100}},
        {valAxisMinVal:0,valAxisMaxVal:Math.max(1.05,...rows.map(r=>r.rate || 0))*1.65,valAxisLabelPos:'none',valAxisLineShow:false,valGridLine:{color:'FFFFFF',transparency:100}}],
      chartColors:['4F81BD','F79646','C84343'],showLegend:true,legendPos:'t',legendFontSize:7*visualScale,legendFontFace:font,
      showBorder:false,showCatName:false,showTitle:false,
    });

  }

    devices.forEach((device,i)=>{
      const item=data.devices[device], c=item.consumption,u=item.utilization;
      const label={摄像头:'摄像头情况：',WIFI路由器:'WIFI路由器情况：',FTTO:'FTTO设备情况：',专线卫士:'专线卫士设备情况：'}[device];
      const first=device==='WIFI路由器'?'路由器':device;
      const prefix=device==='摄像头'?'摄像头':device==='WIFI路由器'?'WIFI路由器':device+'设备';
      text([
        {text:label,options:{bold:true,color:'000000'}},
        {text:`${month}月${first}利旧设备${num(c.numerator)}台，${device}装机出库${num(c.denominator)}台，每装机工单旧终端耗用占比${percent(c.rate)}；截至${month}月底${device}旧终端库存${num(u.denominator)}台，旧终端利用率${percent(u.rate)}。${prefix}每装机工单旧终端耗用占比较差地市有`},
        {text:item.low_cities.join('、'),options:{color:'C84343'}},
        {text:device==='摄像头'?'。':'，但实际库存旧终端数充足。'}
      ],{x:.22,y:i===0?.86:3.90,w:12.86,h:.57},{fontSize:12});
      const y=i===0?1.47:4.52;
      const title=device==='摄像头'?'摄像头每装机工单旧终端耗用占比':`服务类${device}每装机工单旧终端耗用占比`;
      chart(item.consumption_chart,title,device,false,.22,y);
      chart(item.utilization_chart,device+'旧终端利用率',device,true,6.64,y);
    });
    text(String(page+index),{x:12.55,y:7.18,w:.35,h:.18},{fontSize:8,color:'777777',align:'right'});
    slide.addNotes(JSON.stringify({metric_run_id:data.metric_run_id,sources:data.sources,rules:data.rules,scope:'正文全部业务；耗用图按指定业务；库存充足为参考页固定描述，未作需求覆盖验证'},null,2));
  }
}

module.exports = {addTerminalReuseSlide,addTerminalReuseDeviceSlides};

function addCumulativeTerminalReuseSlide(p,d,background,page=29){const s=p.addSlide();background(s);if(!d){s.addText('累计终端利旧指标尚未计算入库',{x:.5,y:1,w:12,h:.5,fontSize:12});return s;}const startText='24年6月',endText=String(d.period[1]).slice(2,4)+'年'+Number(String(d.period[1]).slice(5))+'月';
const txt=(v,x,y,w,h,o={})=>s.addText(v,{x,y,w,h,fontFace:'Microsoft YaHei',fontSize:12,color:'163F78',margin:0,...o});const pct=v=>(v*100).toFixed(2)+'%';const c=d.summary.city,q=d.summary.county;
txt('终端利旧情况',.27,.15,12,.48,{fontSize:27,bold:true,color:'FFFFFF'});s.addShape(p.ShapeType.rect,{x:.35,y:.86,w:.12,h:.12,line:{color:'111111',width:1.5},fill:{color:'FFFFFF'}});txt('累计终端利旧数',.64,.81,12,.29,{fontSize:14,bold:true,color:'000000'});
const low=(key)=>d.city.slice().sort((a,b)=>a[key]-b[key]).slice(0,3).map(x=>x.label).join('、');
const rich=[
{text:`${startText}至${endText}全省装机工单终端总数${c.outbound}台，其中装机利旧终端耗用数${c.reuse}台，累计每装机工单旧终端耗用占比为${pct(c.consumption)}，`},
{text:low('consumption'),options:{color:'C84343'}},{text:'靠后。\n'},
{text:`24年5月全省库存已有旧终端数${(c.opening_stock/10000).toFixed(2)}万台，${startText}至${endText}全省拆回终端数${(c.utilization_denominator/10000).toFixed(2)}万台，其中利旧终端数${c.reuse}台，截至${endText}累计旧终端利用率为${pct(c.utilization)}，`},
{text:low('utilization'),options:{color:'C84343'}},{text:'靠后。'}];
txt(rich,.62,1.10,12.25,.76);
const r=d.city_chart,labels=r.map(x=>x.label);
const panel=(x,y,w,h)=>s.addShape(p.ShapeType.rect,{x,y,w,h,line:{color:'D5D5D5',width:.7},fill:{color:'FFFFFF',transparency:100}});
panel(.28,1.94,12.82,2.40);
txt('终端利旧情况',5.65,2.05,2,.25,{bold:true,color:'595959',align:'center',fontSize:12});
s.addShape(p.ShapeType.rect,{x:8.0,y:2.10,w:.28,h:.08,line:{color:'4F81BD',transparency:100},fill:{color:'4F81BD'}});txt('利旧数',8.31,2.04,.43,.22,{fontSize:9,color:'595959'});
function lineLegend(x,width,color,label){s.addShape(p.ShapeType.line,{x,y:2.14,w:.28,h:0,line:{color,width:1.2}});s.addShape(p.ShapeType.ellipse,{x:x+.115,y:2.11,w:.06,h:.06,line:{color,width:1},fill:{color:'FFFFFF'}});txt(label,x+.32,2.04,width,.22,{fontSize:9,color:'595959'});}
lineLegend(8.75,1.55,'C84343',`截至${endText}旧终端利用率`);lineLegend(10.65,2.1,'F79646','每装机工单旧终端耗用占比');

s.addChart([{type:p.ChartType.bar,data:[{name:'利旧数',labels,values:r.map(x=>x.reuse)}],options:{chartColors:['4F81BD'],showValue:true,dataLabelPosition:'outEnd',dataLabelFontSize:9,dataLabelColor:'4F81BD'}},{type:p.ChartType.line,data:[{name:`截至${endText}旧终端利用率`,labels,values:r.map(x=>x.utilization)},{name:'每装机工单旧终端耗用占比',labels,values:r.map(x=>x.consumption)}],options:{secondaryValAxis:true,secondaryCatAxis:true,chartColors:['C84343','F79646'],showValue:true,dataLabelFormatCode:'0.00%',dataLabelPosition:'t',dataLabelFontSize:9,lineSize:1.5,lineDataSymbol:'circle',lineDataSymbolSize:3}}],{x:.42,y:2.38,w:12.52,h:1.86,showLegend:false,legendPos:'t',legendFontSize:9,showTitle:false,title:'终端利旧情况',titleFontSize:12,catAxisLabelFontSize:10,valAxes:[{valAxisMinVal:0,valAxisMaxVal:65000,valAxisLabelPos:'none',valAxisLineShow:false,valGridLine:{color:'FFFFFF',transparency:100}},{valAxisMinVal:0,valAxisMaxVal:1.6,valAxisLabelPos:'none',valAxisLineShow:false,valGridLine:{color:'FFFFFF',transparency:100}}],catAxes:[{},{catAxisLabelPos:'none'}],showBorder:false});
s.addShape(p.ShapeType.rect,{x:.35,y:4.48,w:.12,h:.12,line:{color:'111111',width:1.5},fill:{color:'FFFFFF'}});txt('累计终端利旧数（区县）',.64,4.43,12,.29,{fontSize:14,bold:true,color:'000000'});
txt([{text:`${startText}至${endText}，累计每装机工单旧终端耗用占比${pct(q.consumption)}，`},{text:d.county_consumption_bottom10.slice(0,3).map(x=>x.label).join('、'),options:{color:'C84343'}},{text:`靠后；累计旧终端利用率${pct(q.utilization)}，`},{text:d.county_utilization_bottom10.slice(0,3).map(x=>x.label).join('、'),options:{color:'C84343'}},{text:'靠后。'}],.57,4.72,12.4,.34);
for(const [i,key,title,field] of [[0,'county_consumption_bottom10','每装机工单旧终端耗用占比低（后10县区）','consumption'],[1,'county_utilization_bottom10','旧终端利用率（后10区县）','utilization']]){let rs=d[key];panel(.28+i*6.41,5.02,6.41,1.96);txt(title,.43+i*6.41,5.12,6.11,.25,{fontSize:12,bold:true,color:'000000',align:'center'});s.addChart(p.ChartType.bar,[{name:title,labels:rs.map(x=>x.label),values:rs.map(x=>x[field])}],{x:.43+i*6.41,y:5.52,w:6.11,h:1.38,barDir:'col',chartColors:['4F81BD'],showValue:true,dataLabelPosition:'outEnd',dataLabelFormatCode:'0.00%',dataLabelColor:'4F81BD',dataLabelFontSize:9,catAxisLabelFontSize:9,valAxisMinVal:0,valAxisMaxVal:.40,valAxisLabelPos:'none',valAxisLineShow:false,valGridLine:{color:'FFFFFF',transparency:100},showLegend:false,showTitle:false,title,titleFontSize:12,showBorder:false});}
txt(`注：上文累计拆回终端数含2024年5月期初库存。每装机工单旧终端耗用占比=累计装机利旧数/累计装机终端总数；\n    截至${endText}累计终端利旧率=${startText}至${endText}装机终端利旧数/（${startText}至${endText}拆回终端数+截至24年5月库存回收设备数）。`,.28,7.04,12.65,.32,{fontSize:8,color:'000000'});txt(String(page),12.78,7.27,.35,.20,{fontSize:12,bold:true,color:'97B953',align:'right'});s.addNotes(JSON.stringify(d));return s;
}
module.exports.addCumulativeTerminalReuseSlide=addCumulativeTerminalReuseSlide;
