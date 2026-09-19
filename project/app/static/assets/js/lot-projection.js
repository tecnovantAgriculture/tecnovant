(function(){
"use strict";
const metrics=[
 {key:"ndvi",label:"NDVI"},{key:"protein",label:"Proteína (%)"},
 {key:"vari",label:"VARI",advanced:true},{key:"nbi",label:"NBI",advanced:true},
 {key:"gli",label:"GLI",advanced:true},{key:"ngrdi",label:"NGRDI",advanced:true},{key:"exg",label:"ExG",advanced:true}
];
const colors=["#2563eb","#ef4444","#059669","#7c3aed","#ea580c","#0891b2","#65a30d","#db2777"];
function number(value){if(value===null||value===undefined||value==="")return null;const parsed=Number(value);return Number.isFinite(parsed)?parsed:null}
function esc(value){return String(value==null?"":value).replace(/[&<>'"]/g,char=>({"&":"&amp;","<":"&lt;",">":"&gt;","'":"&#39;",'"':"&quot;"}[char]))}
function lotKey(row){return String(row.lot_id!=null?row.lot_id:(row.lot_name||"Lote"))}
function csrf(){const match=document.cookie.match(/(?:^|;\s*)csrf_access_token=([^;]+)/);return match?decodeURIComponent(match[1]):""}
function lotGroups(rows){const groups=new Map();rows.forEach(row=>{const key=lotKey(row);if(!groups.has(key))groups.set(key,{key,name:row.lot_name||"Lote",rows:[]});groups.get(key).rows.push(row)});return Array.from(groups.values())}
function pointsFor(rows,key){return rows.map(row=>({x:number(row.rest_days),y:number(row[key]),lot:row.lot_name||"Lote",date:row.common_analysis_date||row.orthophoto_name||""})).filter(point=>point.x!==null&&point.y!==null)}
function solve(matrix,values){
 const n=values.length,a=matrix.map((row,index)=>row.slice().concat(values[index]));
 for(let col=0;col<n;col++){let pivot=col;for(let row=col+1;row<n;row++)if(Math.abs(a[row][col])>Math.abs(a[pivot][col]))pivot=row;if(Math.abs(a[pivot][col])<1e-12)return null;[a[col],a[pivot]]=[a[pivot],a[col]];const divisor=a[col][col];for(let j=col;j<=n;j++)a[col][j]/=divisor;for(let row=0;row<n;row++){if(row===col)continue;const factor=a[row][col];for(let j=col;j<=n;j++)a[row][j]-=factor*a[col][j]}}
 return a.map(row=>row[n]);
}
function polynomialRegression(points){
 const uniqueX=new Set(points.map(point=>point.x));if(points.length<4||uniqueX.size<4)return null;
 const degree=3,sums=[];for(let power=0;power<=degree*2;power++)sums[power]=points.reduce((sum,point)=>sum+Math.pow(point.x,power),0);
 const matrix=[];for(let row=0;row<=degree;row++){matrix[row]=[];for(let col=0;col<=degree;col++)matrix[row][col]=sums[row+col]}
 const values=[];for(let power=0;power<=degree;power++)values[power]=points.reduce((sum,point)=>sum+point.y*Math.pow(point.x,power),0);
 const coefficients=solve(matrix,values);if(!coefficients)return null;
 const predict=x=>coefficients.reduce((sum,value,power)=>sum+value*Math.pow(x,power),0),mean=points.reduce((sum,p)=>sum+p.y,0)/points.length;
 const residual=points.reduce((sum,p)=>sum+Math.pow(p.y-predict(p.x),2),0),total=points.reduce((sum,p)=>sum+Math.pow(p.y-mean,2),0),r2=total>0?1-residual/total:1;
 return {coefficients,predict,r2};
}
function equation(model){
 if(!model)return "";const c=model.coefficients,term=(value,label,index)=>{const absolute=Math.abs(value).toPrecision(3);return (index?value>=0?" + ":" - ":value<0?"-":"")+absolute+label};
 return "y = "+term(c[3],"x³",0)+term(c[2],"x²",1)+term(c[1],"x",2)+term(c[0],"",3);
}
function evolutionSummary(points,metric){
 const ordered=points.slice().sort((a,b)=>a.x-b.x);if(!ordered.length)return "Sin datos válidos.";
 const maximum=ordered.reduce((best,p)=>p.y>best.y?p:best),minimum=ordered.reduce((best,p)=>p.y<best.y?p:best);
 if(ordered.length===1)return "Solo hay un análisis graficable: día "+ordered[0].x+", "+metric.label+" "+ordered[0].y+".";
 const changes=[];for(let i=1;i<ordered.length;i++){const previous=ordered[i-1],current=ordered[i],difference=current.y-previous.y,direction=difference>0?"subió":difference<0?"bajó":"se mantuvo";changes.push("del día "+previous.x+" al "+current.x+" "+direction+(difference?" "+Math.abs(difference).toFixed(2):""))}
 return "Máximo en el día "+maximum.x+" ("+maximum.y+"). Mínimo en el día "+minimum.x+" ("+minimum.y+"). "+changes.join("; ")+".";
}
function chart(metric,rows){
 const groups=lotGroups(rows).map((group,index)=>({...group,color:colors[index%colors.length],points:pointsFor(group.rows,metric.key)})).filter(group=>group.points.length);
 const points=groups.flatMap(group=>group.points),width=800,height=360,left=82,right=28,top=28,bottom=56,plotW=width-left-right,plotH=height-top-bottom;
 if(!points.length)return '<div class="rounded-xl border bg-white p-8 text-center text-sm text-gray-500">Los lotes seleccionados no tienen datos para '+esc(metric.label)+'.</div>';
 let minX=0,maxX=Math.max(10,Math.ceil(Math.max(...points.map(p=>p.x))/10)*10),minY=Math.min(...points.map(p=>p.y)),maxY=Math.max(...points.map(p=>p.y)); const zeroBased=metric.key==="protein"||metric.key==="ndvi"||metric.key.indexOf("nutrient_")===0; if(zeroBased){minY=0;if(metric.key==="ndvi"){maxY=Math.max(1,Math.ceil(maxY*10)/10)}else{const raw=Math.max(maxY*1.15,1),power=Math.pow(10,Math.floor(Math.log10(raw))),scaled=raw/power,nice=scaled<=1?1:scaled<=2?2:scaled<=5?5:10;maxY=nice*power}}else if(minY===maxY){const pad=Math.abs(minY)*.1||1;minY-=pad;maxY+=pad}else{const pad=(maxY-minY)*.12;minY-=pad;maxY+=pad}
 const sx=x=>left+(x-minX)/(maxX-minX)*plotW,sy=y=>top+plotH-(y-minY)/(maxY-minY)*plotH,clampY=y=>Math.max(top,Math.min(top+plotH,sy(y)));
 let grid="";for(let i=0;i<=5;i++){const x=left+plotW*i/5,y=top+plotH*i/5,xv=minX+(maxX-minX)*i/5,yv=maxY-(maxY-minY)*i/5;grid+='<line x1="'+x+'" y1="'+top+'" x2="'+x+'" y2="'+(top+plotH)+'" stroke="#e2e8f0"/><text x="'+x+'" y="'+(height-31)+'" text-anchor="middle" font-size="11" fill="#64748b">'+Number(xv.toFixed(1))+'</text><line x1="'+left+'" y1="'+y+'" x2="'+(left+plotW)+'" y2="'+y+'" stroke="#e2e8f0"/><text x="'+(left-9)+'" y="'+(y+4)+'" text-anchor="end" font-size="11" fill="#64748b">'+(zeroBased&&maxY>=10?Number(yv.toFixed(1)):Number(yv.toPrecision(4)))+'</text>'}
 let graphics="",details="";
 groups.forEach(group=>{if(group.points.length>1){graphics+='<polyline points="'+group.points.slice().sort((a,b)=>a.x-b.x).map(point=>sx(point.x)+','+sy(point.y)).join(' ')+'" fill="none" stroke="'+group.color+'" stroke-width="2.5"/>'}const model=polynomialRegression(group.points);if(model){const samples=[],groupMinX=Math.min(...group.points.map(point=>point.x)),groupMaxX=Math.max(...group.points.map(point=>point.x));for(let i=0;i<=80;i++){const x=groupMinX+(groupMaxX-groupMinX)*i/80;samples.push(sx(x)+','+clampY(model.predict(x)))}graphics+='<polyline points="'+samples.join(' ')+'" fill="none" stroke="'+group.color+'" stroke-width="2.5" stroke-dasharray="7 4"/>';details+='<div class="rounded-lg border p-2 text-xs"><div class="font-bold" style="color:'+group.color+'">'+esc(group.name)+'</div><div class="mt-1 font-mono text-[10px] text-gray-600">'+esc(equation(model))+'</div><div class="mt-1 font-semibold text-gray-700">R² = '+model.r2.toFixed(4)+'</div><div class="mt-1 text-[11px] text-gray-600">'+esc(evolutionSummary(group.points,metric))+'</div></div>'}else{details+='<div class="rounded-lg border p-2 text-xs"><div class="font-bold" style="color:'+group.color+'">'+esc(group.name)+'</div><div class="mt-1 text-[10px] text-amber-700">Hay '+group.points.length+' puntos válidos; con 2 se dibuja la evolución y con 4 se calcula también la proyección.</div><div class="mt-1 text-[11px] text-gray-600">'+esc(evolutionSummary(group.points,metric))+'</div></div>'}graphics+=group.points.map(point=>'<circle cx="'+sx(point.x)+'" cy="'+sy(point.y)+'" r="6" fill="'+group.color+'" stroke="#fff" stroke-width="2"><title>'+esc(group.name+' · '+point.date+' · '+point.x+' días · '+metric.label+': '+point.y)+'</title></circle>').join('')});
 const legend=groups.map(group=>'<span class="inline-flex items-center gap-1.5 text-xs"><i class="h-2.5 w-2.5 rounded-full" style="background:'+group.color+'"></i>'+esc(group.name)+' ('+group.points.length+')</span>').join('');
 return '<article class="rounded-lg border border-gray-200 bg-white p-3 shadow-sm"><div class="flex flex-wrap items-center justify-between gap-2"><h4 class="text-sm font-bold text-gray-800">Días de descanso vs. '+esc(metric.label)+'</h4><div class="flex flex-wrap gap-3">'+legend+'</div></div><svg viewBox="0 0 '+width+' '+height+'" class="mx-auto mt-2 h-auto w-full" style="max-width:800px;max-height:360px" role="img">'+grid+'<line x1="'+left+'" y1="'+(top+plotH)+'" x2="'+(left+plotW)+'" y2="'+(top+plotH)+'" stroke="#475569"/>'+graphics+'<text x="'+(left+plotW/2)+'" y="'+(height-10)+'" text-anchor="middle" font-size="12" font-weight="600" fill="#334155">Días de descanso</text><text x="18" y="'+(top+plotH/2)+'" text-anchor="middle" font-size="12" font-weight="600" fill="#334155" transform="rotate(-90 18 '+(top+plotH/2)+')">'+esc(metric.label)+'</text></svg><div class="mt-2 grid grid-cols-1 gap-2 md:grid-cols-2">'+details+'</div></article>';
}
function historyTable(group,color){
 if(!group)return '<div class="rounded-lg border bg-gray-50 p-4 text-center text-xs text-gray-500">Selecciona un lote.</div>';
 const valid=group.rows.filter(row=>number(row.rest_days)!==null).length;const body=group.rows.slice().sort((a,b)=>String(a.common_analysis_date||"").localeCompare(String(b.common_analysis_date||""))).map(row=>'<tr class="border-t"><td class="px-2 py-1">'+esc(row.common_analysis_date||row.orthophoto_name||"Sin fecha")+'</td><td class="px-2 py-1"><div class="flex items-center justify-center gap-1"><input type="number" min="0" step="0.1" data-rest-input data-lot-id="'+esc(row.lot_id)+'" data-asset-id="'+esc(row.media_asset_id)+'" value="'+(number(row.rest_days)===null?"":esc(row.rest_days))+'" placeholder="Días" class="w-20 rounded border px-2 py-1 text-center text-xs"><button type="button" data-save-rest class="rounded bg-emerald-600 px-2 py-1 text-white" title="Guardar días"><i class="fas fa-save"></i></button></div></td></tr>').join("");
 return '<div class="overflow-hidden rounded-lg border bg-white"><div class="flex justify-between px-3 py-2 text-xs font-bold" style="color:'+color+'"><span>'+esc(group.name)+'</span><span>'+valid+' de '+group.rows.length+' graficables</span></div><div class="max-h-36 overflow-auto"><table class="w-full text-xs"><thead class="sticky top-0 bg-gray-100"><tr><th class="px-2 py-1 text-left">Fecha / ortofoto</th><th class="px-2 py-1">Días de descanso</th></tr></thead><tbody>'+body+'</tbody></table></div></div>';
}
function renderWorkspace(rows,content,title,subtitle){
 let activeMetric="protein";const availableMetrics=metrics.slice(),seenMetrics=new Set(availableMetrics.map(item=>item.key));
 rows.forEach(row=>Object.entries(row.nutrients_info||{}).forEach(([id,info])=>{const key="nutrient_"+id;if(seenMetrics.has(key))return;seenMetrics.add(key);availableMetrics.push({key,label:(info.symbol||info.name||("Mineral "+id))+(info.unit?" ("+info.unit+")":""),advanced:true})}));
 const farmMap=new Map();rows.forEach(row=>{const key=String(row.farm_id!=null?row.farm_id:(row.farm_name||"Finca"));if(!farmMap.has(key))farmMap.set(key,{key,name:row.farm_name||"Finca",rows:[]});farmMap.get(key).rows.push(row)});
 const farms=Array.from(farmMap.values()).sort((a,b)=>a.name.localeCompare(b.name,"es"));
 content.innerHTML='<section class="grid gap-3 md:grid-cols-2"><div class="rounded-lg border bg-white p-3"><div class="grid grid-cols-2 gap-2"><div><label class="text-xs font-bold text-blue-700">Finca 1</label><select id="projectionFarmA" class="mt-1 w-full rounded border px-2 py-2 text-xs"></select></div><div><label class="text-xs font-bold text-blue-700">Lote 1</label><select id="projectionLotA" class="mt-1 w-full rounded border px-2 py-2 text-xs"></select></div></div><div id="projectionHistoryA" class="mt-2"></div></div><div class="rounded-lg border bg-white p-3"><div class="grid grid-cols-2 gap-2"><div><label class="text-xs font-bold text-red-600">Finca 2</label><select id="projectionFarmB" class="mt-1 w-full rounded border px-2 py-2 text-xs"></select></div><div><label class="text-xs font-bold text-red-600">Lote 2</label><select id="projectionLotB" class="mt-1 w-full rounded border px-2 py-2 text-xs"></select></div></div><div id="projectionHistoryB" class="mt-2"></div></div></section><section class="mt-3 rounded-lg border bg-white p-2"><div class="flex flex-wrap items-center justify-between gap-2"><div id="projectionBasicMetrics" class="flex flex-wrap gap-2"></div><div class="flex gap-2"><button id="backToLotComparison" type="button" class="rounded border px-3 py-2 text-xs font-semibold">Volver</button><button id="projectionDraw" type="button" class="rounded bg-indigo-600 px-4 py-2 text-xs font-bold text-white"><i class="fas fa-chart-line mr-2"></i>Graficar</button></div></div><details class="mt-2 rounded border border-indigo-100 bg-indigo-50/50 p-2"><summary class="cursor-pointer text-xs font-bold text-indigo-800">Variables avanzadas y minerales</summary><div id="projectionAdvancedMetrics" class="mt-2 flex flex-wrap gap-2"></div></details></section><div id="projectionMessage" class="mt-2 hidden rounded border border-amber-200 bg-amber-50 p-2 text-xs text-amber-800"></div><div id="projectionChart" class="mt-3"></div>';
 const farmA=document.getElementById("projectionFarmA"),farmB=document.getElementById("projectionFarmB"),lotA=document.getElementById("projectionLotA"),lotB=document.getElementById("projectionLotB"),historyA=document.getElementById("projectionHistoryA"),historyB=document.getElementById("projectionHistoryB"),graph=document.getElementById("projectionChart"),message=document.getElementById("projectionMessage");
 const farmOptions=value=>farms.map(farm=>'<option value="'+esc(farm.key)+'" '+(farm.key===value?"selected":"")+'>'+esc(farm.name)+'</option>').join("");
 farmA.innerHTML=farmOptions(farms[0]&&farms[0].key);farmB.innerHTML=farmOptions(farms[0]&&farms[0].key);
 const currentFarm=select=>farms.find(farm=>farm.key===select.value)||farms[0];
 const lotsFor=select=>lotGroups((currentFarm(select)||{rows:[]}).rows).sort((a,b)=>a.name.localeCompare(b.name,"es"));
 const selected=(farmSelect,lotSelect)=>lotsFor(farmSelect).find(group=>group.key===lotSelect.value)||null;
 const lotOptions=(groups,value,blocked)=>'<option value="">-- Seleccionar lote --</option>'+groups.map(group=>'<option value="'+esc(group.key)+'" '+(group.key===value?"selected ":"")+(group.key===blocked?"disabled":"")+'>'+esc(group.name)+'</option>').join("");
 function refreshTables(){
  const ga=selected(farmA,lotA),gb=selected(farmB,lotB),sameFarm=farmA.value===farmB.value;
  historyA.innerHTML=historyTable(ga,"#2563eb");historyB.innerHTML=historyTable(gb,"#ef4444");
  lotA.innerHTML=lotOptions(lotsFor(farmA),ga&&ga.key,sameFarm&&gb&&gb.key);lotB.innerHTML=lotOptions(lotsFor(farmB),gb&&gb.key,sameFarm&&ga&&ga.key);
 }
 function resetSide(farmSelect,lotSelect,otherFarm,otherLot){
  const groups=lotsFor(farmSelect),blocked=farmSelect.value===otherFarm.value?otherLot.value:"",first=groups.find(group=>group.key!==blocked)||null;
  lotSelect.innerHTML=lotOptions(groups,first&&first.key,blocked);refreshTables();graph.innerHTML="";message.classList.add("hidden");
 }
 const metricButton=metric=>'<button type="button" data-projection-metric="'+metric.key+'" class="rounded border px-3 py-1.5 text-xs font-semibold">'+esc(metric.label)+'</button>';
 document.getElementById("projectionBasicMetrics").innerHTML=availableMetrics.filter(metric=>!metric.advanced).map(metricButton).join("");
 document.getElementById("projectionAdvancedMetrics").innerHTML=availableMetrics.filter(metric=>metric.advanced).map(metricButton).join("");
 function paint(){document.querySelectorAll("[data-projection-metric]").forEach(button=>{const on=button.dataset.projectionMetric===activeMetric;button.className="rounded border px-3 py-1.5 text-xs font-semibold "+(on?"border-indigo-600 bg-indigo-600 text-white":"border-gray-300 bg-white text-gray-700")})}
 document.querySelectorAll("[data-projection-metric]").forEach(button=>button.addEventListener("click",()=>{activeMetric=button.dataset.projectionMetric;paint()}));
 farmA.addEventListener("change",()=>resetSide(farmA,lotA,farmB,lotB));farmB.addEventListener("change",()=>resetSide(farmB,lotB,farmA,lotA));lotA.addEventListener("change",refreshTables);lotB.addEventListener("change",refreshTables);
 content.addEventListener("click",async event=>{
  const button=event.target.closest("[data-save-rest]");if(!button)return;
  const input=button.parentElement.querySelector("[data-rest-input]"),lotId=Number(input.dataset.lotId),assetId=Number(input.dataset.assetId),value=number(input.value);
  if(value===null||value<0){message.textContent="Escribe un número válido de días de descanso.";message.classList.remove("hidden");return}
  button.disabled=true;button.innerHTML='<i class="fas fa-spinner fa-spin"></i>';
  try{
   const getResponse=await fetch("/api/agrovista/lot-asset-form?lot_id="+lotId+"&media_asset_id="+assetId,{credentials:"include",cache:"no-store"}),existing=await getResponse.json().catch(()=>({}));
   if(!getResponse.ok)throw new Error(existing.description||"No se pudieron cargar los datos existentes.");
   const formData=Object.assign({},existing.form_data||{},{rest_days:value});
   const saveResponse=await fetch("/api/agrovista/lot-asset-form",{method:"PUT",credentials:"include",headers:{"Content-Type":"application/json","X-CSRF-TOKEN":csrf()},body:JSON.stringify({lot_id:lotId,media_asset_id:assetId,form_data:formData})}),saved=await saveResponse.json().catch(()=>({}));
   if(!saveResponse.ok)throw new Error(saved.description||"No se pudieron guardar los días.");
   rows.filter(row=>Number(row.lot_id)===lotId&&Number(row.media_asset_id)===assetId).forEach(row=>row.rest_days=value);
   refreshTables();graph.innerHTML="";message.textContent="Días guardados. Pulsa Graficar para actualizar.";message.classList.remove("hidden");
  }catch(error){message.textContent=error.message;message.classList.remove("hidden");button.disabled=false;button.innerHTML='<i class="fas fa-save"></i>'}
 });
 document.getElementById("projectionDraw").addEventListener("click",()=>{
  const ga=selected(farmA,lotA),gb=selected(farmB,lotB);
  if(!ga||!gb||(farmA.value===farmB.value&&ga.key===gb.key)){message.textContent="Selecciona dos lotes diferentes para realizar la comparación.";message.classList.remove("hidden");graph.innerHTML="";return}
  const metric=availableMetrics.find(item=>item.key===activeMetric)||availableMetrics[0],pointsA=pointsFor(ga.rows,metric.key),pointsB=pointsFor(gb.rows,metric.key);
  message.textContent=ga.name+": "+pointsA.length+" puntos · "+gb.name+": "+pointsB.length+" puntos. La línea ordena cada análisis por sus días de descanso.";message.classList.remove("hidden");
  graph.innerHTML=chart(metric,ga.rows.concat(gb.rows));subtitle.textContent=currentFarm(farmA).name+" / "+ga.name+" vs. "+currentFarm(farmB).name+" / "+gb.name+" · "+metric.label;
 });
 document.getElementById("backToLotComparison").addEventListener("click",()=>{title.textContent="Comparación de lotes";document.getElementById("openLotComparisonBtn")?.click()});
 const initialA=lotsFor(farmA)[0]||null,initialB=lotsFor(farmB)[1]||lotsFor(farmB)[0]||null;
 lotA.innerHTML=lotOptions(lotsFor(farmA),initialA&&initialA.key,initialB&&initialB.key);lotB.innerHTML=lotOptions(lotsFor(farmB),initialB&&initialB.key,initialA&&initialA.key);paint();refreshTables();
}
async function openProjection(){
 const modal=document.getElementById("lotComparisonModal"),content=document.getElementById("lotComparisonContent"),title=document.getElementById("lotComparisonTitle"),subtitle=document.getElementById("lotComparisonSubtitle"),button=document.getElementById("openLotProjectionBtn");if(!modal||!content)return;
 modal.classList.remove("hidden");document.body.classList.add("overflow-hidden");button.disabled=true;title.textContent="Proyecciones de proteína y minerales";subtitle.textContent="Cargando análisis de todas las ortofotos…";content.innerHTML='<div class="p-10 text-center text-sm text-gray-500"><i class="fas fa-spinner fa-spin mr-2"></i>Cargando historial…</div>';
 try{const allRows=typeof window.getSavedPolygonMineralRows==="function"?await window.getSavedPolygonMineralRows():[],rows=allRows;subtitle.textContent=lotGroups(rows).length+" lotes · "+rows.length+" análisis revisados";if(!rows.length){content.innerHTML='<div class="rounded-xl border border-amber-200 bg-amber-50 p-6 text-center text-sm text-amber-800">Todavía no hay análisis de ortofotos guardados.</div>';return}renderWorkspace(rows,content,title,subtitle)}catch(error){console.error(error);subtitle.textContent="";content.innerHTML='<div class="rounded-lg border border-red-200 bg-red-50 p-4 text-sm text-red-700">'+esc(error.message||"No se pudieron generar las proyecciones.")+'</div>'}finally{button.disabled=false}
}
document.addEventListener("DOMContentLoaded",()=>{const button=document.getElementById("openLotProjectionBtn");if(button)button.addEventListener("click",openProjection)});
})();