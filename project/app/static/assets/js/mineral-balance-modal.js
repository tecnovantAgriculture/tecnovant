(function () {
  "use strict";

  const ENDPOINTS = {
    objectives: "/api/foliage/objectives/",
    common: "/api/foliage/common_analyses/",
    leaf: "/api/foliage/leaf_analyses/",
    balance: "/api/agrovista/mineral-balance",
    comparison: document.currentScript?.dataset.comparisonUrl || "/dashboard/agrovista/comparacion",
  };
  const ORDER = ["N", "P", "K", "Ca", "Mg", "S", "Cu", "Zn", "Mn", "B", "Mo", "Fe", "Si"];
  const NUTRIENT_SYMBOLS = {
    n: "N", nitrogeno: "N", nitrogen: "N",
    p: "P", fosforo: "P", phosphorus: "P",
    k: "K", potasio: "K", potassium: "K",
    ca: "Ca", calcio: "Ca", calcium: "Ca",
    mg: "Mg", magnesio: "Mg", magnesium: "Mg",
    s: "S", azufre: "S", sulfur: "S", sulphur: "S",
    cu: "Cu", cobre: "Cu", copper: "Cu",
    zn: "Zn", zinc: "Zn",
    mn: "Mn", manganeso: "Mn", manganese: "Mn",
    b: "B", boro: "B", boron: "B",
    mo: "Mo", molibdeno: "Mo", molybdenum: "Mo",
    fe: "Fe", hierro: "Fe", iron: "Fe",
    si: "Si", silicio: "Si", silicon: "Si",
  };
  function nutrientSymbol(value) {
    const key = String(value || "").trim().toLowerCase().normalize("NFD").replace(/[\u0300-\u036f]/g, "");
    return NUTRIENT_SYMBOLS[key] || null;
  }
  const state = { loaded: false, objectives: [], common: [], leaf: [], selectedObjective: null, selectedLeaf: null, balance: null, showGrade: false, showNano: false };

  function esc(value) {
    const node = document.createElement("div");
    node.textContent = value == null ? "" : String(value);
    return node.innerHTML;
  }
  function number(value) {
    if (value == null || value === "") return null;
    const parsed = Number(value);
    return Number.isFinite(parsed) ? parsed : null;
  }
  function fmt(value, digits) {
    const parsed = number(value);
    if (parsed == null) return "0";
    return parsed.toFixed(digits == null ? 2 : digits).replace(/\.00$/, "").replace(/(\.\d*[1-9])0+$/, "$1");
  }
  function csrf() {
    return document.querySelector('meta[name="csrf-token"]')?.content || document.querySelector('input[name="csrf_token"]')?.value || "";
  }
  function nutrientInfo(item) {
    const rows = Array.isArray(item?.nutrient_targets) ? item.nutrient_targets : [];
    const info = new Map();
    rows.forEach(row => info.set(String(row.nutrient_id), {
      id: Number(row.nutrient_id), name: row.nutrient_name || row.nutrient_symbol,
      symbol: row.nutrient_symbol || row.nutrient_name, unit: row.nutrient_unit || "", value: row.target_value,
    }));
    return info;
  }
  function allNutrients() {
    const result = new Map();
    state.objectives.forEach(objective => nutrientInfo(objective).forEach((value, key) => result.set(key, value)));
    state.leaf.forEach(analysis => Object.entries(analysis.nutrients_info || {}).forEach(([key, value]) => {
      if (!result.has(key)) result.set(key, { id: Number(key), name: value.name || value.symbol, symbol: value.symbol || value.name, unit: value.unit || "" });
    }));
    return Array.from(result.values())
      .map(item => ({ ...item, symbol: nutrientSymbol(item.symbol) || nutrientSymbol(item.name) || item.symbol }))
      .filter(item => ORDER.includes(item.symbol))
      .sort((a, b) => ORDER.indexOf(a.symbol) - ORDER.indexOf(b.symbol));
  }
  function commonFor(leaf) {
    return state.common.find(item => Number(item.id) === Number(leaf.common_analysis_id)) || {
      id: leaf.common_analysis_id, date: leaf.common_analysis_date,
      farm_id: leaf.farm_id, farm_name: leaf.farm_name,
      lot_id: leaf.lot_id, lot_name: leaf.lot_name,
      protein: leaf.protein, yield_estimate: leaf.yield_estimate,
    };
  }

  function installMarkup() {
    const mediaButton = document.getElementById("open-media-picker");
    if (!mediaButton || document.getElementById("open-mineral-balance")) return false;
    mediaButton.insertAdjacentHTML("afterend", '<button id="open-mineral-balance" type="button" class="inline-flex items-center gap-2 rounded-lg bg-emerald-700 px-3 py-2 text-xs font-semibold text-white shadow-sm hover:bg-emerald-800"><i class="fas fa-balance-scale"></i>Balance de minerales</button>');
    if (!document.getElementById("mineral-balance-modal-style")) {
      document.head.insertAdjacentHTML("beforeend", `<style id="mineral-balance-modal-style">
        #open-mineral-balance{display:inline-flex!important;align-items:center!important;gap:8px!important;border:1px solid #047857!important;border-radius:9px!important;background:#047857!important;padding:9px 13px!important;color:#fff!important;font-size:12px!important;font-weight:700!important;line-height:1!important;opacity:1!important;box-shadow:0 1px 3px rgba(15,23,42,.18)!important;white-space:nowrap!important}
        #open-mineral-balance:hover{border-color:#065f46!important;background:#065f46!important;color:#fff!important}
        #open-mineral-balance:focus-visible{outline:3px solid rgba(16,185,129,.3)!important;outline-offset:2px!important}
        #mineral-balance-layout{display:grid;grid-template-columns:minmax(0,1fr);min-height:0;flex:1;overflow:hidden}
        #mineral-balance-sidebar{display:flex;min-height:0;flex-direction:column;gap:10px;overflow-y:auto;border-right:1px solid #d1d5db;background:#fff;padding:12px}
        #mineral-balance-main{display:grid;min-height:0;grid-template-rows:145px 145px minmax(250px,1fr);gap:8px;overflow:hidden;background:#f9fafb;padding:8px}
        #mineral-balance-main>section{display:flex;min-height:0;flex-direction:column;overflow:hidden}
        #mineral-balance-main>section>.mineral-table-scroll{min-height:0;flex:1;overflow:auto}
        #mineral-balance-main table{min-width:980px!important;font-size:9px!important;line-height:1.05}
        #mineral-balance-main table th,#mineral-balance-main table td{padding:3px 5px!important;white-space:nowrap}
        #mineral-balance-main h3{padding-top:4px!important;padding-bottom:4px!important}
        #mineral-summary{display:grid!important;grid-template-columns:repeat(4,minmax(0,1fr))!important}
        .mineral-row-action{border:1px solid #9ca3af;background:#fff;padding:3px 6px;font-size:9px;font-weight:700;color:#374151;box-shadow:0 1px 2px rgba(0,0,0,.08)}
        .mineral-row-action:hover{background:#f3f4f6;border-color:#4b5563}
        #mineral-balance-actions{display:flex;flex-direction:row;align-items:center;gap:8px;margin-top:0}
        #mineral-balance-actions button{width:auto}
        #mineral-balance-main table thead{position:sticky;top:0;z-index:2}
        #mineral-balance-modal>section{inset:auto!important;left:50%!important;top:50%!important;transform:translate(-50%,-50%);width:min(1420px,calc(100vw - 48px));height:auto!important;max-height:calc(100vh - 48px);border:0!important;border-radius:18px!important;background:#f8fafc!important;box-shadow:0 28px 80px rgba(15,23,42,.28)!important}
        #mineral-balance-modal>section>header{padding:12px 18px!important;background:linear-gradient(135deg,#fff 0%,#f8fafc 100%)!important}
        #mineral-balance-title{font-size:15px;letter-spacing:.04em;color:#0f172a}
        #mineral-status{margin-top:3px;font-size:11px}
        #mineral-balance-layout{grid-template-columns:minmax(0,1fr)!important;min-height:0!important;height:auto!important;max-height:calc(100vh - 112px);flex:none!important}
        #mineral-balance-sidebar{gap:14px!important;padding:16px 14px!important;border-color:#e2e8f0!important;background:#fff!important}
        #mineral-balance-sidebar>div:first-child{padding:2px 0 14px!important;border-color:#e2e8f0!important;font-size:17px!important}
        #mineral-balance-sidebar label{font-size:9px!important;letter-spacing:.06em;color:#64748b!important}
        #mineral-balance-sidebar input,#mineral-balance-sidebar select{margin-top:5px!important;border:1px solid #e2e8f0!important;border-radius:9px!important;background:#f8fafc!important;padding:7px 9px!important;font-size:11px!important;color:#334155!important;box-shadow:none!important}
        #mineral-balance-actions{gap:7px!important;margin-top:0!important;padding-top:0}
        #mineral-balance-actions button{border:1px solid #e2e8f0!important;border-radius:9px!important;background:#fff!important;padding:8px 10px!important;font-size:10px!important;color:#334155!important;box-shadow:0 1px 2px rgba(15,23,42,.04)}
        #mineral-balance-actions button:hover:not(:disabled){border-color:#10b981!important;background:#ecfdf5!important;color:#047857!important}
        #mineral-balance-main{grid-template-rows:155px 155px auto!important;align-content:start;gap:10px!important;padding:12px!important;background:#f1f5f9!important}
        #mineral-balance-main>section{border:1px solid #e2e8f0!important;border-radius:12px!important;background:#fff!important;box-shadow:0 1px 3px rgba(15,23,42,.05)!important}
        #mineral-balance-main h3{border-color:#e2e8f0!important;background:#fff!important;padding:7px 12px!important;text-align:left!important;font-size:10px!important;letter-spacing:.08em!important;color:#059669!important}
        #mineral-balance-main table{min-width:940px!important;font-size:9px!important;color:#334155}
        #mineral-balance-main table thead{background:#f8fafc!important;color:#64748b!important}
        #mineral-balance-main table th,#mineral-balance-main table td{padding:3px 7px!important;border-color:#f1f5f9!important}
        #mineral-balance-main tbody tr{transition:background-color .12s ease}
        #mineral-balance-main tbody tr:hover{background:#f0fdf4!important}
        #mineral-balance-output{min-height:0!important;padding:10px 12px!important}
        #mineral-summary{gap:8px!important;margin-bottom:9px!important}
        #mineral-summary>div{border:1px solid #e2e8f0!important;border-radius:10px!important;background:#f8fafc!important;padding:7px 9px!important}
        #mineral-summary span{font-size:8px!important;letter-spacing:.05em}
        #mineral-summary strong{margin-top:2px!important;font-size:12px!important;color:#0f172a}
        .mineral-row-action{border:0!important;border-radius:6px!important;background:#fff!important;padding:3px 7px!important;color:#047857!important;box-shadow:0 0 0 1px #a7f3d0!important}
        .mineral-row-action:hover{background:#d1fae5!important}
        .mineral-action-table{margin-top:8px;overflow:hidden;border:1px solid #e2e8f0;border-radius:9px;background:#fff;box-shadow:0 1px 2px rgba(15,23,42,.04)}
        .mineral-action-table table{margin:0!important}
        .mineral-action-table thead{position:static!important}
        .dark #mineral-balance-sidebar{border-color:#374151;background:#111827}
        .dark #mineral-balance-main{background:#030712}
        @media(max-width:700px){
          #mineral-balance-modal>section{width:calc(100vw - 16px);height:calc(100vh - 16px)!important;max-height:none;border-radius:12px!important}
          #mineral-balance-layout{display:flex;flex-direction:column;overflow:hidden}
          #mineral-balance-sidebar{min-height:auto;flex:none;flex-direction:row;overflow-x:auto;border-right:0;border-bottom:1px solid #d1d5db}
          #mineral-balance-sidebar label{min-width:150px}
          #mineral-balance-actions{margin:0 0 0 auto;flex-direction:row}
          #mineral-balance-actions button{width:auto;white-space:nowrap}
          #mineral-balance-main{display:block;overflow:auto}
          #mineral-balance-main>section{height:250px;margin-bottom:12px}
          #mineral-balance-main>#mineral-balance-output{height:auto;min-height:330px}
        }
      </style>`);
    }
    document.body.insertAdjacentHTML("beforeend", `
      <div id="mineral-balance-modal" class="hidden fixed inset-0 bg-slate-950/70 backdrop-blur-sm" style="z-index:2147483600" role="dialog" aria-modal="true" aria-labelledby="mineral-balance-title">
        <div class="absolute inset-0" data-mineral-close></div>
        <section class="absolute inset-2 flex min-h-0 flex-col overflow-hidden rounded-xl border border-gray-300 bg-gray-100 shadow-2xl dark:border-gray-700 dark:bg-gray-950 sm:inset-4">
          <header class="flex shrink-0 items-center justify-between border-b border-gray-300 bg-white px-4 py-3 dark:border-gray-700 dark:bg-gray-900">
            <div><h2 id="mineral-balance-title" class="font-semibold uppercase tracking-wide">Balance de minerales</h2><p id="mineral-status" class="text-xs text-gray-500">Selecciona un objetivo y un análisis foliar.</p></div>
            <div id="mineral-balance-actions" class="flex items-center gap-2">
              <button id="mineral-formulator" disabled class="rounded border bg-white px-3 py-2 text-xs font-semibold uppercase disabled:opacity-50">Formulador</button>
              <button id="mineral-projection" disabled class="rounded border bg-white px-3 py-2 text-xs font-semibold uppercase disabled:opacity-50">Proyección</button>
              <button id="mineral-liebig" disabled class="rounded border bg-white px-3 py-2 text-xs font-semibold uppercase disabled:opacity-50">Ley Liebig</button>
              <button type="button" data-mineral-close class="h-9 w-9 rounded-md text-gray-500 hover:bg-gray-100" aria-label="Cerrar"><i class="fas fa-times"></i></button>
            </div>
          </header>
          <div id="mineral-balance-layout">
            <main id="mineral-balance-main">
              ${tableSection("Objetivo", "objective")}
              ${tableSection("Foliar", "foliar")}
              <section id="mineral-balance-output" class="border-t-2 border-indigo-700 bg-white p-3 shadow-sm dark:bg-gray-900">
                <h3 class="mb-2 text-center text-xs font-bold uppercase tracking-wider text-red-500">Balance</h3>
                <div id="mineral-summary" class="mb-3 grid grid-cols-2 gap-2 text-center text-[11px] sm:grid-cols-4"></div>
                <div id="mineral-result" class="overflow-x-auto"><div class="border border-dashed p-8 text-center text-xs text-gray-500">Selecciona una fila de Objetivo y una de Foliar; después pulsa Formulador.</div></div>
                <div id="mineral-liebig-result" class="mt-3 hidden border-l-4 border-amber-500 bg-amber-50 px-4 py-3 text-xs text-amber-900"></div>
              </section>
            </main>
          </div>
        </section>
      </div>`);
    return true;
  }
  function tableSection(title, prefix) {
    return `<section class="border border-gray-300 bg-white shadow-sm dark:border-gray-700 dark:bg-gray-900"><h3 class="shrink-0 border-b py-1.5 text-center text-xs font-bold uppercase tracking-wider text-red-500">${title}</h3><div class="mineral-table-scroll"><table class="w-full min-w-[1120px] border-collapse text-[11px]"><thead id="mineral-${prefix}-head" class="bg-gray-100 text-gray-600"></thead><tbody id="mineral-${prefix}-body" class="divide-y"><tr><td class="p-5 text-center text-gray-500">Cargando…</td></tr></tbody></table></div></section>`;
  }
  function setStatus(message, error) {
    const node = document.getElementById("mineral-status");
    if (node) { node.textContent = message; node.classList.toggle("text-red-600", !!error); }
  }
  function updateButtons() {
    const ready = !!state.selectedObjective && !!state.selectedLeaf;
    document.getElementById("mineral-formulator").disabled = !ready;
    document.getElementById("mineral-projection").disabled = !ready;
    document.getElementById("mineral-liebig").disabled = !state.balance;
  }

  async function load() {
    if (state.loaded) return renderAll();
    setStatus("Cargando objetivos y análisis foliares…");
    const resources = [
      { key: "objectives", label: "Objetivos", url: ENDPOINTS.objectives },
      { key: "leaf", label: "Análisis foliares", url: ENDPOINTS.leaf + "?page=1&per_page=100" },
    ];
    const results = await Promise.allSettled(resources.map(async resource => {
      const response = await fetch(resource.url, { credentials: "include" });
      const body = await response.json().catch(() => ({}));
      if (!response.ok) {
        const detail = body?.description || body?.error || body?.message || `HTTP ${response.status}`;
        throw new Error(`${resource.label}: ${detail}`);
      }
      const data = Array.isArray(body) ? body : (Array.isArray(body?.items) ? body.items : []);
      return { key: resource.key, data };
    }));
    const errors = [];
    results.forEach((result, index) => {
      if (result.status === "fulfilled") state[result.value.key] = result.value.data;
      else errors.push(result.reason?.message || `${resources[index].label}: error de consulta`);
    });
    renderAll();
    state.loaded = errors.length === 0;
    if (errors.length) setStatus(errors.join(" · "), true);
    else if (!state.objectives.length && !state.leaf.length) setStatus("No hay objetivos ni análisis foliares disponibles para este usuario.", true);
    else setStatus("Selecciona un objetivo y un análisis foliar.");
  }
  function renderAll() { renderObjectives(); renderFoliar(); updateButtons(); }
  function renderObjectives() {
    const nutrients = allNutrients();
    document.getElementById("mineral-objective-head").innerHTML = `<tr><th class="px-2 py-2">ID</th><th class="px-2 py-2 text-left">Cultivo</th>${nutrients.map(n => `<th class="px-2 py-2">${esc(n.symbol)}</th>`).join("")}<th class="px-2 py-2">Aforo</th><th class="px-2 py-2">Descanso</th></tr>`;
    const rows = state.objectives;
    document.getElementById("mineral-objective-body").innerHTML = rows.length ? rows.map(item => {
      const values = nutrientInfo(item), selected = Number(state.selectedObjective?.id) === Number(item.id);
      return `<tr data-objective-id="${item.id}" class="cursor-pointer hover:bg-emerald-50 ${selected ? "bg-emerald-100 ring-1 ring-inset ring-emerald-500" : ""}"><td class="px-2 py-1.5 text-center">${item.id}</td><td class="px-2 py-1.5 font-medium">${esc(item.crop_name)}</td>${nutrients.map(n => `<td class="px-2 py-1.5 text-center">${fmt(values.get(String(n.id))?.value, 3)}</td>`).join("")}<td class="px-2 py-1.5 text-center">${fmt(item.target_value, 3)}</td><td class="px-2 py-1.5 text-center">${fmt(item.rest, 0)}</td></tr>`;
    }).join("") : `<tr><td colspan="${nutrients.length + 4}" class="p-5 text-center text-gray-500">No hay objetivos para mostrar.</td></tr>`;
  }
  function renderFoliar() {
    const nutrients = allNutrients();
    document.getElementById("mineral-foliar-head").innerHTML = `<tr><th class="px-2 py-2">ID</th><th class="px-2 py-2">Fecha</th><th class="px-2 py-2 text-left">Finca</th><th class="px-2 py-2 text-left">Potrero</th>${nutrients.map(n => `<th class="px-2 py-2">${esc(n.symbol)}</th>`).join("")}</tr>`;
    const rows = state.leaf;
    document.getElementById("mineral-foliar-body").innerHTML = rows.length ? rows.map(item => {
      const common = commonFor(item), selected = Number(state.selectedLeaf?.id) === Number(item.id);
      return `<tr data-leaf-id="${item.id}" class="cursor-pointer hover:bg-sky-50 ${selected ? "bg-sky-100 ring-1 ring-inset ring-sky-500" : ""}"><td class="px-2 py-1.5 text-center">${item.id}</td><td class="px-2 py-1.5 text-center">${esc(common.date || item.common_analysis_date || "")}</td><td class="px-2 py-1.5">${esc(common.farm_name || item.farm_name || "")}</td><td class="px-2 py-1.5">${esc(common.lot_name || item.lot_name || "")}</td>${nutrients.map(n => `<td class="px-2 py-1.5 text-center">${fmt(item[`nutrient_${n.id}`], 3)}</td>`).join("")}</tr>`;
    }).join("") : `<tr><td colspan="${nutrients.length + 4}" class="p-5 text-center text-gray-500">No hay análisis foliares para este filtro.</td></tr>`;
  }

  function buildPayload() {
    const objective = state.selectedObjective, leaf = state.selectedLeaf, common = commonFor(leaf), info = nutrientInfo(objective), nutrients = allNutrients();
    const order = [], targets = {}, actuals = {};
    nutrients.forEach(nutrient => {
      const target = info.get(String(nutrient.id));
      if (!target) return;
      const name = target.name || nutrient.name || nutrient.symbol;
      order.push(name); targets[name] = target.value; actuals[name] = leaf[`nutrient_${nutrient.id}`];
    });
    return { order, targets, actuals, aforo_objective: objective.target_value, aforo_actual: common.yield_estimate, protein: objective.protein };
  }
  async function calculate() {
    setStatus("Calculando balance mineral…");
    try {
      const response = await fetch(ENDPOINTS.balance, { method: "POST", credentials: "include", headers: { "Content-Type": "application/json", "X-CSRF-TOKEN": csrf() }, body: JSON.stringify(buildPayload()) });
      const data = await response.json().catch(() => ({}));
      if (!response.ok) throw new Error(data.description || data.error || "No se pudo calcular el balance.");
      state.balance = data; renderBalance(); updateButtons(); setStatus("Balance calculado con la lógica vigente del sistema.");
    } catch (error) { setStatus(error.message, true); }
  }
  function renderBalance() {
    const objective = state.selectedObjective, common = commonFor(state.selectedLeaf);
    const nutrientMeta = new Map(Array.from(nutrientInfo(objective).values()).map(item => [String(item.name || "").toLowerCase(), { symbol: item.symbol, isMicro: String(item.unit || "").toLowerCase().includes("ppm") }]));
    const entries = (Array.isArray(state.balance?.entries) ? state.balance.entries : [])
      .map(item => ({ ...item, _symbol: nutrientSymbol(item.symbol) || nutrientSymbol(item.name) || nutrientSymbol(nutrientMeta.get(String(item.name || "").toLowerCase())?.symbol) }))
      .filter(item => ORDER.includes(item._symbol))
      .sort((a, b) => ORDER.indexOf(a._symbol) - ORDER.indexOf(b._symbol));
    const cards = [["Proteína objetivo", objective.protein, "%"], ["Aforo objetivo", state.balance.aforo_objective ?? objective.target_value, " kg/m²"], ["Proteína actual", common.protein, "%"], ["Aforo actual", common.yield_estimate, " kg/m²"]];
    document.getElementById("mineral-summary").innerHTML = cards.map(([label, value, suffix]) => `<div class="border bg-gray-100 px-3 py-2"><span class="block uppercase text-gray-500">${label}</span><strong class="mt-1 block text-sm">${number(value) == null ? "--" : fmt(value, 2) + suffix}</strong></div>`).join("");
    const sum = key => entries.reduce((total, item) => total + (number(item[key]) || 0), 0);
    const displayValue = (item, key) => {
      const value = number(item[key]);
      const meta = nutrientMeta.get(String(item.name || "").toLowerCase());
      return value != null && meta?.isMicro && ["objective_kg", "actual_kg", "difference_kg"].includes(key) ? value * 1000 : value;
    };
    const row = (label, key, cls, total, suffix) => `<tr class="${cls}"><th class="sticky left-0 bg-inherit px-2 py-1.5 text-left">${label}</th>${entries.map(item => `<td class="px-2 py-1.5 text-center">${fmt(displayValue(item, key), 2)}</td>`).join("")}<td class="px-2 py-1.5 text-center font-bold">${total == null ? "--" : fmt(total, 2) + (suffix || "")}</td></tr>`;
    const headerCells = entries.map(item => { const meta = nutrientMeta.get(String(item.name || "").toLowerCase()); return `<th class="px-2 py-2">${esc(item._symbol)} (${meta?.isMicro ? "g" : "kg"})</th>`; }).join("");
    const actionRow = (label, action, key, cls, visible, total, suffix) => `<tr class="${cls}"><th class="sticky left-0 bg-inherit px-2 py-1.5 text-left"><button type="button" class="mineral-row-action" data-mineral-reveal="${action}">${label}</button></th>${entries.map(item => `<td class="px-2 py-1.5 text-center">${visible ? fmt(item[key], 2) : ""}</td>`).join("")}<td class="px-2 py-1.5 text-center font-bold">${visible && total != null ? fmt(total, 2) + (suffix || "") : ""}</td></tr>`;
    document.getElementById("mineral-result").innerHTML = `<table class="w-full min-w-[1120px] table-fixed border-collapse text-[11px]"><thead class="bg-gray-100"><tr><th class="sticky left-0 bg-gray-100 px-2 py-2 text-left">Concepto</th>${headerCells}<th class="px-2 py-2">Total</th></tr></thead><tbody>${row("Objetivo (% · ppm)", "objective_raw", "bg-indigo-50", null)}${row("Objetivo (kg/ha)", "objective_kg", "bg-indigo-50", sum("objective_kg"), " kg/ha")}${row("Actual (% · ppm)", "actual_raw", "bg-sky-50", null)}${row("Actual (kg/ha)", "actual_kg", "bg-sky-50", sum("actual_kg"), " kg/ha")}${row("Total (kg/ha)", "difference_kg", "bg-red-50 text-red-600", state.balance.total_kg_ha, " kg/ha")}${actionRow("GRADO FÓRMULA", "grade", "grade_pct", "bg-yellow-50", state.showGrade, sum("grade_pct"), "%")}${actionRow("NANO (kg/ha)", "nano", "nano_kg", "bg-emerald-50 text-emerald-800", state.showNano, state.balance.total_nano_kg_ha, " kg/ha")}</tbody></table>`;
  }
  function showLiebig() {
    const entries = Array.isArray(state.balance?.entries) ? state.balance.entries : [];
    const limiting = entries.reduce((best, item) => Math.abs(number(item.difference_kg) || 0) > Math.abs(number(best?.difference_kg) || 0) ? item : best, null);
    const node = document.getElementById("mineral-liebig-result");
    node.classList.remove("hidden");
    node.innerHTML = limiting && Math.abs(number(limiting.difference_kg) || 0) > 0 ? `<strong>Ley de Liebig:</strong> el nutriente limitante es <strong>${esc(limiting.name)}</strong>, con un déficit de <strong>${fmt(Math.abs(number(limiting.difference_kg)), 2)} kg/ha</strong>.` : "No se identifican déficits minerales en esta comparación.";
  }
  function openProjection() {
    const common = commonFor(state.selectedLeaf), objective = state.selectedObjective;
    const params = new URLSearchParams({ mode: "lot_vs_objective", lot_id: String(common.lot_id || ""), common_analysis_id: String(common.id || state.selectedLeaf.common_analysis_id), objective_id: String(objective.id), objective_type: "crop", objective_label: objective.crop_name || "Objetivo" });
    window.location.href = `${ENDPOINTS.comparison}?${params}`;
  }
  function open() { document.getElementById("mineral-balance-modal").classList.remove("hidden"); document.body.classList.add("overflow-hidden"); load(); }
  function close() { document.getElementById("mineral-balance-modal").classList.add("hidden"); document.body.classList.remove("overflow-hidden"); document.getElementById("open-mineral-balance")?.focus(); }

  function bind() {
    document.getElementById("open-mineral-balance").addEventListener("click", open);
    document.querySelectorAll("[data-mineral-close]").forEach(node => node.addEventListener("click", close));
    document.getElementById("mineral-objective-body").addEventListener("click", event => { const row = event.target.closest("[data-objective-id]"); if (!row) return; state.selectedObjective = state.objectives.find(item => Number(item.id) === Number(row.dataset.objectiveId)); state.balance = null; state.showGrade = false; state.showNano = false; renderObjectives(); updateButtons(); if (state.selectedLeaf) calculate(); else setStatus("Objetivo seleccionado; selecciona el análisis foliar."); });
    document.getElementById("mineral-foliar-body").addEventListener("click", event => { const row = event.target.closest("[data-leaf-id]"); if (!row) return; state.selectedLeaf = state.leaf.find(item => Number(item.id) === Number(row.dataset.leafId)); state.balance = null; state.showGrade = false; state.showNano = false; renderFoliar(); updateButtons(); if (state.selectedObjective) calculate(); else setStatus("Análisis seleccionado; selecciona el objetivo."); });
    document.getElementById("mineral-formulator").addEventListener("click", calculate);
    document.getElementById("mineral-projection").addEventListener("click", openProjection);
    document.getElementById("mineral-liebig").addEventListener("click", showLiebig);
    document.getElementById("mineral-result").addEventListener("click", event => { const button = event.target.closest("[data-mineral-reveal]"); if (!button || !state.balance) return; if (button.dataset.mineralReveal === "grade") state.showGrade = true; if (button.dataset.mineralReveal === "nano") state.showNano = true; renderBalance(); });
    document.addEventListener("keydown", event => { if (event.key === "Escape" && !document.getElementById("mineral-balance-modal").classList.contains("hidden")) close(); });
  }

  if (installMarkup()) bind();
})();
