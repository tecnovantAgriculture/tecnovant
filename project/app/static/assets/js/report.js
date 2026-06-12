/**
 * report.js — Foliar report viewer with charts, tabs, PDF/DOCX export, and results loader.
 *
 * Requires window.REPORT_CONFIG to be set by the including template with:
 *   - foliarData            (object)  analysisData.foliar
 *   - nutrientNames         (object)  nutrient_names mapping
 *   - analysisData          (object)  full analysisData
 *   - minimumLawAnalyses    (object)  minimum_law_analyses
 *   - automaticRecommendations (string)
 *   - textRecommendations   (string)
 *   - historicalData        (array)
 *   - cvData                (object)
 *   - cropName              (string)
 *   - reportTitle           (string)
 *   - reportAuthor          (string)
 *   - recommendationId      (string|null)
 *
 * Usage in template:
 *   <script>window.REPORT_CONFIG = { ... }; </script>
 *   <script src="/js/report.js"></script>
 */
(function () {
    'use strict';

    /* ------------------------------------------------------------------ */
    /*  Config retrieval                                                    */
    /* ------------------------------------------------------------------ */
    var CFG = window.REPORT_CONFIG || {};
    var foliarData = CFG.foliarData || {};
    var nutrientNames = CFG.nutrientNames || {};
    var analysisData = CFG.analysisData || {};
    var minimumLawAnalyses = CFG.minimumLawAnalyses || {};
    var automaticRecommendations = CFG.automaticRecommendations || '';
    var textRecommendations = CFG.textRecommendations || '';
    var historicalData = CFG.historicalData || [];
    var cvData = CFG.cvData || {};
    var recommendationDoses = CFG.recommendationDoses || [];

    /* ------------------------------------------------------------------ */
    /*  Helpers                                                             */
    /* ------------------------------------------------------------------ */

    /**
     * Generate a palette of colors for charts.
     * @param {number} count
     * @returns {string[]}
     */
    function generateColors(count) {
        var baseColors = [
            '#10B981', '#3B82F6', '#F59E0B', '#EF4444', '#8B5CF6',
            '#06B6D4', '#F97316', '#84CC16', '#EC4899', '#6366F1'
        ];
        if (count > baseColors.length) {
            for (var i = baseColors.length; i < count; i++) {
                var hue = (i * 137.5) % 360;
                baseColors.push('hsl(' + hue + ', 70%, 50%)');
            }
        }
        return baseColors.slice(0, count);
    }

    /**
     * Separate nutrients by type (macro vs micro).
     * @param {object} data
     * @returns {{macro: object, micro: object}}
     */
    function separateNutrientsByType(data) {
        var macro = {};
        var micro = {};
        Object.keys(data).forEach(function (key) {
            if (key !== 'id' && data[key] && typeof data[key] === 'object') {
                var nutrient = data[key];
                if (nutrient.tipo === 'Macronutrient') {
                    macro[key] = nutrient;
                } else if (nutrient.tipo === 'Micronutrient') {
                    micro[key] = nutrient;
                }
            }
        });
        return { macro: macro, micro: micro };
    }

    /**
     * Normalize a nutrient key for CV lookup (strip accents, lowercase).
     * @param {string} name
     * @returns {string}
     */
    function normalizeNutrientKey(name) {
        return name.normalize('NFD').replace(/[\u0300-\u036f]/g, '').toLowerCase();
    }

    /* ------------------------------------------------------------------ */
    /*  Chart creators                                                      */
    /* ------------------------------------------------------------------ */

    /**
     * Create a horizontal bar (progress) chart for nutrients.
     * @param {string} canvasId
     * @param {object} data
     * @param {string} title
     */
    function createProgressChart(canvasId, data, title) {
        var nutrients = Object.keys(data);
        if (nutrients.length === 0) return;

        var labels = nutrients.map(function (nutrient) {
            return nutrientNames[nutrient] || nutrient.charAt(0).toUpperCase() + nutrient.slice(1);
        });
        var percentages = nutrients.map(function (nutrient) {
            var ideal = data[nutrient].ideal;
            var actual = data[nutrient].valor;
            return ideal > 0 ? (actual / ideal) * 100 : 0;
        });

        var colors = generateColors(nutrients.length);
        var ctx = document.getElementById(canvasId);
        if (!ctx) return;
        ctx = ctx.getContext('2d');

        new Chart(ctx, {
            type: 'bar',
            data: {
                labels: labels,
                datasets: [{
                    label: '% del Ideal',
                    data: percentages,
                    backgroundColor: colors,
                    borderColor: colors.map(function (color) {
                        if (color.startsWith('hsl')) {
                            return color.replace('50%)', '40%)');
                        }
                        return color;
                    }),
                    borderWidth: 1,
                    borderRadius: 4
                }]
            },
            options: {
                indexAxis: 'y',
                responsive: true,
                maintainAspectRatio: false,
                plugins: {
                    legend: { display: false },
                    tooltip: {
                        callbacks: {
                            label: function (context) {
                                var nutrientKey = nutrients[context.dataIndex];
                                var nutrient = data[nutrientKey];
                                var percentage = context.parsed.x.toFixed(1);
                                return [
                                    percentage + '% del ideal',
                                    'Actual: ' + nutrient.valor + ' ' + nutrient.unidad,
                                    'Ideal: ' + nutrient.ideal + ' ' + nutrient.unidad
                                ];
                            }
                        }
                    }
                },
                scales: {
                    x: {
                        beginAtZero: true,
                        max: 150,
                        title: {
                            display: true,
                            text: 'Porcentaje del Valor Ideal (%)',
                            font: { size: 12, weight: 'bold' },
                            color: '#1F2937'
                        },
                        grid: { color: 'rgba(0, 0, 0, 0.1)' },
                        ticks: {
                            callback: function (value) { return value + '%'; }
                        }
                    },
                    y: {
                        grid: { display: false },
                        ticks: { font: { size: 11 } }
                    }
                },
                animation: { duration: 1000, easing: 'easeInOutQuart' }
            }
        });
    }

    /**
     * Create a horizontal bar chart for soil data.
     * @param {string} canvasId
     * @param {object} data
     * @param {string} title
     */
    function createSoilChart(canvasId, data, title) {
        var labels = Object.keys(data).filter(function (key) { return key !== 'id'; });
        var values = labels.map(function (key) { return data[key]; });
        var colors = generateColors(labels.length);

        var ctx = document.getElementById(canvasId);
        if (!ctx) return;
        ctx = ctx.getContext('2d');

        new Chart(ctx, {
            type: 'bar',
            data: {
                labels: labels.map(function (l) { return l.charAt(0).toUpperCase() + l.slice(1); }),
                datasets: [{
                    label: 'Valor',
                    data: values,
                    backgroundColor: colors,
                    borderColor: colors.map(function (color) {
                        if (color.startsWith('hsl')) {
                            return color.replace('50%)', '40%)');
                        }
                        return color;
                    }),
                    borderWidth: 1,
                    borderRadius: 4
                }]
            },
            options: {
                indexAxis: 'y',
                responsive: true,
                maintainAspectRatio: false,
                plugins: { legend: { display: false } },
                scales: {
                    x: {
                        beginAtZero: true,
                        title: {
                            display: true,
                            text: 'Valor',
                            font: { size: 12, weight: 'bold' },
                            color: '#1F2937'
                        },
                        grid: { color: 'rgba(0, 0, 0, 0.1)' }
                    },
                    y: {
                        grid: { display: false },
                        ticks: { font: { size: 11 } }
                    }
                },
                animation: { duration: 1000, easing: 'easeInOutQuart' }
            }
        });
    }

    /* ------------------------------------------------------------------ */
    /*  Tab management                                                      */
    /* ------------------------------------------------------------------ */

    function initTabs() {
        var tabs = document.querySelectorAll('.report-tabs-trigger');
        tabs.forEach(function (tab) {
            tab.addEventListener('click', function () {
                tabs.forEach(function (t) { t.classList.remove('active'); });
                this.classList.add('active');
                var targetContent = document.querySelector(this.getAttribute('data-target'));
                document.querySelectorAll('.report-tabs-content').forEach(function (content) {
                    content.classList.add('hidden');
                });
                if (targetContent) targetContent.classList.remove('hidden');
            });
        });
    }

    /* ------------------------------------------------------------------ */
    /*  PDF Export                                                          */
    /* ------------------------------------------------------------------ */

    function initExportBtn() {
        var exportBtn = document.getElementById('btnExportPDF');
        if (exportBtn) {
            exportBtn.addEventListener('click', function () {
                exportBtn.disabled = true;
                exportBtn.textContent = 'Generando PDF...';
                exportDetailedPdf().catch(function (err) {
                    console.error('Error al generar PDF:', err);
                    alert('Error al generar el PDF. Revise la consola para m\u00E1s detalles.');
                }).finally(function () {
                    exportBtn.disabled = false;
                    exportBtn.innerHTML = '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" class="h-4 w-4"><path d="M22 11.08V12a10 10 0 1 1-5.93-9.14"></path><polyline points="12 2 2 7.86 12 12"></polyline><line x1="12" y1="16" x2="12.01" y2="16"></line></svg> Exportar PDF';
                });
            });
        }
    }

    /* ------------------------------------------------------------------ */
    /*  DOCX Export                                                         */
    /* ------------------------------------------------------------------ */

    var DOCX_BTN_DEFAULT_HTML = '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" class="h-4 w-4"><path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z"></path><polyline points="14 2 14 8 20 8"></polyline><line x1="9" y1="13" x2="15" y2="13"></line><line x1="9" y1="17" x2="15" y2="17"></line></svg> Exportar DOC';

    function initExportDocxBtn() {
        var btn = document.getElementById('btnExportDOCX');
        if (!btn) return;
        btn.addEventListener('click', function () {
            var recId = CFG.recommendationId;
            if (!recId) {
                alert('No se pudo determinar el ID del informe.');
                return;
            }
            btn.disabled = true;
            btn.textContent = 'Generando DOCX...';
            var endpoint = '/api/foliage/report/' + recId + '/export/docx';
            fetch(endpoint, { credentials: 'include' })
                .then(function (resp) {
                    if (!resp.ok) {
                        throw new Error('HTTP ' + resp.status);
                    }
                    return resp.blob().then(function (blob) {
                        return { blob: blob, filename: _filenameFromResponse(resp) };
                    });
                })
                .then(function (data) {
                    var url = URL.createObjectURL(data.blob);
                    var a = document.createElement('a');
                    a.href = url;
                    a.download = data.filename || 'informe.docx';
                    document.body.appendChild(a);
                    a.click();
                    document.body.removeChild(a);
                    setTimeout(function () { URL.revokeObjectURL(url); }, 1000);
                })
                .catch(function (err) {
                    console.error('Error exportando DOCX:', err);
                    alert('No se pudo generar el archivo DOCX.');
                })
                .then(function () {
                    btn.disabled = false;
                    btn.innerHTML = DOCX_BTN_DEFAULT_HTML;
                });
        });
    }

    function _filenameFromResponse(resp) {
        var header = resp.headers.get('Content-Disposition') || '';
        var match = header.match(/filename\*=UTF-8''([^;]+)|filename="?([^";]+)"?/i);
        if (!match) return null;
        return decodeURIComponent(match[1] || match[2] || '');
    }

    /**
     * Write a numeric or NaN cell with color coding.
     */
    function writeCell(doc, val, x, yy, label) {
        if (!isNaN(val)) {
            if (label === '%P') {
                if (val < 60) doc.setTextColor(220, 38, 38);          // red
                else if (val >= 60 && val < 80) doc.setTextColor(234, 88, 12);  // orange
                else if (val > 140) doc.setTextColor(6, 95, 70);      // dark green
                else doc.setTextColor(22, 163, 74);                   // green
            } else if (label === 'Diferencia') {
                if (val < 0) doc.setTextColor(220, 38, 38);
                else if (val > 0) doc.setTextColor(234, 88, 12);
            } else { doc.setTextColor(0, 0, 0); }
            doc.text(val.toFixed(2), x, yy);
        } else { doc.setTextColor(0, 0, 0); doc.text('\u2014', x, yy); }
    }

    function nextFrame() {
        return new Promise(function (resolve) {
            requestAnimationFrame(function () { requestAnimationFrame(resolve); });
        });
    }

    function delay(ms) { return new Promise(function (r) { setTimeout(r, ms); }); }

    /**
     * Composite a (possibly transparent) canvas over white and encode as
     * JPEG. Cuts PDF size ~10x vs PNG+alpha with no visible quality loss.
     */
    function canvasToJpeg(sourceCanvas) {
        var off = document.createElement('canvas');
        off.width = sourceCanvas.width;
        off.height = sourceCanvas.height;
        var ctx = off.getContext('2d');
        ctx.fillStyle = '#ffffff';
        ctx.fillRect(0, 0, off.width, off.height);
        ctx.drawImage(sourceCanvas, 0, 0);
        return off.toDataURL('image/jpeg', 0.95);
    }

    /**
     * Convert a URL to a JPEG data URL for jsPDF embedding.
     * @param {string} url
     * @returns {Promise<string|null>}
     */
    function _loadImageDataUrl(url) {
        return new Promise(function (resolve) {
            var img = new Image();
            img.crossOrigin = 'anonymous';
            img.onload = function () {
                var cv = document.createElement('canvas');
                cv.width = img.naturalWidth;
                cv.height = img.naturalHeight;
                var ctx = cv.getContext('2d');
                ctx.drawImage(img, 0, 0);
                resolve(cv.toDataURL('image/jpeg', 0.88));
            };
            img.onerror = function () { resolve(null); };
            img.src = url;
        });
    }

    /**
     * Analyze foliar data to auto-generate findings for the PDF report.
     * @param {object} foliarData — {nutrient: {valor, ideal, tipo, ...}}
     * @param {object} mla — minimumLawAnalyses
     * @returns {{strengths:Array, risks:Array, limitingNutrient:string,
     *            limitingPct:number, priority:string, priorityColor:Array}}
     */
    function _analyzeFindings(foliarData, mla) {
        var strengths = [];
        var risks = [];
        var limitingNutrient = (mla && mla.nutriente_limitante) ? mla.nutriente_limitante : null;
        var limitingPct = null;

        Object.keys(foliarData).forEach(function (nut) {
            var d = foliarData[nut];
            if (!d || typeof d !== 'object' || nut === 'id') return;
            var ideal = (d.ideal != null && d.ideal > 0) ? d.ideal : null;
            var actual = (d.valor != null) ? d.valor : null;
            if (ideal == null || actual == null) return;
            var pct = (actual / ideal) * 100;

            var name = (CFG.nutrientNames && CFG.nutrientNames[nut]) || nut;

            if (pct >= 95 && pct <= 110) {
                strengths.push({ name: name, pct: Math.round(pct) });
            } else if (pct < 80) {
                risks.push({ name: name, pct: Math.round(pct), severity: 'Deficiencia' });
            } else if (pct > 140) {
                risks.push({ name: name, pct: Math.round(pct), severity: 'Exceso' });
            } else if (pct < 95) {
                risks.push({ name: name, pct: Math.round(pct), severity: 'Leve' });
            }

            if (limitingNutrient && name.toLowerCase() === limitingNutrient.toLowerCase()) {
                limitingPct = Math.round(pct);
            }
        });

        // Determine priority
        var deficientCount = risks.filter(function (r) { return r.severity === 'Deficiencia'; }).length;
        var priority, priorityColor;
        if (deficientCount >= 3 || (limitingPct != null && limitingPct < 70)) {
            priority = 'ALTA';
            priorityColor = [220, 38, 38];
        } else if (deficientCount >= 1 || risks.length >= 3) {
            priority = 'MEDIA';
            priorityColor = [245, 158, 11];
        } else {
            priority = 'BAJA';
            priorityColor = [22, 163, 74];
        }

        return {
            strengths: strengths,
            risks: risks,
            limitingNutrient: limitingNutrient,
            limitingPct: limitingPct,
            priority: priority,
            priorityColor: priorityColor
        };
    }

    /**
     * Export a live Chart.js instance to a high-resolution PNG with visual
     * parity to the web render: same data, colors, scales, fonts and
     * proportions. Only the backing-store resolution changes (dpr 3x),
     * so the exported image is the exact on-screen chart at print quality.
     * The chart's tab must be visible (real container dimensions) first.
     */
    async function captureChartHighRes(canvasId) {
        var chart = (window.Chart && window.Chart.getChart) ? window.Chart.getChart(canvasId) : null;
        if (!chart) return null;

        // Chart created inside a hidden tab renders at ~0 size; force a
        // resize now that the tab is visible and verify real dimensions.
        if (!chart.width || chart.width < 50 || !chart.height || chart.height < 50) {
            try { chart.resize(); } catch (e) { /* noop */ }
            await nextFrame();
        }
        if (!chart.width || chart.width < 50 || !chart.height || chart.height < 50) {
            console.warn('captureChartHighRes: chart sin dimensiones reales', canvasId, chart.width, chart.height);
            return null;
        }

        var prevDpr = chart.options.devicePixelRatio;
        var prevAnim = chart.options.animation;
        try {
            chart.options.animation = false;
            chart.options.devicePixelRatio = 3; // 3x pixels, identical CSS layout
            chart.resize();
            await nextFrame(); // deferred _resize applies (canvas buffer at 3x)
            // The entry animation started when the hidden tab was revealed may
            // still be in flight; while the animator has active animations,
            // update()/render() defer drawing to the next animator tick, so
            // the canvas would hold a mid-animation frame. stop() kills the
            // in-flight animations, update('none') sets the final layout and
            // draw() paints it synchronously before capture.
            chart.stop();
            chart.update('none');
            chart.draw();
            return {
                url: canvasToJpeg(chart.canvas),
                w: chart.canvas.width,
                h: chart.canvas.height
            };
        } catch (e) {
            console.warn('captureChartHighRes', canvasId, e);
            return null;
        } finally {
            chart.options.devicePixelRatio = prevDpr;
            chart.options.animation = prevAnim;
            try { chart.resize(); chart.update('none'); } catch (e) { /* noop */ }
        }
    }

    /**
     * Reveal hidden tab panes, force chart resize, snapshot charts and the
     * recommendation doses table, then restore the hidden state.
     * html2canvas / toDataURL cannot capture elements inside display:none.
     */
    async function captureReportImages(html2canvas) {
        var captures = { macro: null, micro: null, historical: null, recTable: null, mineralBalance: null };
        var hiddenTabs = Array.prototype.slice.call(
            document.querySelectorAll('.report-tabs-content.hidden')
        );
        hiddenTabs.forEach(function (t) { t.classList.remove('hidden'); });
        try {
            // Let layout settle so every chart container reports its real
            // width/height, then size charts to match the web render.
            await nextFrame();
            ['macroChart', 'microChart', 'soilChart', 'historicalChart'].forEach(function (cid) {
                var ch = (window.Chart && window.Chart.getChart) ? window.Chart.getChart(cid) : null;
                if (ch) { try { ch.resize(); } catch (e) { /* noop */ } }
            });
            await delay(400);

            captures.macro = await captureChartHighRes('macroChart');
            captures.micro = await captureChartHighRes('microChart');
            captures.historical = await captureChartHighRes('historicalChart');

            // Balance de Minerales — Producto Nano
            var balTableEl = document.getElementById('mineralBalanceTable');
            if (balTableEl && html2canvas) {
                try {
                    var balCanvas = await html2canvas(balTableEl, {
                        scale: 2, useCORS: true, logging: false, backgroundColor: '#ffffff'
                    });
                    if (balCanvas.width > 0 && balCanvas.height > 0) {
                        captures.mineralBalance = { url: canvasToJpeg(balCanvas), w: balCanvas.width, h: balCanvas.height };
                    }
                } catch (e) { console.warn('captura tabla balance minerales', e); }
            }

            var recTableEl = document.getElementById('recommendationDosesTable');
            if (recTableEl && html2canvas) {
                try {
                    var recCanvas = await html2canvas(recTableEl, {
                        scale: 2, useCORS: true, logging: false, backgroundColor: '#ffffff'
                    });
                    if (recCanvas.width > 0 && recCanvas.height > 0) {
                        captures.recTable = { url: canvasToJpeg(recCanvas), w: recCanvas.width, h: recCanvas.height };
                    }
                } catch (e) { console.warn('captura tabla recomendaciones', e); }
            }
        } finally {
            hiddenTabs.forEach(function (t) { t.classList.add('hidden'); });
        }
        return captures;
    }

    /**
     * Export the full report as a multi-page, executive-quality PDF using jsPDF.
     *
     * Narrative structure (9 sections):
     *   1. Portada               — clean cover, no technical data
     *   2. Resumen Ejecutivo     — KPI dashboard cards + orthophoto
     *   3. Hallazgos Principales — strengths, risks, priority
     *   4. Ley del Mínimo        — prominent visual block + explanation
     *   5. Análisis Foliar       — improved zebra-striped table
     *   6. Macronutrientes       — captured chart + detailed values
     *   7. Micronutrientes       — captured chart + detailed values
     *   8. Recomendaciones       — investment summary + product cards
     *   9. Histórico             — chart + trend cards with ▲▼ arrows
     */
    async function exportDetailedPdf() {
        var jsPDFLib = window.jspdf;
        if (!jsPDFLib || !jsPDFLib.jsPDF) {
            alert('No se pudo cargar el exportador PDF.');
            return;
        }
        var html2canvas = window.html2canvas;
        var jsPDF = jsPDFLib.jsPDF;

        // Capture charts/tables from hidden tabs BEFORE building the document.
        var captures = await captureReportImages(html2canvas);

        // Load lot orthophoto if available
        var lotImageDataUrl = null;
        if (CFG.lotImageUrl) {
            try { lotImageDataUrl = await _loadImageDataUrl(CFG.lotImageUrl); } catch (e) { /* noop */ }
        }

        var doc = new jsPDF('p', 'mm', 'a4');
        var W = 210;
        var H = 297;
        var ML = 14;
        var MR = 14;
        var CW = W - ML - MR;   // 182 mm usable width
        var y = 18;

        // ── Data shorthands ──
        var obj = CFG.productiveObjective || {};
        var mla = CFG.minimumLawAnalyses || {};
        var foliar = CFG.analysisData && CFG.analysisData.foliar ? CFG.analysisData.foliar : {};
        var soil  = CFG.analysisData && CFG.analysisData.soil ? CFG.analysisData.soil : {};
        var common = CFG.analysisData && CFG.analysisData.common ? CFG.analysisData.common : {};
        var finca = common.finca || '--';
        var lote  = common.lote || '--';
        var fecha = common.fechaAnalisis || '--';
        var crop  = CFG.cropName || '--';
        var autor = CFG.reportAuthor || 'Sistema';
        var now = new Date();
        var findings = _analyzeFindings(foliar, mla);
        var separated = separateNutrientsByType(foliar);
        var doses = CFG.recommendationDoses || [];

        // CV lookup
        var cvLookup = {};
        if (CFG.cvData && typeof CFG.cvData === 'object') {
            for (var ck in CFG.cvData) {
                if (CFG.cvData.hasOwnProperty(ck)) cvLookup[normalizeNutrientKey(ck)] = CFG.cvData[ck];
            }
        }

        // ── Local drawing helpers ──

        var checkPage = function (needed) {
            if (y + needed > H - 18) { doc.addPage(); y = 18; }
        };

        var drawSectionTitle = function (title) {
            doc.setFillColor(16, 185, 129);
            doc.rect(ML, y, 3, 8, 'F');
            doc.setFontSize(13);
            doc.setFont(undefined, 'bold');
            doc.setTextColor(17, 24, 39);
            doc.text(title, ML + 7, y + 6.5);
            y += 14;
        };

        var drawKpiCard = function (cx, cy, cw, ch, title, value, subtitle, accent) {
            doc.setFillColor(255, 255, 255);
            doc.setDrawColor(229, 231, 235);
            doc.roundedRect(cx, cy, cw, ch, 2, 2, 'FD');
            doc.setFillColor(accent[0], accent[1], accent[2]);
            doc.rect(cx + 1, cy + 1, cw - 2, 2.5, 'F');
            doc.setFontSize(6);
            doc.setTextColor(107, 114, 128);
            doc.setFont(undefined, 'bold');
            doc.text(title, cx + 3, cy + 8);
            doc.setFontSize(11);
            doc.setTextColor(17, 24, 39);
            doc.setFont(undefined, 'bold');
            doc.text(value, cx + 3, cy + 18);
            if (subtitle) {
                doc.setFontSize(5.5);
                doc.setTextColor(107, 114, 128);
                doc.setFont(undefined, 'normal');
                doc.text(subtitle, cx + 3, cy + ch - 3);
            }
        };

        function fmtNum(v, decimals) {
            if (v == null || isNaN(v)) return '--';
            return Number(v).toFixed(decimals || 1);
        }

        function pctSign(v) {
            if (v == null || isNaN(v)) return '--';
            var n = Number(v);
            return (n >= 0 ? '+' : '') + n.toFixed(1) + '%';
        }

        function getTrafficLightColor(pct) {
            if (pct < 80) return [220, 38, 38];
            if (pct < 95) return [245, 158, 11];
            if (pct <= 110) return [22, 163, 74];
            return [59, 130, 246];
        }

        // ══════════════════════════════════════════════════════════════
        //  PAGE 1 — PORTADA
        // ══════════════════════════════════════════════════════════════
        var gradientSteps = 40;
        for (var gs = 0; gs < gradientSteps; gs++) {
            var ratio = gs / gradientSteps;
            var gr = Math.round(6 + ratio * 18);
            var gg = Math.round(95 + ratio * 20);
            var gb = Math.round(70 - ratio * 10);
            doc.setFillColor(gr, gg, gb);
            doc.rect(0, (H / gradientSteps) * gs, W, (H / gradientSteps) + 1, 'F');
        }

        // Decorative lines
        doc.setDrawColor(16, 185, 129);
        doc.setLineWidth(0.4);
        doc.line(ML, 72, W - MR, 72);
        doc.line(ML, H - 48, W - MR, H - 48);

        // Title
        doc.setTextColor(255, 255, 255);
        doc.setFontSize(22); doc.setFont(undefined, 'bold');
        doc.text('Informe de An\u00E1lisis', W / 2, 88, { align: 'center' });
        doc.text('y Recomendaciones', W / 2, 99, { align: 'center' });

        doc.setFontSize(9); doc.setFont(undefined, 'normal');
        doc.setTextColor(167, 243, 208);
        doc.text('Ley del M\u00EDnimo de Liebig \u00B7 Optimizaci\u00F3n Nutricional', W / 2, 112, { align: 'center' });

        // Info block
        var infoY = 138;
        var infoPairs = [
            ['Finca', finca],
            ['Lote', lote],
            ['Cultivo', crop],
            ['Fecha de an\u00E1lisis', fecha],
            ['Autor', autor]
        ];
        doc.setTextColor(167, 243, 208);
        doc.setFontSize(8.5);
        infoPairs.forEach(function (pair) {
            var label = pair[0], val = pair[1];
            if (val && val !== '--' && val !== '') {
                doc.setFont(undefined, 'normal');
                doc.setTextColor(167, 243, 208);
                var lbl = label + ': ';
                doc.text(lbl + val, W / 2, infoY, { align: 'center' });
                infoY += 6.5;
            }
        });

        // Lot image on cover (full-width background, dimmed)
        if (lotImageDataUrl) {
            var coverImgMaxW = CW * 0.85;
            var coverImgMaxH = H - infoY - 50;
            var coverImgW = coverImgMaxW;
            var coverImgH = coverImgW / 1.6;  // landscape aspect
            if (coverImgH > coverImgMaxH) {
                coverImgH = coverImgMaxH;
                coverImgW = coverImgH * 1.6;
            }
            var coverImgX = W / 2 - coverImgW / 2;
            var coverImgY = infoY + 4;
            doc.setGState(new doc.GState({ opacity: 0.22 }));
            doc.addImage(lotImageDataUrl, 'JPEG', coverImgX, coverImgY, coverImgW, coverImgH);
            doc.setGState(new doc.GState({ opacity: 1 }));
        }

        // Bottom branding
        var fechaInforme = now.toLocaleDateString('es-CO', { day: '2-digit', month: 'long', year: 'numeric' });
        doc.setTextColor(100, 200, 150);
        doc.setFontSize(8); doc.setFont(undefined, 'italic');
        doc.text(fechaInforme, W / 2, H - 30, { align: 'center' });
        doc.setTextColor(150, 150, 150);
        doc.setFontSize(8);
        doc.text('TecnoAgro \u00B7 Nutrici\u00F3n Foliar de Precisi\u00F3n', W / 2, H - 20, { align: 'center' });

        // ══════════════════════════════════════════════════════════════
        //  PAGE 2 — RESUMEN EJECUTIVO
        // ══════════════════════════════════════════════════════════════
        doc.addPage();
        y = 18;
        drawSectionTitle('Resumen Ejecutivo');

        // Row 1 — 3 KPI cards
        var cardW = 57, cardH = 29, gap = 4.5;
        var row1y = y;
        var cx1 = ML;
        var cx2 = ML + cardW + gap;
        var cx3 = ML + (cardW + gap) * 2;

        // Aforo
        var yieldActual = obj.current && obj.current.yield ? fmtNum(obj.current.yield, 1) + ' t/ha' : '--';
        var yieldMeta  = obj.target && obj.target.yield ? 'Meta: ' + fmtNum(obj.target.yield, 1) + ' t/ha' : '';
        drawKpiCard(cx1, row1y, cardW, cardH, 'AFORO', yieldActual, yieldMeta, [16, 185, 129]);

        // Proteína
        var protActual = obj.current && obj.current.protein ? fmtNum(obj.current.protein, 1) + '%' : '--';
        var protMeta   = obj.target && obj.target.protein ? 'Meta: ' + fmtNum(obj.target.protein, 1) + '%' : '';
        drawKpiCard(cx2, row1y, cardW, cardH, 'PROTE\u00CDNA', protActual, protMeta, [59, 130, 246]);

        // Nutriente Limitante
        var limName = findings.limitingNutrient || 'Ninguno';
        var limSub = findings.limitingPct != null ? findings.limitingPct + '% del ideal' : 'Sin limitante cr\u00EDtico';
        var limColor = findings.limitingNutrient ? [220, 38, 38] : [22, 163, 74];
        drawKpiCard(cx3, row1y, cardW, cardH, 'LIMITANTE', limName, limSub, limColor);

        y = row1y + cardH + gap;

        // Row 2 — 3 KPI cards
        var row2y = y;

        // Área
        var areaVal = CFG.lotArea ? fmtNum(CFG.lotArea, 2) + ' ha' : '--';
        drawKpiCard(cx1, row2y, cardW, cardH, '\u00C1REA DEL LOTE', areaVal, 'Lote ' + lote, [107, 114, 128]);

        // Estado
        var estado = (findings.risks.length > 0) ? 'Requiere atenci\u00F3n' : '\u00D3ptimo';
        var estadoSub = findings.risks.length + ' nutrientes fuera de rango';
        var estadoColor = findings.risks.length > 0 ? [245, 158, 11] : [22, 163, 74];
        drawKpiCard(cx2, row2y, cardW, cardH, 'ESTADO', estado, estadoSub, estadoColor);

        // Brecha Productiva
        var gapYield = obj.gaps && obj.gaps.yield_pct != null ? 'Aforo: ' + pctSign(obj.gaps.yield_pct) : 'Aforo: --';
        var gapProt = obj.gaps && obj.gaps.protein_pct != null ? 'Prote\u00EDna: ' + pctSign(obj.gaps.protein_pct) : 'Prote\u00EDna: --';
        var gapSub = gapYield + '  |  ' + gapProt;
        drawKpiCard(cx3, row2y, cardW, cardH, 'BRECHA PRODUCTIVA', '', gapSub, [234, 88, 12]);

        y = row2y + cardH + gap + 2;

        // Orthophoto / NDVI
        if (lotImageDataUrl) {
            var imgMaxW = CW * 0.9;
            var imgMaxH = 100;
            var imgAspect = 3 / 2;
            var imgW = Math.min(imgMaxW, imgMaxH * imgAspect);
            var imgH = imgW / imgAspect;
            var imgX = ML + (CW - imgW) / 2;
            checkPage(imgH + 16);
            doc.setDrawColor(229, 231, 235);
            doc.setFillColor(249, 250, 251);
            doc.roundedRect(ML, y, CW, imgH + 14, 2, 2, 'FD');
            doc.setFontSize(7);
            doc.setTextColor(107, 114, 128);
            doc.setFont(undefined, 'bold');
            doc.text('ORTOFOTO / NDVI', ML + 4, y + 8);
            doc.addImage(lotImageDataUrl, 'JPEG', imgX, y + 11, imgW, imgH);
            y += imgH + 16;
        }

        // ══════════════════════════════════════════════════════════════
        //  PAGE 3 — HALLAZGOS PRINCIPALES
        // ══════════════════════════════════════════════════════════════
        doc.addPage();
        y = 18;
        drawSectionTitle('Hallazgos Principales');

        // Priority badge
        var badgeW = 44, badgeH = 10;
        var badgeX = W - MR - badgeW;
        doc.setFillColor(findings.priorityColor[0], findings.priorityColor[1], findings.priorityColor[2]);
        doc.roundedRect(badgeX, y - 12, badgeW, badgeH, 2, 2, 'F');
        doc.setFontSize(7);
        doc.setTextColor(255, 255, 255);
        doc.setFont(undefined, 'bold');
        doc.text('PRIORIDAD: ' + findings.priority, badgeX + badgeW / 2, y - 5, { align: 'center' });

        y += 2;

        // Strengths block
        if (findings.strengths.length > 0) {
            doc.setFillColor(236, 253, 243);
            doc.setDrawColor(22, 163, 74);
            doc.roundedRect(ML, y, CW, 8, 2, 2, 'FD');
            doc.setFontSize(8);
            doc.setTextColor(22, 163, 74);
            doc.setFont(undefined, 'bold');
            doc.text('\u2713 FORTALEZAS', ML + 3, y + 5.5);
            y += 12;
            doc.setFontSize(7.5);
            doc.setTextColor(17, 24, 39);
            doc.setFont(undefined, 'normal');
            var strengthTexts = findings.strengths.map(function (s) {
                return s.name + ' al ' + s.pct + '% del ideal';
            });
            if (strengthTexts.length > 0) {
                var sLines = doc.splitTextToSize(strengthTexts.join('  \u00B7  '), CW - 6);
                sLines.forEach(function (line) {
                    checkPage(5);
                    doc.text(line, ML + 3, y);
                    y += 5;
                });
            }
            y += 2;
        }

        // Risks block
        if (findings.risks.length > 0) {
            checkPage(8);
            doc.setFillColor(254, 242, 242);
            doc.setDrawColor(220, 38, 38);
            doc.roundedRect(ML, y, CW, 8, 2, 2, 'FD');
            doc.setFontSize(8);
            doc.setTextColor(220, 38, 38);
            doc.setFont(undefined, 'bold');
            doc.text('\u26A0 RIESGOS', ML + 3, y + 5.5);
            y += 12;
            doc.setFontSize(7.5);
            doc.setTextColor(17, 24, 39);
            doc.setFont(undefined, 'normal');
            findings.risks.forEach(function (r) {
                checkPage(5);
                var severityLabel = r.severity === 'Deficiencia' ? ' (Deficiencia)' :
                                    r.severity === 'Exceso' ? ' (Exceso)' : ' (Leve)';
                doc.text('\u2022 ' + r.name + severityLabel + ' \u2014 ' + r.pct + '% del ideal', ML + 3, y);
                y += 5;
            });
            y += 2;
        }

        // Impact & limiting nutrient
        checkPage(14);
        doc.setFillColor(249, 250, 251);
        doc.setDrawColor(229, 231, 235);
        doc.roundedRect(ML, y, CW, 14, 2, 2, 'FD');
        doc.setFontSize(7.5);
        doc.setFont(undefined, 'bold');
        doc.setTextColor(17, 24, 39);
        doc.text('Impacto esperado:', ML + 3, y + 4.5);
        doc.setFont(undefined, 'normal');
        var impactText = findings.limitingNutrient
            ? 'Corregir ' + findings.limitingNutrient + ' puede destrabar el potencial productivo del cultivo. Los nutrientes por debajo del 80% del ideal est\u00E1n limitando activamente el rendimiento y la calidad.'
            : 'Los nutrientes se encuentran dentro de rangos aceptables. Mantener el programa de fertilizaci\u00F3n actual y monitorear peri\u00F3dicamente.';
        var impactLines = doc.splitTextToSize(impactText, CW - 6);
        impactLines.forEach(function (line) {
            doc.text(line, ML + 3, y + 8.5 + (impactLines.indexOf(line) * 4));
        });
        y += 18;

        // ══════════════════════════════════════════════════════════════
        //  PAGE 4 — LEY DEL MÍNIMO DE LIEBIG
        // ══════════════════════════════════════════════════════════════
        doc.addPage();
        y = 18;
        drawSectionTitle('Ley del M\u00EDnimo de Liebig');

        // Big visual block for limiting nutrient
        var blockH = 36, blockW = CW * 0.55;
        var blockX = ML + (CW - blockW) / 2;
        checkPage(blockH + 20);
        doc.setFillColor(6, 95, 70);
        doc.setDrawColor(16, 185, 129);
        doc.roundedRect(blockX, y, blockW, blockH, 3, 3, 'FD');
        doc.setTextColor(167, 243, 208);
        doc.setFontSize(8);
        doc.setFont(undefined, 'normal');
        doc.text('NUTRIENTE LIMITANTE', blockX + blockW / 2, y + 9, { align: 'center' });
        doc.setTextColor(255, 255, 255);
        doc.setFontSize(18);
        doc.setFont(undefined, 'bold');
        doc.text(limName, blockX + blockW / 2, y + 24, { align: 'center' });
        if (findings.limitingPct != null) {
            doc.setFontSize(7.5);
            doc.setTextColor(167, 243, 208);
            doc.setFont(undefined, 'normal');
            doc.text(findings.limitingPct + '% del ideal', blockX + blockW / 2, y + 31, { align: 'center' });
        }
        y += blockH + 6;

        // Mini barrel illustration (textual)
        doc.setFontSize(8);
        doc.setTextColor(107, 114, 128);
        doc.setFont(undefined, 'italic');
        doc.text('El crecimiento del cultivo est\u00E1 limitado por el nutriente m\u00E1s escaso,', ML + 2, y);
        y += 4.5;
        doc.text('como la duela m\u00E1s corta de un barril determina el nivel de agua.', ML + 2, y);
        y += 8;

        // Nutrient summary table (compact)
        var foliarKeys = Object.keys(foliar).filter(function (k) { return k !== 'id' && typeof foliar[k] === 'object'; });
        if (foliarKeys.length > 0) {
            doc.setFontSize(7);
            doc.setFillColor(16, 185, 129);
            doc.setTextColor(255, 255, 255);
            doc.setFont(undefined, 'bold');
            doc.rect(ML, y, CW, 5, 'F');
            var tCols = [CW * 0.26, CW * 0.16, CW * 0.16, CW * 0.16, CW * 0.26];
            var tHeaders = ['Nutriente', '% Ideal', 'I', 'R', 'Diferencia'];
            var tx = ML + 1.5;
            tHeaders.forEach(function (hdr, hi) {
                doc.text(hdr, tx, y + 3.5);
                tx += tCols[hi];
            });
            y += 5;

            doc.setFont(undefined, 'normal');
            doc.setTextColor(17, 24, 39);
            foliarKeys.forEach(function (nut, i) {
                checkPage(5.5);
                if (i % 2 === 1) {
                    doc.setFillColor(249, 250, 251);
                    doc.rect(ML, y, CW, 5, 'F');
                }
                var d = foliar[nut];
                var act = (d.valor != null) ? d.valor : null;
                var targ = (d.ideal != null && d.ideal > 0) ? d.ideal : null;
                var p = (act != null && targ != null) ? (act / targ) * 100 : NaN;
                var diff = (act != null && targ != null) ? 100 - p : NaN;
                var normKey = normalizeNutrientKey(nut);
                var cv = cvLookup[normKey] != null ? cvLookup[normKey] : null;
                var iVal = (!isNaN(p) && cv != null) ? Math.abs(p - 100) * cv / 100 : NaN;
                var rVal = NaN;
                if (!isNaN(iVal)) { rVal = p > 100 ? p - iVal : p + iVal; if (rVal < 88) rVal = 88; if (rVal > 108) rVal = 108; }

                var displayName = (CFG.nutrientNames && CFG.nutrientNames[nut]) || nut.charAt(0).toUpperCase() + nut.slice(1);
                tx = ML + 1.5;
                doc.setFontSize(6.5);
                doc.text(displayName, tx, y + 3.5); tx += tCols[0];
                doc.setTextColor(getTrafficLightColor(p)[0], getTrafficLightColor(p)[1], getTrafficLightColor(p)[2]);
                doc.text(!isNaN(p) ? p.toFixed(0) + '%' : '\u2014', tx, y + 3.5); tx += tCols[1];
                doc.setTextColor(17, 24, 39);
                doc.text(!isNaN(iVal) ? iVal.toFixed(1) : '\u2014', tx, y + 3.5); tx += tCols[2];
                doc.text(!isNaN(rVal) ? rVal.toFixed(1) : '\u2014', tx, y + 3.5); tx += tCols[3];
                doc.setTextColor(diff < 0 ? 220 : diff > 0 ? 234 : 17, diff < 0 ? 38 : diff > 0 ? 88 : 24, diff < 0 ? 38 : diff > 0 ? 12 : 39);
                doc.text(!isNaN(diff) ? (diff > 0 ? '+' : '') + diff.toFixed(0) + '%' : '\u2014', tx, y + 3.5);
                doc.setTextColor(17, 24, 39);
                y += 5;
            });
            y += 4;
        }

        // ══════════════════════════════════════════════════════════════
        //  PAGE 5 — ANÁLISIS FOLIAR DETALLADO
        // ══════════════════════════════════════════════════════════════
        doc.addPage();
        y = 18;
        drawSectionTitle('An\u00E1lisis Foliar Detallado');

        if (foliarKeys.length > 0) {
            doc.setFontSize(6.5);
            doc.setFillColor(6, 95, 70);
            doc.setTextColor(255, 255, 255);
            doc.setFont(undefined, 'bold');
            doc.rect(ML, y, CW, 5.5, 'F');
            var ftCols = [CW * 0.18, CW * 0.10, CW * 0.10, CW * 0.08, CW * 0.10, CW * 0.16, CW * 0.28];
            var ftLabels = ['Nutriente', 'S\u00EDmb.', 'Actual', 'Unid.', 'Ideal', 'Tipo', '% Ideal'];
            var fcx = ML + 1.5;
            ftLabels.forEach(function (lbl, i) {
                doc.text(lbl, fcx, y + 3.8);
                fcx += ftCols[i];
            });
            y += 5.5;

            doc.setFont(undefined, 'normal');
            doc.setTextColor(17, 24, 39);
            foliarKeys.forEach(function (nut, i) {
                checkPage(6);
                if (i % 2 === 1) { doc.setFillColor(249, 250, 251); doc.rect(ML, y, CW, 5.5, 'F'); }
                var d = foliar[nut];
                var actual = (d.valor != null) ? d.valor : '--';
                var ideal  = (d.ideal != null) ? d.ideal : '--';
                var unit   = d.unidad || '';
                var tipo   = d.tipo || '';
                var pctVal = (ideal && actual && ideal > 0) ? (actual / ideal * 100) : null;
                var sym    = (CFG.nutrientNames && CFG.nutrientNames[nut]) || nut.toUpperCase();

                fcx = ML + 1.5;
                doc.setFontSize(6.5);
                doc.text(nut.charAt(0).toUpperCase() + nut.slice(1), fcx, y + 3.8); fcx += ftCols[0];
                doc.text(sym, fcx, y + 3.8); fcx += ftCols[1];
                doc.text(String(actual), fcx, y + 3.8); fcx += ftCols[2];
                doc.text(String(unit), fcx, y + 3.8); fcx += ftCols[3];
                doc.text(String(ideal), fcx, y + 3.8); fcx += ftCols[4];
                doc.text(tipo.length > 4 ? tipo.slice(0, 4) : tipo, fcx, y + 3.8); fcx += ftCols[5];

                if (pctVal != null) {
                    var tc = getTrafficLightColor(pctVal);
                    doc.setTextColor(tc[0], tc[1], tc[2]);
                    doc.setFont(undefined, 'bold');
                }
                doc.text(pctVal != null ? pctVal.toFixed(0) + '%' : '\u2014', fcx, y + 3.8);
                doc.setTextColor(17, 24, 39);
                doc.setFont(undefined, 'normal');
                y += 5.5;
            });
        }
        y += 4;

        // Soil data (if present)
        var soilKeys = Object.keys(soil).filter(function (k) { return k !== 'id' && soil[k] != null; });
        if (soilKeys.length > 0) {
            checkPage(14);
            y += 4;
            doc.setFillColor(16, 185, 129);
            doc.rect(ML, y, 2.5, 7, 'F');
            doc.setFontSize(10);
            doc.setFont(undefined, 'bold');
            doc.setTextColor(17, 24, 39);
            doc.text('An\u00E1lisis de Suelo', ML + 6, y + 5.5);
            y += 10;
            soilKeys.forEach(function (key) {
                checkPage(5);
                doc.setFontSize(7);
                doc.setTextColor(107, 114, 128);
                doc.setFont(undefined, 'normal');
                doc.text(key.charAt(0).toUpperCase() + key.slice(1) + ':', ML + 3, y);
                doc.setFont(undefined, 'bold');
                doc.setTextColor(17, 24, 39);
                doc.text(String(soil[key]), ML + 50, y);
                y += 5;
            });
        }

        // ══════════════════════════════════════════════════════════════
        //  PAGE 6 — MACRONUTRIENTES
        // ══════════════════════════════════════════════════════════════
        if (Object.keys(separated.macro).length > 0 || captures.macro) {
            doc.addPage();
            y = 18;
            drawSectionTitle('Macronutrientes');

            if (captures.macro) {
                var macW = CW;
                var macH = (captures.macro.h / captures.macro.w) * CW;
                var macMaxH = H - y - 60;
                if (macH > macMaxH) { macW = macW * (macMaxH / macH); macH = macMaxH; }
                doc.addImage(captures.macro.url, 'JPEG', ML + (CW - macW) / 2, y, macW, macH);
                y += macH + 8;
            }

            var macKeys = Object.keys(separated.macro);
            if (macKeys.length > 0) {
                doc.setFontSize(9);
                doc.setFont(undefined, 'bold');
                doc.setTextColor(22, 163, 74);
                doc.text('Valores detallados', ML, y);
                y += 6;
                doc.setFont(undefined, 'normal');
                macKeys.forEach(function (nut) {
                    checkPage(5);
                    var d = separated.macro[nut];
                    var sym = (CFG.nutrientNames && CFG.nutrientNames[nut]) || nut.toUpperCase();
                    var act = (d.valor != null) ? d.valor.toFixed(2) : '--';
                    var idl = (d.ideal != null) ? d.ideal.toFixed(2) : '--';
                    var pct = (d.valor != null && d.ideal != null && d.ideal > 0) ? (d.valor / d.ideal * 100).toFixed(0) : '--';
                    doc.setFontSize(8);
                    doc.setTextColor(17, 24, 39);
                    doc.text(sym + ': ' + act + ' ' + (d.unidad || ''), ML, y);
                    doc.setFontSize(7);
                    doc.setTextColor(107, 114, 128);
                    doc.text('Ideal: ' + idl + '  |  ' + pct + '% del ideal', ML + 42, y);
                    y += 5;
                });
            }
        }

        // ══════════════════════════════════════════════════════════════
        //  PAGE 7 — MICRONUTRIENTES
        // ══════════════════════════════════════════════════════════════
        if (Object.keys(separated.micro).length > 0 || captures.micro) {
            doc.addPage();
            y = 18;
            drawSectionTitle('Micronutrientes');

            if (captures.micro) {
                var micW = CW;
                var micH = (captures.micro.h / captures.micro.w) * CW;
                var micMaxH = H - y - 60;
                if (micH > micMaxH) { micW = micW * (micMaxH / micH); micH = micMaxH; }
                doc.addImage(captures.micro.url, 'JPEG', ML + (CW - micW) / 2, y, micW, micH);
                y += micH + 8;
            }

            var micKeys = Object.keys(separated.micro);
            if (micKeys.length > 0) {
                doc.setFontSize(9);
                doc.setFont(undefined, 'bold');
                doc.setTextColor(59, 130, 246);
                doc.text('Valores detallados', ML, y);
                y += 6;
                doc.setFont(undefined, 'normal');
                micKeys.forEach(function (nut) {
                    checkPage(5);
                    var d = separated.micro[nut];
                    var sym = (CFG.nutrientNames && CFG.nutrientNames[nut]) || nut.toUpperCase();
                    var act = (d.valor != null) ? d.valor.toFixed(2) : '--';
                    var idl = (d.ideal != null) ? d.ideal.toFixed(2) : '--';
                    var pct = (d.valor != null && d.ideal != null && d.ideal > 0) ? (d.valor / d.ideal * 100).toFixed(0) : '--';
                    doc.setFontSize(8);
                    doc.setTextColor(17, 24, 39);
                    doc.text(sym + ': ' + act + ' ' + (d.unidad || ''), ML, y);
                    doc.setFontSize(7);
                    doc.setTextColor(107, 114, 128);
                    doc.text('Ideal: ' + idl + '  |  ' + pct + '% del ideal', ML + 42, y);
                    y += 5;
                });
            }
        }

        // ══════════════════════════════════════════════════════════════
        //  PAGE 8 — RECOMENDACIONES
        // ══════════════════════════════════════════════════════════════
        doc.addPage();
        y = 18;
        drawSectionTitle('Recomendaciones');

        // Balance de Minerales — Producto Nano (captured from DOM)
        if (captures.mineralBalance) {
            checkPage(20);
            doc.setFontSize(9);
            doc.setFont(undefined, 'bold');
            doc.setTextColor(17, 24, 39);
            doc.text('Balance de Minerales \u2014 Producto Nano', ML, y);
            y += 5;
            var balW = CW;
            var balH = (captures.mineralBalance.h / captures.mineralBalance.w) * CW;
            var balMaxH = H - y - 22;
            if (balH > balMaxH) { balW = balW * (balMaxH / balH); balH = balMaxH; }
            if (y + balH > H - 18) { doc.addPage(); y = 18; }
            doc.addImage(captures.mineralBalance.url, 'JPEG', ML, y, balW, balH);
            y += balH + 8;
        }

        // ══════════════════════════════════════════════════════════════
        //  PAGE 9 — HISTÓRICO Y TENDENCIAS
        // ══════════════════════════════════════════════════════════════
        if (CFG.historicalData && CFG.historicalData.length > 1) {
            doc.addPage();
            y = 18;
            drawSectionTitle('Hist\u00F3rico y Tendencias');

            // Historical chart
            if (captures.historical) {
                var histW = CW;
                var histH = (captures.historical.h / captures.historical.w) * CW;
                var histMaxH = H - y - 50;
                if (histH > histMaxH) { histW = histW * (histMaxH / histH); histH = histMaxH; }
                doc.addImage(captures.historical.url, 'JPEG', ML + (CW - histW) / 2, y, histW, histH);
                y += histH + 6;
            }

            // Trend cards
            var trends = CFG.trends || {};
            var trendKeys = Object.keys(trends);
            if (trendKeys.length > 0) {
                checkPage(10);
                doc.setFontSize(8);
                doc.setFont(undefined, 'bold');
                doc.setTextColor(17, 24, 39);
                doc.text('Variaciones observadas', ML, y);
                y += 6;

                var trendCardW = 56, trendCardH = 14, trendGap = 2.5;
                var cardsPerRow = Math.floor(CW / (trendCardW + trendGap));
                trendKeys.forEach(function (nutrient, ti) {
                    var trend = trends[nutrient];
                    if (!trend || trend.percentage_change == null) return;
                    var col = ti % cardsPerRow;
                    var row = Math.floor(ti / cardsPerRow);
                    var tcx = ML + col * (trendCardW + trendGap);
                    var tcy = y + row * (trendCardH + trendGap);

                    checkPage(trendCardH + 4);
                    var isUp = trend.percentage_change >= 0;
                    var arrow = isUp ? '\u25B2' : '\u25BC';
                    var tColor = isUp ? [22, 163, 74] : [220, 38, 38];
                    doc.setFillColor(255, 255, 255);
                    doc.setDrawColor(229, 231, 235);
                    doc.roundedRect(tcx, tcy, trendCardW, trendCardH, 2, 2, 'FD');
                    doc.setFontSize(5.5);
                    doc.setTextColor(107, 114, 128);
                    doc.setFont(undefined, 'bold');
                    doc.text(nutrient, tcx + 2.5, tcy + 4.5);
                    doc.setFontSize(7);
                    doc.setTextColor(tColor[0], tColor[1], tColor[2]);
                    doc.setFont(undefined, 'bold');
                    var changeStr = arrow + ' ' + Math.abs(trend.percentage_change).toFixed(1) + '%';
                    doc.text(changeStr, tcx + 2.5, tcy + 10);
                    doc.setFontSize(5);
                    doc.setTextColor(107, 114, 128);
                    doc.setFont(undefined, 'normal');
                    doc.text(trend.initial_value.toFixed(1) + '% \u2192 ' + trend.final_value.toFixed(1) + '%', tcx + 2.5, tcy + 13);
                });
                y += Math.ceil(trendKeys.length / cardsPerRow) * (trendCardH + trendGap) + 4;
            }

            // Historical data table (compact)
            var allHistNutrients = {};
            CFG.historicalData.forEach(function (e) {
                for (var hk in e) { if (hk !== 'fecha') allHistNutrients[hk] = true; }
            });
            var histNuts = Object.keys(allHistNutrients);
            if (histNuts.length > 0 && CFG.historicalData.length <= 12) {
                checkPage(8);
                var hColW = CW / (histNuts.length + 1);
                doc.setFontSize(5.5);
                doc.setFillColor(16, 185, 129);
                doc.setTextColor(255, 255, 255);
                doc.setFont(undefined, 'bold');
                doc.rect(ML, y, CW, 4.5, 'F');
                doc.text('Fecha', ML + 1, y + 3.2);
                histNuts.forEach(function (n, ni) {
                    doc.text(n, ML + hColW * (ni + 1) + 1, y + 3.2);
                });
                y += 4.5;

                doc.setFont(undefined, 'normal');
                doc.setTextColor(17, 24, 39);
                CFG.historicalData.forEach(function (entry, ei) {
                    checkPage(4.5);
                    if (ei % 2 === 1) { doc.setFillColor(249, 250, 251); doc.rect(ML, y, CW, 4.5, 'F'); }
                    doc.text(entry.fecha || '', ML + 1, y + 3.2);
                    histNuts.forEach(function (nut, ni) {
                        var val = entry[nut];
                        if (val != null) doc.text(String(val), ML + hColW * (ni + 1) + 1, y + 3.2);
                    });
                    y += 4.5;
                });
            }
        }

        // ══════════════════════════════════════════════════════════════
        //  GLOBAL HEADERS & FOOTERS (applied after all pages built)
        // ══════════════════════════════════════════════════════════════
        var pageCount = doc.internal.getNumberOfPages();
        for (var pi = 1; pi <= pageCount; pi++) {
            doc.setPage(pi);
            // Footer on every page
            doc.setFontSize(6);
            doc.setTextColor(156, 163, 175);
            doc.text('Informe Agron\u00F3mico \u00B7 TecnoAgro \u00B7 P\u00E1gina ' + pi + ' de ' + pageCount, W / 2, H - 8, { align: 'center' });
            // Header on non-cover pages
            if (pi > 1) {
                var headerLine = finca + ' \u00B7 ' + lote + ' \u00B7 ' + fecha;
                doc.setFontSize(6);
                doc.text(headerLine, ML, 10);
                doc.setDrawColor(229, 231, 235);
                doc.line(ML, 11.5, W - MR, 11.5);
            }
        }

        var safeLote = lote.replace(/[^a-zA-Z0-9\u00E1\u00E9\u00ED\u00F3\u00FA\u00C1\u00C9\u00CD\u00D3\u00DA\u00F1\u00D1 ]/g, '').trim();
        doc.save('informe_' + safeLote + '_' + now.toISOString().slice(0, 10) + '.pdf');
    }

    /* ------------------------------------------------------------------ */
    /*  Historical chart (second script block)                              */
    /* ------------------------------------------------------------------ */

    function initHistoricalChart() {
        if (!historicalData || historicalData.length < 2) return;
        var canvas = document.getElementById('historicalChart');
        if (!canvas) return;

        var labels = [];
        var datasets = {};

        historicalData.forEach(function (entry) {
            labels.push(entry.fecha);
            for (var nutrient in entry) {
                if (entry.hasOwnProperty(nutrient) && nutrient !== 'fecha') {
                    if (!datasets[nutrient]) {
                        datasets[nutrient] = {
                            label: nutrient,
                            data: [],
                            fill: false,
                            borderColor: '#' + Math.floor(Math.random() * 16777215).toString(16),
                            tension: 0.1
                        };
                    }
                    datasets[nutrient].data.push(entry[nutrient]);
                }
            }
        });

        var ctx = canvas.getContext('2d');
        new Chart(ctx, {
            type: 'line',
            data: {
                labels: labels,
                datasets: Object.keys(datasets).map(function (k) { return datasets[k]; })
            },
            options: {
                responsive: true,
                scales: {
                    x: { title: { display: true, text: 'Fecha' } },
                    y: { title: { display: true, text: 'Valor' } }
                }
            }
        });
    }

    /* ------------------------------------------------------------------ */
    /*  Historical nutrient comparison table                                */
    /* ------------------------------------------------------------------ */

    function initHistoricalTable() {
        var wrap = document.getElementById('historicalTableWrap');
        if (!wrap) return;
        if (!historicalData || historicalData.length === 0) return;

        var nutrientKeys = {};
        historicalData.forEach(function (entry) {
            for (var k in entry) {
                if (entry.hasOwnProperty(k) && k !== 'fecha') nutrientKeys[k] = true;
            }
        });
        var cols = Object.keys(nutrientKeys);
        if (cols.length === 0) return;

        var html = '<table class="min-w-full text-sm border border-gray-200 dark:border-gray-700">';
        html += '<thead class="bg-gray-100 dark:bg-gray-800"><tr>';
        html += '<th class="px-3 py-2 text-left font-semibold">Fecha</th>';
        cols.forEach(function (c) {
            var label = c.charAt(0).toUpperCase() + c.slice(1);
            html += '<th class="px-3 py-2 text-right font-semibold">' + label + '</th>';
        });
        html += '</tr></thead><tbody>';
        historicalData.forEach(function (entry, i) {
            html += '<tr class="' + (i % 2 ? 'bg-gray-50 dark:bg-gray-800/50' : '') + '">';
            html += '<td class="px-3 py-2 whitespace-nowrap">' + (entry.fecha || '') + '</td>';
            cols.forEach(function (c) {
                var val = entry[c];
                var text = (val === null || val === undefined) ? '—' : val;
                html += '<td class="px-3 py-2 text-right">' + text + '</td>';
            });
            html += '</tr>';
        });
        html += '</tbody></table>';
        wrap.innerHTML = html;
    }

    /* ------------------------------------------------------------------ */
    /*  Results tab loader                                                  */
    /* ------------------------------------------------------------------ */

    function initResultsLoader() {
        var recommendationId = CFG.recommendationId || null;
        var resultsSection = document.getElementById('results-content');
        if (!resultsSection) return;

        if (!recommendationId) {
            resultsSection.innerHTML = '<p class="text-gray-400 text-sm">ID de recomendaci\u00F3n no disponible.</p>';
            return;
        }

        fetch('/api/foliage/report/recommendations/' + recommendationId + '/results', {
            credentials: 'include'
        })
            .then(function (r) { return r.json(); })
            .then(function (data) {
                resultsSection.innerHTML = renderResults(data);
            })
            .catch(function (err) {
                resultsSection.innerHTML = '<p class="text-red-500 text-sm">Error al cargar resultados: ' + (err.message || '') + '</p>';
                console.error('Error loading results:', err);
            });

        function renderResults(data) {
            if (!data.success) {
                return '<p class="text-red-500 text-sm">No se pudieron cargar los resultados.</p>';
            }

            var s = data.result_summary;
            var rec = data.recommendation;

            var appliedHtml = rec && rec.applied
                ? '<span class="text-green-600 font-medium">\u2713 Aplicada</span>'
                : '<span class="text-yellow-600 font-medium">\u23F3 Pendiente de aplicaci\u00F3n</span>';

            var statusHtml = '';
            if (s && s.status === 'PENDING_PRODUCTION') {
                statusHtml = '<tr><td colspan="2" class="px-4 py-3 text-gray-500 italic">' +
                    'Producci\u00F3n no registrada a\u00FAn</td></tr>';
            } else {
                var statusClass = s && s.success ? 'text-green-700 font-bold' : 'text-red-600 font-bold';
                statusHtml =
                    '<tr><td class="px-4 py-2 font-medium text-gray-700">Producci\u00F3n registrada</td>' +
                    '<td class="px-4 py-2">' + (s && s.actual_kg !== null ? s.actual_kg + ' kg/ha' : '\u2014') + '</td></tr>' +
                    '<tr><td class="px-4 py-2 font-medium text-gray-700">Objetivo</td>' +
                    '<td class="px-4 py-2">' + (s && s.target_kg !== null ? s.target_kg + ' kg/ha' : 'No definido') + '</td></tr>' +
                    '<tr><td class="px-4 py-2 font-medium text-gray-700">Diferencia</td>' +
                    '<td class="px-4 py-2">' +
                    (s && s.delta_kg !== null ? (s.delta_kg >= 0 ? '+' : '') + s.delta_kg + ' kg/ha (' +
                        (s.delta_pct >= 0 ? '+' : '') + s.delta_pct + '%)' : '\u2014') +
                    '</td></tr>' +
                    '<tr><td class="px-4 py-2 font-medium text-gray-700">Estado</td>' +
                    '<td class="px-4 py-2 ' + statusClass + '">' + (s ? s.status_text : '') + '</td></tr>';
            }

            return '<table class="w-full text-sm border border-gray-200 rounded overflow-hidden">' +
                '<tbody>' +
                '<tr class="bg-white"><td class="px-4 py-2 font-medium text-gray-700">Recomendaci\u00F3n aplicada</td>' +
                '<td class="px-4 py-2">' + appliedHtml + '</td></tr>' +
                statusHtml +
                '</tbody></table>';
        }
    }

    /* ------------------------------------------------------------------ */
    /*  Init on DOM ready                                                    */
    /* ------------------------------------------------------------------ */
    function initAll() {
        // Nutrient charts
        var separated = separateNutrientsByType(foliarData);
        if (Object.keys(separated.macro).length > 0) {
            createProgressChart('macroChart', separated.macro, 'Macronutrientes');
        } else {
            var macroContainer = document.getElementById('macroChart');
            if (macroContainer && macroContainer.parentElement) {
                macroContainer.parentElement.innerHTML = '<div class="flex items-center justify-center h-96"><p class="text-gray-500 text-lg">No hay macronutrientes disponibles</p></div>';
            }
        }

        if (Object.keys(separated.micro).length > 0) {
            createProgressChart('microChart', separated.micro, 'Micronutrientes');
        } else {
            var microContainer = document.getElementById('microChart');
            if (microContainer && microContainer.parentElement) {
                microContainer.parentElement.innerHTML = '<div class="flex items-center justify-center h-96"><p class="text-gray-500 text-lg">No hay micronutrientes disponibles</p></div>';
            }
        }

        // Soil chart
        var soilData = analysisData && analysisData.soil ? analysisData.soil : {};
        var soilChartCanvas = document.getElementById('soilChart');
        if (soilChartCanvas) {
            if (soilData && Object.keys(soilData).length > 1) {
                createSoilChart('soilChart', soilData, 'An\u00E1lisis de Suelo');
            } else {
                var soilContainer = soilChartCanvas.parentElement;
                if (soilContainer) {
                    soilContainer.innerHTML = '<div class="flex items-center justify-center h-96"><p class="text-gray-500 text-lg">No hay datos de suelo disponibles para graficar</p></div>';
                }
            }
        }

        // Tabs, PDF export, historical chart, results loader
        initTabs();
        initExportBtn();
        initExportDocxBtn();
        initHistoricalChart();
        initHistoricalTable();
        initResultsLoader();
    }

    if (document.readyState === 'loading') {
        document.addEventListener('DOMContentLoaded', initAll);
    } else {
        initAll();
    }
})();
