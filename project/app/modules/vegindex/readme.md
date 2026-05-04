# Vegindex – Cálculo rápido de VARI y proteína estimada

Vegindex es un micro-módulo que expone una API JSON y un formulario web para **inspeccionar escenas RGB** sin pasar por el pipeline pesado de Agrovista. Parte de una URI `local:` o `s3://`, lee los bytes directamente en memoria, calcula VARI y aproxima la proteína foliar mediante una tabla piecewise. Todo el flujo vive en este módulo, por lo que no requiere base de datos ni tareas background.

---

## Componentes principales

| Pieza | Archivo | Función |
| --- | --- | --- |
| Blueprint web | `__init__.py` (`vegindex`) + `web_routes.py` | Formularios HTML bajo `/dashboard/vegindex` (`/hello`, `/analyze`). |
| Blueprint API | `vegindex_api` + `api_routes.py` | Endpoints `/api/vegindex/ping` y `/compute`. |
| Controlador | `controller.py` | `compute_from_source` encapsula la orquestación desde la URI hasta las estadísticas. |
| Helpers | `helpers.py` | Resuelve la URI hacia `LocalStorage` o `S3Storage` y normaliza rutas. |
| Servicios | `services/indices.py` y `services/storage.py` | Lógica numérica (lectura raster, normalización, VARI, proteína) y drivers de almacenamiento. |
| Plantillas | `templates/vegindex/upload.j2` y `result.j2` | UI minimalista para cargar una URI y mostrar el resumen de VARI. |

---

## Flujo `compute_from_source`

1. **Resolver almacenamiento.** `get_storage_and_path` identifica el esquema `local:` o `s3:`/`s3://`.  
   - Para rutas locales puede acotar la lectura a `VEGINDEX_LOCAL_BASE`.  
   - Para S3 reutiliza un cliente `boto3` configurado con `VEGINDEX_S3_BUCKET` y credenciales `AWS_*`.
2. **Descargar en memoria.** El backend devuelve `bytes`; se abren con `rasterio.MemoryFile` para extraer bandas 1–3 y el valor `nodata`.
3. **Normalizar y enmascarar.** `mask_and_normalize_uint8` fuerza `float32` en `[0, 1]` y aplica máscaras donde haya `nodata`.
4. **Calcular VARI.** `compute_vari` aplica `(G - R) / (G + R - B)` cuidando divisiones y marcando invalidaciones cuando el denominador no es positivo.
5. **Recortar (opcional).** Si llega `bbox=[xmin,ymin,xmax,ymax]`, se recorta en píxeles asegurando que al menos haya un píxel por eje.
6. **Derivar proteína.** Se filtran valores `NaN`, se proyecta la distribución con `vari_to_protein_vector` y se calcula `mean_protein`.
7. **Responder.** Se arma un diccionario con `count`, `vari_stats {min,max,mean}`, `shape` de la matriz y `mean_protein`. Si no hay píxeles válidos se responde con `count=0` y estadísticas `None`.

Toda la operación es in-memory y el único estado compartido son las credenciales/paths configurados vía entorno.

---

## API JSON

| Método | Ruta | Uso |
| --- | --- | --- |
| `GET` | `/api/vegindex/ping` | Health-check para verificar despliegues. |
| `POST` | `/api/vegindex/compute` | Body JSON: `{ "source": "local:/data/foo.tif", "bbox": [xmin, ymin, xmax, ymax]? }`. Devuelve las estadísticas descritas arriba o `{"error": "..."} + 400` si falta `source` o sucede una excepción. |

`api_routes.py` no depende de autenticación; si se publica externamente debe protegerse desde la configuración del blueprint o a nivel de gateway.

---

## Vistas HTML

- `GET /dashboard/vegindex/hello` renderiza `upload.j2`, un formulario con campos `source` y `bbox`.  
- `POST /dashboard/vegindex/analyze` convierte `bbox` en lista de ints, valida entradas, llama a `compute_from_source` y muestra `result.j2`; los errores se reportan con `flash`.

La UI es deliberadamente simple para permitir a agrónomos pegar una URI y validar una escena sin abrir herramientas externas.

---

## Servicios y utilidades

- **`services/storage.py`**
  - `LocalStorage`: abre archivos locales y evita path traversal al resolver contra `VEGINDEX_LOCAL_BASE`.
  - `S3Storage`: crea un cliente `boto3` con credenciales de entorno, interpreta tanto `s3://bucket/key` como `s3:key` (usando `VEGINDEX_S3_BUCKET` como bucket por defecto) y devuelve los bytes del objeto.
- **`services/indices.py`**
  - `load_rgb_from_bytes`: lectura segura desde `MemoryFile`.
  - `mask_and_normalize_uint8`, `compute_vari`: preparación numérica con `numpy` en `float32`.
  - `vari_to_protein_vector`: mapea tramos de VARI (`<=0`, `0-0.10`, `0.10-0.17`, `0.17-0.23`, `0.23-0.35`, `>0.35`) a valores discretos de proteína (0–12%) preservando máscaras.

No hay modelos ni esquemas activos; los archivos `models.py` y `schemas.py` quedan como placeholders para futuras integraciones.

---

## Manejo de errores y validaciones

- `LocalStorage` restringe la lectura a la raíz configurada y levanta `PermissionError` si la ruta resuelta sale del sandbox.
- Cuando `compute_from_source` recibe un `bbox` fuera de rango lo ajusta al tamaño real para evitar índices negativos.
- En `api_routes.py` todas las excepciones se capturan y devuelven como JSON `{error: str}` con HTTP 400; la UI web transforma cualquier excepción en mensajes de `flash`.
- Si todos los píxeles resultan inválidos se devuelve un payload sin estadísticas numéricas para que el consumidor lo trate como "sin datos".

---

## Configuración disponible

| Variable | Descripción |
| --- | --- |
| `VEGINDEX_LOCAL_BASE` | Prefijo absoluto desde el cual se resuelven las rutas `local:`; evita accesos fuera del árbol esperado. |
| `VEGINDEX_S3_BUCKET` | Bucket predeterminado para URIs `s3:key` (sin doble slash). |
| `AWS_ACCESS_KEY_ID`, `AWS_SECRET_ACCESS_KEY`, `AWS_REGION` | Credenciales usadas por `boto3` al descargar archivos S3. |

Al no haber persisted storage, bastan estos valores para cambiar de data lake o mover la carpeta local sin tocar el código.

---

## Próximos pasos sugeridos

1. Añadir autenticación o rate limiting a `/api/vegindex/compute` para evitar abusos si se expone a internet.
2. Permitir especificar bandas personalizadas (p.ej. usar bandas 4/8 de un COG) y devolver métricas adicionales.
3. Exponer histograms o datos crudos del VARI cuando los consumidores requieran análisis más detallado.
