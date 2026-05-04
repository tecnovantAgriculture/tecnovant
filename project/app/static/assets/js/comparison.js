// comparison.js - Lógica JavaScript para comparación nutricional
// Extraído de comparacion-config.j2 durante auditoría técnica fase 3

(function() {
    "use strict";

    const el = {
        error: document.getElementById("comparison-error"),
        modeBadge: document.getElementById("modeBadge"),
        analysisCardTitle: document.getElementById("analysisCardTitle"),
        analysisCardBadge: document.getElementById("analysisCardBadge"),
        analysisLotName: document.getElementById("analysisLotName"),
        analysisLotArea: document.getElementById("analysisLotArea"),
        analysisLotCrop: document.getElementById("analysisLotCrop"),
        analysisLotDate: document.getElementById("analysisLotDate"),
        analysisNdvi: document.getElementById("analysisNdvi"),
        analysisVari: document.getElementById("analysisVari"),
        analysisNbi: document.getElementById("analysisNbi"),
        referenceCardBadge: document.getElementById("referenceCardBadge"),
        referenceName: document.getElementById("referenceName"),
        referenceSource: document.getElementById("referenceSource"),
        referenceType: document.getElementById("referenceType"),
        referenceNdvi: document.getElementById("referenceNdvi"),
        referenceVari: document.getElementById("referenceVari"),
        referenceNbi: document.getElementById("referenceNbi"),
        limitingNutrient: document.getElementById("limitingNutrient"),
        optimalNutrients: document.getElementById("optimalNutrients"),
        excessNutrients: document.getElementById("excessNutrients"),
        cropInfoHeader: document.getElementById("cropInfoHeader"),
        cropInfoRow: document.getElementById("cropInfoRow"),
        analysisMeta: document.getElementById("analysisMeta"),
        analysisInfoHeader: document.getElementById("analysisInfoHeader"),
        analysisInfoRow: document.getElementById("analysisInfoRow"),
        cvInfoHeader: document.getElementById("cvInfoHeader"),
        cvInfoRow: document.getElementById("cvInfoRow"),
        lawTableHeader: document.getElementById("lawTableHeader"),
        lawTableBody: document.getElementById("lawTableBody"),
        exportPdfBtn: document.getElementById("exportPdfBtn"),
        previewReportBtn: document.getElementById("previewReportBtn"),
        saveReportBtn: document.getElementById("saveReportBtn"),
        previewModal: document.getElementById("previewModal"),
        previewModalClose: document.getElementById("previewModalClose"),
        previewModalCloseBtn: document.getElementById("previewModalCloseBtn"),
        previewSaveBtn: document.getElementById("previewSaveBtn"),
        previewDiagnosis: document.getElementById("previewDiagnosis"),
        previewTable: document.getElementById("previewTable"),
        previewProducts: document.getElementById("previewProducts"),
        previewCost: document.getElementById("previewCost"),
        previewWarnings: document.getElementById("previewWarnings"),
    };

    // Estado de la aplicación
    let state = {
        mode: null,
        analysisLot: null,
        reference: null,
        foliarData: null,
        cvData: null,
        lawData: null,
        products: null,
        diagnosis: null,
        warnings: [],
    };

    // Funciones de utilidad
    function showError(msg) {
        if (el.error) {
            el.error.textContent = msg;
            el.error.classList.remove("hidden");
        }
        console.error(msg);
    }

    function hideError() {
        if (el.error) {
            el.error.classList.add("hidden");
        }
    }

    function formatNumber(num, decimals = 2) {
        if (num == null) return "--";
        return Number(num).toFixed(decimals);
    }

    function formatDate(dateStr) {
        if (!dateStr) return "--";
        try {
            const date = new Date(dateStr);
            return date.toLocaleDateString("es-ES");
        } catch {
            return dateStr;
        }
    }

    function formatArea(area) {
        if (!area) return "--";
        return `${formatNumber(area, 1)} ha`;
    }

    // Funciones principales de la aplicación
    function initializeComparison() {
        // Configurar event listeners
        if (el.exportPdfBtn) {
            el.exportPdfBtn.addEventListener("click", handleExportPdf);
        }
        
        if (el.previewReportBtn) {
            el.previewReportBtn.addEventListener("click", handlePreviewReport);
        }
        
        if (el.saveReportBtn) {
            el.saveReportBtn.addEventListener("click", handleSaveReport);
        }
        
        if (el.previewModalClose) {
            el.previewModalClose.addEventListener("click", closePreviewModal);
        }
        
        if (el.previewModalCloseBtn) {
            el.previewModalCloseBtn.addEventListener("click", closePreviewModal);
        }
        
        if (el.previewSaveBtn) {
            el.previewSaveBtn.addEventListener("click", handlePreviewSave);
        }

        // Cargar datos iniciales si existen
        loadInitialData();
    }

    function loadInitialData() {
        // Intentar cargar datos desde atributos data-* o variables globales
        try {
            const dataElement = document.getElementById("comparison-data");
            if (dataElement && dataElement.textContent) {
                const data = JSON.parse(dataElement.textContent);
                updateState(data);
                render();
            }
        } catch (error) {
            console.warn("No se pudieron cargar datos iniciales:", error);
        }
    }

    function updateState(newData) {
        state = { ...state, ...newData };
        
        // Actualizar badge de modo
        if (el.modeBadge && state.mode) {
            el.modeBadge.textContent = `Modo: ${state.mode}`;
        }
    }

    function render() {
        // Renderizar datos del lote analizado
        if (state.analysisLot && el.analysisLotName) {
            el.analysisLotName.textContent = state.analysisLot.name || "--";
            el.analysisLotArea.textContent = formatArea(state.analysisLot.area);
            el.analysisLotCrop.textContent = state.analysisLot.crop || "--";
            el.analysisLotDate.textContent = formatDate(state.analysisLot.date);
            
            if (state.analysisLot.indices) {
                el.analysisNdvi.textContent = formatNumber(state.analysisLot.indices.ndvi);
                el.analysisVari.textContent = formatNumber(state.analysisLot.indices.vari);
                el.analysisNbi.textContent = formatNumber(state.analysisLot.indices.nbi);
            }
        }

        // Renderizar datos de referencia
        if (state.reference && el.referenceName) {
            el.referenceName.textContent = state.reference.name || "--";
            el.referenceSource.textContent = state.reference.source || "--";
            el.referenceType.textContent = state.reference.type || "--";
            
            if (state.reference.indices) {
                el.referenceNdvi.textContent = formatNumber(state.reference.indices.ndvi);
                el.referenceVari.textContent = formatNumber(state.reference.indices.vari);
                el.referenceNbi.textContent = formatNumber(state.reference.indices.nbi);
            }
        }

        // Renderizar tabla de Ley de Mínimos
        renderLawTable();
        
        // Renderizar diagnóstico
        renderDiagnosis();
    }

    function renderLawTable() {
        if (!el.lawTableBody || !state.lawData) return;
        
        el.lawTableBody.innerHTML = "";
        
        state.lawData.forEach(item => {
            const row = document.createElement("tr");
            row.className = "comparison-law-row";
            
            row.innerHTML = `
                <td class="px-4 py-2 text-sm text-gray-700">${item.nutrient || "--"}</td>
                <td class="px-4 py-2 text-sm text-gray-700 text-right">${formatNumber(item.actual)}</td>
                <td class="px-4 py-2 text-sm text-gray-700 text-right">${formatNumber(item.ideal)}</td>
                <td class="px-4 py-2 text-sm text-gray-700 text-right">${formatNumber(item.percentage, 1)}%</td>
                <td class="px-4 py-2 text-sm text-gray-700 text-right">${formatNumber(item.index)}</td>
                <td class="px-4 py-2 text-sm text-gray-700 text-right">${formatNumber(item.range)}</td>
                <td class="px-4 py-2 text-sm text-gray-700 text-right">${formatNumber(item.difference)}</td>
            `;
            
            el.lawTableBody.appendChild(row);
        });
    }

    function renderDiagnosis() {
        if (!el.limitingNutrient || !state.diagnosis) return;
        
        el.limitingNutrient.textContent = state.diagnosis.limiting || "--";
        el.optimalNutrients.textContent = state.diagnosis.optimal?.join(", ") || "--";
        el.excessNutrients.textContent = state.diagnosis.excess?.join(", ") || "--";
        
        // Renderizar warnings si existen
        if (el.previewWarnings && state.warnings.length > 0) {
            el.previewWarnings.innerHTML = state.warnings
                .map(w => `<div class="text-amber-700 text-sm">⚠ ${w}</div>`)
                .join("");
        }
    }

    // Handlers de eventos
    function handleExportPdf() {
        showError("Exportación PDF: funcionalidad en desarrollo");
        // TODO: Implementar exportación PDF usando jsPDF
    }

    function handlePreviewReport() {
        if (!el.previewModal) return;
        
        // Actualizar contenido del modal
        if (el.previewDiagnosis && state.diagnosis) {
            el.previewDiagnosis.textContent = state.diagnosis.summary || "Sin diagnóstico disponible";
        }
        
        // Mostrar modal
        el.previewModal.classList.remove("hidden");
    }

    function handleSaveReport() {
        showError("Guardar reporte: funcionalidad en desarrollo");
        // TODO: Implementar guardado de reporte
    }

    function closePreviewModal() {
        if (el.previewModal) {
            el.previewModal.classList.add("hidden");
        }
    }

    function handlePreviewSave() {
        // Guardar desde modal de preview
        handleSaveReport();
        closePreviewModal();
    }

    // API pública
    window.ComparisonApp = {
        initialize: initializeComparison,
        update: updateState,
        render: render,
        showError: showError,
        hideError: hideError,
    };

    // Inicializar cuando el DOM esté listo
    if (document.readyState === "loading") {
        document.addEventListener("DOMContentLoaded", initializeComparison);
    } else {
        initializeComparison();
    }
})();