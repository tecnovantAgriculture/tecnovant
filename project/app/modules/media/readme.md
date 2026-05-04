# Media – biblioteca, deduplicación y preprocesamiento

Media centraliza la gestión de archivos (TIFF/JPG/PNG) que entran al ecosistema TecnoAgro. El módulo resuelve la subida local, deduplica por `sha256 + size`, genera miniaturas WebP, expone una biblioteca web embebible y mantiene un worker en segundo plano que prepara artefactos científicos (previews RGB, caches NPZ y pseudo-NDVI). Todo se apoya en SQLAlchemy y un filesystem local (`MEDIA_STORAGE_DIR`).

---

## Arquitectura

| Pieza | Archivo | Función |
| --- | --- | --- |
| Blueprints | `__init__.py` (`media`, `media_api`) | Entradas web `/dashboard/media/*` y API `/api/media/*`. |
| Modelos | `models.py` | `Asset`, `AssetVariant`, enums `AssetType` y `StorageLocation`. |
| Controlador | `controller.py` | Registra subidas (`save_local_upload`) y elimina activos (`delete_asset`). |
| Helpers | `helpers.py` | Abstrae storage, hashing, metadatos, miniaturas, pipelines de color y NDVI. |
| Tareas | `tasks.py` | `ThreadPoolExecutor` + `enqueue_preprocess_asset`. |
| API | `api_routes.py` | Ping, listado, upload, delete y `asset_agrovista_meta`. |
| Web | `web_routes.py` + `templates/media/*.j2` | Biblioteca, picker, detalle, upload UI y endpoints `serve/download`. |

Los originales viven bajo `storage/media/local/<shards>/<uuid>.<ext>` y las derivadas en `storage/media/variants/<kind>/...`. Cada asset también posee un directorio de caché (`storage/media/cache/<uuid>`) administrado por las tareas background.

---

## Ciclo de ingestión (`MediaController.save_local_upload`)

1. **Validación inicial.** Exige nombre de archivo y extensión permitida (`.tif/.tiff/.png/.jpg/.jpeg`).  
2. **Captura a temporal.** `capture_upload_to_temp` recorre el stream en bloques (`MEDIA_UPLOAD_CHUNK_SIZE`), calcula SHA-256 y tamaño sin consumir memoria excesiva.  
3. **Deduplicación.** Busca `Asset` por `(sha256, size_bytes)`.  
   - Si existe, descarta el temporal, valida si faltan variantes WebP (`generate_webp_thumbnails`) y retorna el registro previo (`created=False`).  
   - Si no existe, continúa con la persistencia.
4. **Persistencia.**  
   - `allocate_storage_path` define la ruta definitiva bajo `_media_root()`.  
   - Mueve el archivo, infiere MIME (`guess_mime`) y extrae metadatos: dimensiones/EXIF (`extract_image_info`) y georreferenciación (`extract_geo_info_if_tiff`).  
   - Determina `asset_type` (GeoTIFF vs imagen).  
   - Genera miniaturas según `MEDIA_THUMBNAIL_SPECS` y guarda el `Asset` + `AssetVariant`.  
5. **Posprocesos.** En todos los casos (nuevo o duplicado) `enqueue_preprocess_asset(asset.id)` programa el pipeline científico y la respuesta API indica si fue creación (`201`) o reutilización (`200`).

La eliminación (`delete_asset`) borra el archivo si sigue en disco y luego elimina la fila, priorizando la consistencia de la base.

---

## Preprocesamiento y cachés

`helpers.py` concentra utilidades ciencia/imagen:

- **`preprocess_rgb_once`**: lee el raster, convierte a lineal (`srgb_to_linear`), aplica balance Gray-World y máscara de sombras, y cachea:
  - `__rgb_preproc_linear.npz` con los flotantes exactos.
  - `__rgb_preproc_preview.png` (preview RGB).
  - `__vi_gr_ratio.png`, `__vi_gr_heat.png`, `__vi_heatmap.png` para análisis visual rápido.
  Purga caches corruptos antes de regenerar para evitar lecturas inconsistentes.
- **Índices visibles y NDVI**: `visible_indices`, `combine_indices`, `true_ndvi`, `process_minimal` y `write_float32_geotiff` permiten producir NDVI real (cuando hay banda NIR) o un pseudo-NDVI combinado (pesos 0.4/0.3/0.2/0.1 sobre NGRDI/VARI/GLI/ExG).
- **Miniaturas WebP**: `generate_webp_thumbnails` usa Pillow y, si es necesario, Rasterio para bajar la resolución de GeoTIFFs enormes sin agotar memoria.

Todos estos artefactos se almacenan bajo `cache/<uuid>` y son servidos por el blueprint web.

---

## Worker background (`tasks.py`)

`enqueue_preprocess_asset` envía trabajos a un `ThreadPoolExecutor` cuyo tamaño se controla con `MEDIA_PREPROCESS_MAX_WORKERS`. Cada trabajo:

1. Resuelve el archivo físico (`_media_root() / storage_key`) y aborta si no existe o no es `StorageLocation.LOCAL`.  
2. Marca el flag `.processing` dentro del caché y limpia `.error`.  
3. Ejecuta `preprocess_rgb_once` con un `PreprocessConfig` derivado de la configuración (`MEDIA_PREVIEW_MAX_DIM`).  
4. Limpia el flag o registra la excepción en `.error`.  
5. Si el asset es GeoTIFF, invoca `generate_display_assets` (servicio de Agrovista) para generar derivados listos para map tiles (`MEDIA_DISPLAY_MODE`, `MEDIA_DISPLAY_MAX_DIM`).  
6. Desmarca `.processing` al terminar.

De esta forma las subidas no esperan el preprocesamiento y la UI puede mostrar el progreso leyendo los flags.

---

## Biblioteca y selector embebible

- **`media.library`**: lista paginada con filtros por nombre y tipo (`image`/`geotiff`/`all`). Si llega `picker=1` se convierte en un iframe listo para integrarse en otros módulos; admite parámetros `allowed`, `event`, `multi` para controlar qué tipos se pueden seleccionar y el nombre del `postMessage`.  
- **`media.element`**: muestra metadatos completos (URLs, EXIF, bounds, cachés disponibles) y estado del procesamiento. Permite reencolar (`POST /element/<id>/reprocess`).  
- **`media.upload_local`**: formulario UI que reutiliza el mismo controlador que la API; `media.upload_s3` es un stub informativo.  
- **`media.serve_file` / `media.download_file`**: sirven archivos restringidos a `_media_root()` para prevenir path traversal.

Cuando actúa como picker, la vista envía `window.parent.postMessage({ ...asset... })` bajo el evento configurado, además de señales `eventName:ready/cancel` para coordinar con el consumidor.

---

## API disponible

| Método | Ruta | Descripción |
| --- | --- | --- |
| `GET` | `/api/media/ping` | Latido simple. |
| `GET` | `/api/media/assets` | Lista completa (sin paginar) de assets y variantes ordenados por fecha. Requiere sesión. |
| `POST` | `/api/media/upload` | Recibe `file` (multipart), valida/deduplica, guarda y encola el worker. Devuelve `{asset_id, uuid, storage_key, created}`. |
| `DELETE` | `/api/media/assets/<id>` | Elimina registro + archivo físico local. |
| `GET` | `/api/media/assets/<id>/agrovista-meta` | Garantiza que exista un caché fresco (ejecuta `preprocess_rgb_once` si falta), expone URLs relativas a los previews, la clave NPZ y escalas que Agrovista usa para mostrar overlays sin volver a subir el archivo. |

Todas salvo `ping` llevan `@login_required`. Ante excepciones se hace `db.session.rollback()` y se devuelve JSON `{message: ...}` acorde.

---

## Configuración relevante

| Variable | Uso |
| --- | --- |
| `MEDIA_STORAGE_DIR` | Raíz absoluta para originales/variantes (`storage/media` por defecto). |
| `MEDIA_UPLOAD_TMP_DIR` | Ruta de archivos temporales; cae en `storage/media/tmp` si no se define. |
| `MEDIA_UPLOAD_CHUNK_SIZE` | Tamaño del buffer al capturar uploads (mínimo 1 MiB). |
| `MEDIA_THUMBNAIL_SPECS` | Controla los tamaños/calidad de las WebP (`gallery` por default). |
| `MEDIA_PREPROCESS_MAX_WORKERS` | Hilos del executor. |
| `MEDIA_PREPROCESS_CACHE_DIR` | Override para `storage/media/cache`. |
| `MEDIA_PREVIEW_MAX_DIM` | Dimensión máxima para previews/heatmaps generados. |
| `MEDIA_DISPLAY_MODE`, `MEDIA_DISPLAY_MAX_DIM` | Parámetros enviados a `generate_display_assets` cuando se procesan GeoTIFFs. |

Config adicionales como `MEDIA_MAX_UPLOAD_SIZE` o `MAX_CONTENT_LENGTH` se definen fuera del módulo pero deben mantenerse consistentes para evitar rechazos en Nginx/Flask.

---

## Integraciones destacadas

- **Agrovista**: incrusta la biblioteca en modo picker, consume `asset_agrovista_meta` para reutilizar los caches NPZ/PNG y aprovecha los display assets generados para Leaflet.  
- **Dashboards/reportes**: consultan `/api/media/assets` para poblar catálogos con metadatos homogéneos (hash, MIME, dimensiones, CRS).  
- **Scripts ETL**: pueden subir archivos vía API y usar `storage_key` como puntero dentro del mismo filesystem compartido.

---

## Consideraciones y próximos pasos

- Solo se soporta almacenamiento local; aunque existe la enum `StorageLocation.S3`, aún no hay adapters para subir o servir desde S3.  
- `/api/media/assets` no pagina; antes de crecer en volumen debería añadirse paginación/filtrado.  
- El borrado no limpia `cache/<uuid>` automáticamente.  
- El worker corre en hilos dentro del mismo proceso; en entornos con varias réplicas conviene migrar a un worker dedicado (RQ/Celery) para mejorar observabilidad.  
- La UI “Importar desde S3” sigue siendo un placeholder.

Sugerencias inmediatas:

1. Implementar paginación y filtros en el endpoint `assets`.  
2. Agregar limpieza automática de caches al eliminar un asset o exponer un comando de mantenimiento.  
3. Soportar almacenamiento alternativo (S3) reutilizando `StorageLocation`.  
4. Usar `schemas.py` para documentar respuestas y validar uploads.  
5. Guardar los resultados NDVI (`ndvi.tif`/`ndvi_approx.tif`) como `AssetVariant` cuando existan para evitar reprocesos posteriores.
