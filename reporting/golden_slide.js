// 可编辑点金指标表，数据来自整周期全省快照。
function addGoldenSlide(pptx, data, helpers) {
  const slide=pptx.addSlide();
  helpers.addTemplateBackground(slide);
  const font='Microsoft YaHei';
  slide.addText('业务情况-点金行动指标达成情况',{x:.28,y:.14,w:10.5,h:.4,fontFace:font,fontSize:25,bold:true,color:'FFFFFF',margin:0});
  const x=.45,y=.96,w=12.43,rowH=.405;
  const months=data.months;
  const widths=[1.6,2.35,1.05,...months.map(()=> (w-5)/months.length)];
  function cell(text,c,r,color='000000',height=rowH){
    const cx=x+widths.slice(0,c).reduce((a,b)=>a+b,0);
    slide.addShape(pptx.ShapeType.rect,{x:cx,y:y+r*rowH,w:widths[c],h:height,line:{color:'000000',width:.6},fill:{color:'FFFFFF'}});
    slide.addText(text,{x:cx+.02,y:y+r*rowH+.02,w:widths[c]-.04,h:height-.04,fontFace:font,fontSize:months.length>10?8:9,align:'center',valign:'mid',margin:0,color});
  }
  ['场景名称','场景成效指标','目标值',...months.map(m=>`${m.slice(0,4)}年${Number(m.slice(5))}月`)].forEach((t,c)=>cell(t,c,0));
  data.groups.forEach((g,gi)=>{
    cell(g.title,0,1+gi*4,'000000',4*rowH);
    g.metrics.forEach((metric,mi)=>{
      const r=1+gi*4+mi;
      cell(metric.label,1,r);cell(metric.target,2,r);
      metric.values.forEach((v,i)=>cell(v==null?'—':metric.hours?v.toFixed(2):`${Number(v.toFixed(2))}%`,i+3,r,metric.failed[i]?'C00000':'000000'));
    });
  });
  slide.addText('注：取数范围按集团考核口径，如9月为8月26日—9月25日。\n取值口径：编排系统—数据管理—点金行动报表，全省；缺失数据为“—”，红色表示未达目标。',{x:.6,y:6.55,w:12,h:.48,fontFace:font,fontSize:9,margin:0});
  slide.addText('9',{x:12.65,y:7.18,w:.28,h:.18,fontFace:font,fontSize:8,margin:0});
  return slide;
}
module.exports={addGoldenSlide};
