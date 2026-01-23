# 🌿 Agrovista – NDVI Tool

Módulo del sistema TecnoAgro encargado del **análisis espectral agrícola**, procesamiento **NDVI (Normalized Difference Vegetation Index)** y generación de **objetivos nutrimentales secundarios**.  
Integra procesamiento raster avanzado, cacheo eficiente y una interfaz interactiva basada en **Leaflet**.

---

## 🧩 1. Estructura General del Módulo

| Componente | Ubicación | Descripción |
| --- | --- | --- |
| **Blueprint web** | `app/modules/agrovista/__init__.py` (`agrovista`) | Renderiza las vistas del dashboard en `/dashboard/agrovista`. |
| **Blueprint API** | `app/modules/agrovista/__init__.py` (`agrovista_api`) | Endpoints REST bajo `/api/agrovista`. |
| **Vistas (UI)** | `web_routes.py` | Renderiza `ndvi-tool.j2` y `secondary-objectives.j2`. |
| **Controlador** | `controller.py` | Maneja subida, cacheo, procesamiento y estadísticas NDVI. |
| **Helpers** | `helpers.py` | Utilidades para I/O, índices visibles, NDVI, proteína, nutrientes y caché. |
| **Modelos** | `models.py` | Define `NDVIImage`, `AnalysisCrop`, `SecondaryObjective`, `SecondaryObjectiveNutrient`. |
| **Plantillas** | `templates/agrovista/ndvi-tool.j2` | Dashboard Leaflet + formularios laterales interactivos. |

📁 Todos los archivos generados (TIFFs, arrays `.npy`, PNGs coloreados y metadatos de caché) se almacenan bajo `helpers.DATA_DIR`.  
Extensiones permitidas: `.tif`, `.jp2`, `.png`, `.jpg`, `.jpeg`.

---

## 📤 2. Flujo de Subida y Procesamiento

### 2.1. Flujo General

1. **Selección del archivo**
   - Desde `<input type="file">` o desde la biblioteca (`media.library` en iframe).
   - Ambos caminos ejecutan `uploadFile()` (JS) → `POST /api/agrovista/upload`.

2. **Procesamiento inicial (`process_upload`)**
   - Valida extensión.
   - Calcula hash SHA1 para identificar duplicados.
   - Mueve el raster a `DATA_DIR/<id>_raw.<ext>`.
   - Si el hash ya existe, `_clone_cache` reutiliza `.npy`, `.png` y metadatos.
   - Si no existe, genera preview RGB (`save_quick_preview`) y crea el registro `NDVIImage`.
   - Guarda `meta.json` con rutas, dimensiones, estadísticas y método (`ndvi_approx`).

3. **Respuesta**
   - Devuelve `id`, `width`, `height`, `processed`, `method` y estadísticas básicas.

4. **Render en Leaflet**
   - Crea `L.map("map", { crs: L.CRS.Simple })` con reglas de escala personalizadas.
   - Superpone `L.imageOverlay(getOverlayUrl(), bounds)` con el PNG servido desde `/api/agrovista/image/<id>.png?t=<stamp>`.
   - Ajusta reglas y escalas (px ↔ metros) según `mppX/mppY` de la metadata.

---

## 🧮 3. Cálculo NDVI y Estadísticas

### 3.1. Pipeline Principal (`helpers.compute_ndvi`)

1. Abre el raster con **rasterio**.
2. Si hay bandas **Red + NIR**, aplica NDVI real:  
   `(NIR - Red) / (NIR + Red)` → `float32` (`compute_true_ndvi`).
3. Si solo hay **RGB**, genera índices visibles (`compute_visible_indices`):
   - Lineariza y balancea blancos.
   - Calcula **VARI**, **NGRDI**, **GLI**, **ExG**.
   - Combina con pesos 0.4 / 0.3 / 0.2 / 0.1 (`combine_indices`).
4. Guarda NDVI como `.npy`, crea PNG coloreado (`save_png_float`, mapa `RdYlGn`).
5. Serializa metadata (`bandas`, `CRS`, `transform`, `nodata`) y devuelve un `PipelineResult`.

> Actualmente, el método forzado es `ndvi_approx` y `has_nir=False` hasta activar el pipeline NIR.

---

## 🌾 4. Cálculo de Proteína y Nitrógeno

### Endpoint: `/api/agrovista/protein`

1. Valida `id` y `vertices`.
2. Llama a `ensure_processed` para garantizar que el NDVI esté listo.
3. Crea una máscara poligonal (`polygon_mask`) sobre el array NDVI.
4. Filtra los valores válidos (`mask & np.isfinite(ndvi)`).
5. Convierte NDVI → proteína (`ndvi_to_protein_vec` usando `DEFAULT_PROTEIN_TABLE`).
6. Calcula promedio o mediana (`average_protein`, mínimo 20 celdas).
7. Deriva nitrógeno dividiendo proteína / 6.25 (`protein_to_nitrogen`).
8. Calcula medias de **VI**, **VARI**, **GLI**, **NGRDI** y **ExG** desde los índices visibles.
9. Llama a `compute_secondary_objective_targets` para estimar objetivos nutrimentales.

📤 **Respuesta JSON**:

```json
{
  "protein": 3.45,
  "nitrogen": 0.55,
  "variables": {"VI":0.45,"VARI":0.31,"GLI":0.29,"NGRDI":0.25,"ExG":0.22},
  "nutrients": [{"id":1,"name":"Nitrógeno","unit":"%","target_value":3.2}, ...],
  "ndvi_ready": true,
  "method": "ndvi_approx"
}
````

---

## 🧠 5. Lógica de Cacheo y Persistencia

| Función            | Descripción                                        |
| ------------------ | -------------------------------------------------- |
| `_clone_cache`     | Reutiliza `.npy/.png` si el hash ya fue procesado. |
| `_update_cache`    | Actualiza metadatos del procesamiento.             |
| `_hash_file`       | Genera SHA1 para detectar duplicados.              |
| `_save_meta`       | Guarda `meta.json` de cada imagen.                 |
| `_save_cache_meta` | Mantiene sincronización entre DB y caché local.    |

---

## 🌍 6. Interfaz Leaflet (`ndvi-tool.j2`)

### 6.1. Estado y Endpoints

```js
const ENDPOINTS = {
  upload: "/api/agrovista/upload",
  image:  (id) => `/api/agrovista/image/${id}.png`,
  protein:"/api/agrovista/protein",
  analysisCrops:"/api/agrovista/analysis-crops",
  secondaryObjectives:"/api/agrovista/secondary-objectives",
  foliageFarms:"/api/foliage/farms/",
  foliageLots:"/api/foliage/lots/",
  commonAnalyses:"/api/foliage/common_analyses/",
  leafAnalyses:"/api/foliage/leaf_analyses/"
};
```

Variables principales:

* `imageMeta`: ID, dimensiones, método y estadísticas.
* `lastAreaStats`: última medición del polígono activo.
* `analysisCropsList` / `analysisCropMap`: cultivos de referencia para los formularios.

### 6.2. Eventos Clave

| Acción                    | Frontend                          | Backend                                         |
| ------------------------- | --------------------------------- | ----------------------------------------------- |
| Subida de imagen          | `uploadFile()`                    | `/api/agrovista/upload` → `process_upload`.     |
| Mostrar imagen            | `L.imageOverlay(getOverlayUrl())` | `/api/agrovista/image/<id>.png`.                |
| Dibujar polígono          | `updateStatsForLayer()`           | `/api/agrovista/protein` calcula proteína/NDVI. |
| Crear objetivo secundario | `handleCreateObjective()`         | `/api/agrovista/secondary-objectives`.          |
| Abrir modal foliar        | `openFoliarModal()`               | `/api/foliage/*`.                               |
| Guardar análisis foliar   | `submitFoliarForm()`              | `/api/foliage/common_analyses/`.                |

### 6.3. Elementos Destacados

* `polygonAreaPx2` y `fmtAreaPx2`: muestran áreas en px², m² o ha.
* `drawRulers` y `fmtLinear`: dibujan reglas y escalas dinámicas.
* `media.library`: integrado vía iframe con `postMessage` sin divergencia de flujo.
* `refreshMethodLabel` y `getOverlayUrl`: controlan recarga y método visible (NDVI o índice RGB).

---

## 📊 7. Tablas y Modelos en Base de Datos

| Tabla                             | Campos relevantes                                                           |
| --------------------------------- | --------------------------------------------------------------------------- |
| **ndvi_images**                   | `id`, `filename`, `png_path`, `npy_path`, `width`, `height`, `upload_date`. |
| **analysis_crops**                | `name`, `description`.                                                      |
| **secondary_objectives**          | `analysis_crop_id`, `protein_average`, `nitrogen_estimated`.                |
| **secondary_objective_nutrients** | `nutrient_id`, `target_value`.                                              |

Los nutrientes provienen del módulo **Foliage** y se consultan vía SQLAlchemy para mostrar nombre, símbolo y unidad en la UI.

---

## 🧪 8. Helpers y Utilidades Clave

| Categoría                 | Funciones                                                                              |
| ------------------------- | -------------------------------------------------------------------------------------- |
| **IO y color**            | `read_rgb_from_any`, `save_quick_preview`, `save_png_float`.                           |
| **Índices visibles**      | `compute_visible_indices`, `combine_indices`.                                          |
| **NDVI**                  | `compute_true_ndvi`, `compute_ndvi`, `ensure_processed`.                               |
| **Proteína/Nitrógeno**    | `ndvi_to_protein`, `protein_to_nitrogen`, `average_protein`.                           |
| **Polígonos**             | `polygon_mask` (usa `matplotlib.path` para generar máscaras booleanas).                |
| **Objetivos secundarios** | `compute_secondary_objective_targets`, `secondary_target_map`, `NUTRIENT_DUMMY_RULES`. |

---

## 🧭 9. Resumen de Endpoints REST

| Método     | Ruta                                  | Descripción                                         |
| ---------- | ------------------------------------- | --------------------------------------------------- |
| `POST`     | `/api/agrovista/upload`               | Sube raster, genera preview y metadata.             |
| `GET`      | `/api/agrovista/image/<id>.png`       | Devuelve PNG de preview o NDVI procesado.           |
| `POST`     | `/api/agrovista/protein`              | Calcula proteína, nitrógeno e índices por polígono. |
| `GET/POST` | `/api/agrovista/analysis-crops`       | Listado o creación de cultivos de referencia.       |
| `GET/POST` | `/api/agrovista/secondary-objectives` | Objetivos nutrimentales secundarios.                |

---

## ⚙️ 10. Consideraciones Técnicas

* Arquitectura modular y desacoplada: API y UI comparten los mismos *helpers*.
* Control total de caché y metadatos (`meta.json` + `.npy` + `.png`).
* Prevención de reprocesamiento redundante mediante hash SHA1.
* Diseño seguro y PEP8/PEP257 compliant.
* Interfaz Leaflet responsiva y optimizada para análisis agrícola.
* NDVI aproximado habilitado (pipeline NIR en desarrollo).

---

## 🧾 11. Créditos

**Desarrollado por:** [Johnny De Castro](https://jdcastro.co/)
**Framework:** Flask + SQLAlchemy + Tailwind + Leaflet
**Integración:** Redis · MariaDB · Docker · Nginx · Certbot
**Licencia:** Propietaria – Uso interno TecnoAgro

---

## 12. Consideraciones pendientes

- En varios puntos se fuerza `method="ndvi_approx"` y `has_nir=False` con comentarios `TODO` para habilitar el flujo NIR real.
- La caché evita reprocesar archivos idénticos, pero hoy también se etiqueta como NDVI aproximado para evitar inconsistencias hasta que se soporte NIR completo.
- La estimación de proteína/nitrógeno utiliza una tabla simple; ajustar los valores o el factor 6.25 impacta directamente los objetivos secundarios y los formularios foliares.

---

## 13. Próximos pasos sugeridos

1. Habilitar detección automática de banda NIR y respetar `result.method/result.has_nir`.
2. Extraer el JS de `ndvi-tool.j2` a módulos estáticos para facilitar pruebas y linting.
3. Documentar los endpoints adicionales (`/api/agrovista/analysis-crops`, `/secondary-objectives`, etc.) con ejemplos de request/response.
4. Añadir pruebas para `helpers.compute_visible_indices` y las reglas nutrimentales, asegurando reproducibilidad numérica.

Con esta guía deberías poder navegar el módulo, entender cómo fluye una imagen desde su subida hasta la visualización en Leaflet y cómo se derivan las métricas y objetivos agrícolas.
