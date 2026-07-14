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

    var PDF_BTN_DEFAULT_HTML = '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" class="h-4 w-4"><path d="M22 11.08V12a10 10 0 1 1-5.93-9.14"></path><polyline points="12 2 2 7.86 12 12"></polyline><line x1="12" y1="16" x2="12.01" y2="16"></line></svg> Exportar PDF';

    function initExportBtn() {
        var exportBtn = document.getElementById('btnExportPDF');
        if (!exportBtn) return;
        exportBtn.addEventListener('click', function () {
            var recId = CFG.recommendationId;
            if (!recId) {
                alert('No se pudo determinar el ID del informe.');
                return;
            }
            exportBtn.disabled = true;
            exportBtn.textContent = 'Generando PDF...';
            fetch('/api/foliage/report/' + recId + '/export/pdf', { credentials: 'include' })
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
                    a.download = data.filename || 'informe_agronomico.pdf';
                    document.body.appendChild(a);
                    a.click();
                    document.body.removeChild(a);
                    setTimeout(function () { URL.revokeObjectURL(url); }, 1000);
                })
                .catch(function (err) {
                    console.error('Error exportando PDF:', err);
                    alert('No se pudo generar el archivo PDF.');
                })
                .then(function () {
                    exportBtn.disabled = false;
                    exportBtn.innerHTML = PDF_BTN_DEFAULT_HTML;
                });
        });
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
        var recId = CFG.recommendationId;
        if (!recId) {
            alert('No se pudo determinar el ID del informe.');
            return;
        }
        var resp = await fetch('/api/foliage/report/' + recId + '/export/pdf', { credentials: 'include' });
        if (!resp.ok) {
            throw new Error('HTTP ' + resp.status);
        }
        var blob = await resp.blob();
        var url = URL.createObjectURL(blob);
        var a = document.createElement('a');
        a.href = url;
        a.download = _filenameFromResponse(resp) || 'informe_agronomico.pdf';
        document.body.appendChild(a);
        a.click();
        document.body.removeChild(a);
        setTimeout(function () { URL.revokeObjectURL(url); }, 1000);
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
