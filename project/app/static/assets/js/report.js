/**
 * report.js — Foliar report viewer with charts, tabs, PDF export, and results loader.
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
                exportDetailedPdf();
            });
        }
    }

    /**
     * Write a numeric or NaN cell with color coding.
     */
    function writeCell(doc, val, x, yy, label) {
        if (!isNaN(val)) {
            if (label === '%P') {
                if (val < 88) doc.setTextColor(220, 38, 38);
                else if (val > 108) doc.setTextColor(234, 88, 12);
                else doc.setTextColor(22, 163, 74);
            } else if (label === 'Diferencia') {
                if (val < 0) doc.setTextColor(220, 38, 38);
                else if (val > 0) doc.setTextColor(234, 88, 12);
            } else { doc.setTextColor(0, 0, 0); }
            doc.text(val.toFixed(2), x, yy);
        } else { doc.setTextColor(0, 0, 0); doc.text('\u2014', x, yy); }
    }

    /**
     * Export the full report as a multi-page PDF using jsPDF.
     */
    function exportDetailedPdf() {
        var jsPDFLib = window.jspdf;
        if (!jsPDFLib || !jsPDFLib.jsPDF) {
            alert('No se pudo cargar el exportador PDF.');
            return;
        }
        var jsPDF = jsPDFLib.jsPDF;

        var doc = new jsPDF('p', 'mm', 'a4');
        var W = doc.internal.pageSize.getWidth();
        var H = doc.internal.pageSize.getHeight();
        var ML = 16;
        var MR = 16;
        var CW = W - ML - MR;
        var y = 16;

        var checkPage = function (needed) {
            if (y + needed > H - 20) { doc.addPage(); y = 20; }
        };
        var drawLine = function () {
            doc.setDrawColor(229, 231, 235);
            doc.line(ML, y, W - MR, y);
            y += 3;
        };
        var drawField = function (label, value) {
            if (!value || value === '--' || value === '') return;
            doc.setFontSize(8); doc.setFont(undefined, 'normal');
            doc.setTextColor(107, 114, 128);
            doc.text(label + ':', ML, y);
            var lw = doc.getTextWidth(label + ':  ');
            doc.setTextColor(17, 24, 39); doc.setFont(undefined, 'bold');
            doc.text(String(value), ML + lw, y);
            doc.setTextColor(107, 114, 128); doc.setFont(undefined, 'normal');
            y += 5;
        };

        // Build CV lookup map
        var cvLookup = {};
        if (cvData && typeof cvData === 'object') {
            for (var cvKey in cvData) {
                if (cvData.hasOwnProperty(cvKey)) {
                    var norm = normalizeNutrientKey(cvKey);
                    cvLookup[norm] = cvData[cvKey];
                }
            }
        }

        // ========== PAGE 1: COVER ==========
        doc.setFillColor(6, 95, 70);
        doc.rect(0, 0, W, H, 'F');

        doc.setDrawColor(16, 185, 129);
        doc.setLineWidth(0.5);
        doc.line(ML, 60, W - MR, 60);
        doc.line(ML, H - 40, W - MR, H - 40);

        doc.setTextColor(255, 255, 255);
        doc.setFontSize(24); doc.setFont(undefined, 'bold');
        doc.text('Informe de An\u00E1lisis', W / 2, 80, { align: 'center' });
        doc.text('y Recomendaciones', W / 2, 92, { align: 'center' });

        doc.setFontSize(10); doc.setFont(undefined, 'normal');
        doc.setTextColor(167, 243, 208);
        doc.text('Ley del M\u00EDnimo de Liebig \u00B7 Optimizaci\u00F3n por costo', W / 2, 104, { align: 'center' });

        doc.setFontSize(9); doc.setFont(undefined, 'normal');
        doc.setTextColor(200, 200, 200);
        var com = analysisData && analysisData.common ? analysisData.common : {};
        var finca = com.finca || '--';
        var lote = com.lote || '--';
        var fecha = com.fechaAnalisis || '--';
        var crop = CFG.cropName || '--';
        var reportTitle = CFG.reportTitle || '';
        var autor = CFG.reportAuthor || 'Sistema';

        var infoY = 130;
        var infoItems = [
            ['Finca', finca],
            ['Lote', lote],
            ['Cultivo', crop],
            ['Fecha de an\u00E1lisis', fecha],
            ['T\u00EDtulo', reportTitle],
            ['Autor', autor]
        ];
        infoItems.forEach(function (item) {
            var label = item[0], val = item[1];
            if (val && val !== '--' && val !== '') {
                doc.setTextColor(167, 243, 208);
                doc.setFont(undefined, 'normal');
                doc.text(label + ':', W / 2, infoY, { align: 'center' });
                var lblW = doc.getTextWidth(label + ':  ');
                doc.setTextColor(255, 255, 255);
                doc.setFont(undefined, 'bold');
                doc.text(String(val), W / 2 + lblW, infoY, { align: 'center' });
                infoY += 7;
            }
        });

        var now = new Date();
        var fechaInforme = now.toLocaleDateString('es-CO', { day: '2-digit', month: 'long', year: 'numeric' });
        doc.setTextColor(100, 200, 150);
        doc.setFontSize(9); doc.setFont(undefined, 'italic');
        doc.text(fechaInforme, W / 2, H - 25, { align: 'center' });
        doc.setTextColor(150, 150, 150);
        doc.text('TecnoAgro', W / 2, H - 15, { align: 'center' });

        // ========== PAGE 2: SUMMARY ==========
        doc.addPage();
        y = 20;
        doc.setFontSize(14); doc.setFont(undefined, 'bold');
        doc.setTextColor(16, 185, 129);
        doc.text('Resumen y Ley del M\u00EDnimo', ML, y);
        y += 8;
        doc.setTextColor(0, 0, 0);

        var foliarForCalc = analysisData && analysisData.foliar ? analysisData.foliar : {};
        var calcOrder = Object.keys(foliarForCalc).filter(function (k) {
            return k !== 'id' && typeof foliarForCalc[k] === 'object';
        });

        if (calcOrder.length > 0) {
            doc.setFontSize(7); doc.setFont(undefined, 'bold');
            doc.setFillColor(243, 244, 246);
            var colW = CW / 5;
            doc.rect(ML, y, CW, 7, 'F');
            doc.text('Nutriente', ML + 1, y + 5);
            doc.text('%P', ML + colW + 1, y + 5);
            doc.text('I', ML + colW * 2 + 1, y + 5);
            doc.text('R', ML + colW * 3 + 1, y + 5);
            doc.text('Diferencia', ML + colW * 4 + 1, y + 5);
            y += 7;

            doc.setFont(undefined, 'normal');
            calcOrder.forEach(function (nut, i) {
                checkPage(8);
                if (i % 2 === 0) { doc.setFillColor(249, 250, 251); doc.rect(ML, y, CW, 7, 'F'); }

                var d = foliarForCalc[nut];
                var act = d && d.valor !== undefined ? d.valor : null;
                var targ = d && d.ideal !== undefined ? d.ideal : null;
                var p = (act !== null && targ !== null && targ > 0) ? (act / targ) * 100 : NaN;
                var diff = (act !== null && targ !== null && targ > 0) ? 100 - (act / targ) * 100 : NaN;

                var normKey = normalizeNutrientKey(nut);
                var cv = cvLookup[normKey] !== undefined ? cvLookup[normKey] : null;
                var iVal = (isNaN(p) || cv === null) ? NaN : Math.abs(p - 100) * cv / 100;
                var rVal = NaN;
                if (!isNaN(iVal)) {
                    rVal = p > 100 ? p - iVal : p + iVal;
                    if (rVal < 88) rVal = 88;
                    if (rVal > 108) rVal = 108;
                }

                var displayName = nutrientNames && nutrientNames[nut]
                    ? nutrientNames[nut]
                    : nut.charAt(0).toUpperCase() + nut.slice(1);
                doc.text(displayName, ML + 1, y + 5);
                writeCell(doc, p, ML + colW + 1, y + 5, '%P');
                writeCell(doc, iVal, ML + colW * 2 + 1, y + 5, 'I');
                writeCell(doc, rVal, ML + colW * 3 + 1, y + 5, 'R');
                writeCell(doc, diff, ML + colW * 4 + 1, y + 5, 'Diferencia');

                doc.setTextColor(0, 0, 0);
                y += 7;
            });
            y += 4;
        }

        // ========== PAGE 3: FOLIAR ==========
        doc.addPage();
        y = 20;
        doc.setFontSize(14); doc.setFont(undefined, 'bold');
        doc.setTextColor(16, 185, 129);
        doc.text('An\u00E1lisis Foliar Detallado', ML, y);
        y += 8;
        doc.setTextColor(0, 0, 0);

        var foliar = analysisData && analysisData.foliar ? analysisData.foliar : {};
        var foliarNutrients = Object.keys(foliar).filter(function (k) {
            return k !== 'id' && typeof foliar[k] === 'object';
        });

        if (foliarNutrients.length > 0) {
            doc.setFontSize(7); doc.setFont(undefined, 'bold');
            doc.setFillColor(243, 244, 246);
            var hCols = [CW * 0.20, CW * 0.10, CW * 0.12, CW * 0.10, CW * 0.12, CW * 0.10, CW * 0.16];
            var hLabels = ['Nutriente', 'S\u00EDmbolo', 'Actual', 'Unidad', 'Ideal', 'Tipo', '% Ideal'];
            doc.rect(ML, y, CW, 6, 'F');
            var cx = ML + 1;
            hLabels.forEach(function (lbl, i) {
                doc.text(lbl, cx, y + 4);
                cx += hCols[i];
            });
            y += 6;

            doc.setFont(undefined, 'normal');
            foliarNutrients.forEach(function (nut, i) {
                checkPage(8);
                if (i % 2 === 0) { doc.setFillColor(249, 250, 251); doc.rect(ML, y, CW, 6, 'F'); }
                var d = foliar[nut];
                var actual = d && d.valor !== undefined ? d.valor : '--';
                var ideal = d && d.ideal !== undefined ? d.ideal : '--';
                var unit = d && d.unidad ? d.unidad : '';
                var tipo = d && d.tipo ? d.tipo : '';
                var pct = (ideal && actual && ideal > 0) ? (actual / ideal * 100) : null;
                var sym = nutrientNames && nutrientNames[nut] ? nutrientNames[nut] : nut.toUpperCase();

                cx = ML + 1;
                doc.text(nut.charAt(0).toUpperCase() + nut.slice(1), cx, y + 4); cx += hCols[0];
                doc.text(sym, cx, y + 4); cx += hCols[1];
                doc.text(String(actual), cx, y + 4); cx += hCols[2];
                doc.text(String(unit), cx, y + 4); cx += hCols[3];
                doc.text(String(ideal), cx, y + 4); cx += hCols[4];
                doc.text(tipo.length > 4 ? tipo.slice(0, 4) : tipo, cx, y + 4); cx += hCols[5];
                if (pct !== null) {
                    if (pct >= 80 && pct <= 120) doc.setTextColor(22, 163, 74);
                    else if (pct >= 60 && pct <= 140) doc.setTextColor(234, 88, 12);
                    else doc.setTextColor(220, 38, 38);
                    doc.text(pct.toFixed(1) + '%', cx, y + 4);
                    doc.setTextColor(0, 0, 0);
                }
                y += 6;
            });
            y += 6;
        }

        // ========== PAGE 4: SOIL ==========
        var soil = analysisData && analysisData.soil ? analysisData.soil : {};
        var soilKeys = Object.keys(soil).filter(function (k) {
            return k !== 'id' && soil[k] !== null && soil[k] !== undefined;
        });
        if (soilKeys.length > 0) {
            doc.addPage();
            y = 20;
            doc.setFontSize(14); doc.setFont(undefined, 'bold');
            doc.setTextColor(16, 185, 129);
            doc.text('Interpretaci\u00F3n del An\u00E1lisis de Suelo', ML, y);
            y += 8;
            doc.setTextColor(0, 0, 0);

            soilKeys.forEach(function (key) {
                drawField(key.charAt(0).toUpperCase() + key.slice(1), String(soil[key]));
            });
            y += 4;
        }

        // ========== PAGE 5: RECOMMENDATIONS ==========
        doc.addPage();
        y = 20;
        doc.setFontSize(14); doc.setFont(undefined, 'bold');
        doc.setTextColor(16, 185, 129);
        doc.text('Recomendaciones', ML, y);
        y += 8;
        doc.setTextColor(0, 0, 0);

        var writeRecText = function (text) {
            doc.setFontSize(9); doc.setFont(undefined, 'normal');
            var lines = doc.splitTextToSize(text, CW);
            var lineH = 5;
            lines.forEach(function (line) {
                if (y > H - 25) { doc.addPage(); y = 20; }
                doc.text(line, ML, y);
                y += lineH;
            });
        };

        if (automaticRecommendations) {
            writeRecText(automaticRecommendations);
        }
        if (textRecommendations) {
            if (automaticRecommendations) { y += 2; drawLine(); y += 4; }
            writeRecText(textRecommendations);
        }
        if (!automaticRecommendations && !textRecommendations) {
            doc.setFontSize(9); doc.setFont(undefined, 'normal');
            doc.setTextColor(107, 114, 128);
            doc.text('Las recomendaciones de fertilizaci\u00F3n deben ser', ML, y); y += 5;
            doc.text('proporcionadas por el ingeniero agr\u00F3nomo responsable,', ML, y); y += 5;
            doc.text('con base en el an\u00E1lisis foliar y las condiciones locales.', ML, y); y += 5;
            doc.setTextColor(0, 0, 0);
        }

        // ========== PAGE 6: HISTORICAL ==========
        if (historicalData && historicalData.length > 1) {
            doc.addPage();
            y = 20;
            doc.setFontSize(14); doc.setFont(undefined, 'bold');
            doc.setTextColor(16, 185, 129);
            doc.text('Hist\u00F3rico de An\u00E1lisis', ML, y);
            y += 8;
            doc.setTextColor(0, 0, 0);

            var allHistNutrients = {};
            historicalData.forEach(function (e) {
                for (var k in e) {
                    if (k !== 'fecha') allHistNutrients[k] = true;
                }
            });
            var histNuts = Object.keys(allHistNutrients);

            if (histNuts.length > 0) {
                doc.setFontSize(7); doc.setFont(undefined, 'bold');
                doc.setFillColor(243, 244, 246);
                var hColW = CW / (histNuts.length + 1);
                doc.rect(ML, y, CW, 6, 'F');
                doc.text('Fecha', ML + 1, y + 4);
                histNuts.forEach(function (n, i) {
                    doc.text(n, ML + hColW * (i + 1) + 1, y + 4);
                });
                y += 6;

                doc.setFont(undefined, 'normal');
                historicalData.forEach(function (entry, i) {
                    checkPage(8);
                    if (i % 2 === 0) { doc.setFillColor(249, 250, 251); doc.rect(ML, y, CW, 6, 'F'); }
                    doc.text(entry.fecha || '', ML + 1, y + 4);
                    histNuts.forEach(function (nut, j) {
                        var val = entry[nut];
                        if (val !== null && val !== undefined) {
                            doc.text(String(val), ML + hColW * (j + 1) + 1, y + 4);
                        }
                    });
                    y += 6;
                });
            }
            y += 4;
        }

        // ========== FOOTER ==========
        var pageCount = doc.internal.getNumberOfPages();
        for (var i = 1; i <= pageCount; i++) {
            doc.setPage(i);
            doc.setFontSize(7); doc.setTextColor(156, 163, 175);
            doc.text('Informe de An\u00E1lisis \u00B7 P\u00E1gina ' + i + ' de ' + pageCount, W / 2, H - 10, { align: 'center' });
            doc.setTextColor(0, 0, 0);
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
    document.addEventListener('DOMContentLoaded', function () {
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
        initHistoricalChart();
        initResultsLoader();
    });
})();
