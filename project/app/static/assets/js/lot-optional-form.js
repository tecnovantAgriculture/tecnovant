(function(){
"use strict";
var fields=[
 ["entry_date","Fecha entrada ganado","date"],
 ["exit_date","Fecha salida","date"],
 ["rest_days","Días de descanso","number"],
 ["paddock","Potrero","text"],
 ["milk_liters","Producción de leche (litros)","number"]
];
function esc(value){return String(value==null?"":value).replace(/[&<>'"]/g,function(char){return {"&":"&amp;","<":"&lt;",">":"&gt;","'":"&#39;",'"':"&quot;"}[char]})}
function csrf(){var match=document.cookie.match(/(?:^|;\s*)csrf_access_token=([^;]+)/);return match?decodeURIComponent(match[1]):""}
function valueAt(object,path){return path.split(".").reduce(function(value,key){return value&&value[key]!=null?value[key]:null},object)}
function defaults(ctx){return {entry_date:"",exit_date:"",rest_days:"",paddock:ctx.lotName||"",milk_liters:""}}
function install(){
 if(document.getElementById("lot-optional-form-modal"))return;
 var modal=document.createElement("div");
 modal.id="lot-optional-form-modal";
 modal.className="hidden fixed inset-0";
 modal.style.zIndex="2147483645";
 modal.innerHTML='<div data-lot-form-close class="absolute inset-0 bg-slate-950/50"></div><section style="top:50vh;left:50vw;transform:translate(-50%,-50%)" class="absolute flex max-h-[90vh] w-[min(620px,calc(100vw-24px))] flex-col overflow-hidden rounded-2xl bg-white shadow-2xl dark:bg-gray-900"><header class="flex items-start justify-between border-b px-5 py-4"><div><h2 class="text-base font-bold text-gray-900 dark:text-white">Datos del lote</h2><p id="lot-form-context" class="mt-1 text-xs text-gray-500"></p></div><button type="button" data-lot-form-close class="rounded-lg p-2 text-gray-500 hover:bg-gray-100" aria-label="Cerrar"><i class="fas fa-times"></i></button></header><form id="lot-optional-form" class="min-h-0 flex-1 overflow-y-auto p-5"><div class="mb-4 rounded-lg border border-blue-100 bg-blue-50 px-3 py-2 text-xs text-blue-800"><strong>Formulario opcional.</strong> Puedes guardar solo los datos disponibles o cerrarlo sin completar campos.</div><div id="lot-form-fields" class="grid gap-3 sm:grid-cols-2"></div><p id="lot-form-status" class="mt-3 min-h-[18px] text-xs text-gray-500"></p><footer class="mt-4 flex justify-end gap-2 border-t pt-4"><button type="button" data-lot-form-close class="rounded-lg border px-4 py-2 text-sm font-semibold text-gray-600">Cancelar</button><button id="lot-form-save" type="submit" class="rounded-lg bg-emerald-600 px-4 py-2 text-sm font-semibold text-white hover:bg-emerald-700"><i class="fas fa-save mr-2"></i>Guardar datos</button></footer></form></section>';
 document.body.appendChild(modal);
 document.querySelectorAll("[data-lot-form-close]").forEach(function(node){node.addEventListener("click",close)});
 document.getElementById("lot-optional-form").addEventListener("submit",save);
 document.addEventListener("keydown",function(event){if(event.key==="Escape"&&!modal.classList.contains("hidden")){event.stopImmediatePropagation();close()}},true);
}
function renderFields(values){
 document.getElementById("lot-form-fields").innerHTML=fields.map(function(field){
  var name=field[0],label=field[1],type=field[2],value=values[name];
  return '<label class="block text-xs font-semibold text-gray-600">'+esc(label)+'<input name="'+esc(name)+'" type="'+type+'" '+(type==="number"?'step="any"':'')+' value="'+esc(value==null?"":value)+'" class="mt-1 block w-full rounded-lg border border-gray-300 px-3 py-2 text-sm"></label>';
 }).join("");
}
async function open(){
 install();
 var ctx=window.getAgrovistaLotFormContext&&window.getAgrovistaLotFormContext();
 if(!ctx||!ctx.lotId||!ctx.assetId){if(window.Swal){Swal.fire({icon:"info",title:"Selecciona un lote",text:"Selecciona una ortofoto y un lote guardado antes de abrir sus datos."})}else{alert("Selecciona una ortofoto y un lote guardado.")}return}
 var modal=document.getElementById("lot-optional-form-modal"),status=document.getElementById("lot-form-status");
 modal.dataset.lotId=ctx.lotId;modal.dataset.assetId=ctx.assetId;
 document.getElementById("lot-form-context").textContent=[ctx.lotName,ctx.date].filter(Boolean).join(" · ");
 renderFields(defaults(ctx));status.textContent="Cargando datos guardados…";modal.classList.remove("hidden");document.body.classList.add("overflow-hidden");
 try{
  var response=await fetch("/api/agrovista/lot-asset-form?lot_id="+encodeURIComponent(ctx.lotId)+"&media_asset_id="+encodeURIComponent(ctx.assetId),{credentials:"include",cache:"no-store"});
  var body=await response.json().catch(function(){return {}});
  if(!response.ok)throw new Error(body.description||body.error||"No se pudieron cargar los datos.");
  renderFields(Object.assign(defaults(ctx),body.form_data||{}));status.textContent=Object.keys(body.form_data||{}).length?"Datos guardados cargados.":"Todavía no hay datos manuales guardados.";
 }catch(error){status.textContent=error.message;status.className="mt-3 min-h-[18px] text-xs text-red-600"}
}
async function save(event){
 event.preventDefault();
 var modal=document.getElementById("lot-optional-form-modal"),button=document.getElementById("lot-form-save"),status=document.getElementById("lot-form-status"),form=event.currentTarget,data={};
 new FormData(form).forEach(function(value,key){data[key]=String(value).trim()});
 button.disabled=true;status.textContent="Guardando…";
 try{
  var response=await fetch("/api/agrovista/lot-asset-form",{method:"PUT",credentials:"include",headers:{"Content-Type":"application/json","X-CSRF-TOKEN":csrf()},body:JSON.stringify({lot_id:Number(modal.dataset.lotId),media_asset_id:Number(modal.dataset.assetId),form_data:data})});
  var body=await response.json().catch(function(){return {}});
  if(!response.ok)throw new Error(body.description||body.error||"No se pudieron guardar los datos.");
  status.className="mt-3 min-h-[18px] text-xs text-emerald-700";status.textContent="Datos guardados para este lote y esta ortofoto.";
  setTimeout(close,700);
 }catch(error){status.className="mt-3 min-h-[18px] text-xs text-red-600";status.textContent=error.message}finally{button.disabled=false}
}
function close(){var modal=document.getElementById("lot-optional-form-modal");if(modal){modal.classList.add("hidden");document.body.classList.remove("overflow-hidden")}}
document.addEventListener("DOMContentLoaded",function(){var button=document.getElementById("openLotOptionalForm");if(button)button.addEventListener("click",function(event){event.preventDefault();event.stopPropagation();open()})});
})();
