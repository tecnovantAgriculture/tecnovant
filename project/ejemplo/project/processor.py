import cv2
import numpy as np
import os
import rasterio
from typing import Dict, Optional, Any, Type, List
from enum import Enum


class NutrientCategory(Enum):
    MACRONUTRIENT = "Macronutriente"
    MICRONUTRIENT = "Micronutriente"
    
# Macronutrientes
macronutrients = [
    {"name": "Nitrógeno", "symbol": "N", "unit": "kg/ha", "description": "Esencial para el crecimiento vegetativo y el desarrollo de hojas", "category": NutrientCategory.MACRONUTRIENT},
    {"name": "Fósforo", "symbol": "P", "unit": "kg/ha", "description": "Importante para el desarrollo de raíces y flores", "category": NutrientCategory.MACRONUTRIENT},
    {"name": "Potasio", "symbol": "K", "unit": "kg/ha", "description": "Mejora la resistencia a enfermedades y el rendimiento", "category": NutrientCategory.MACRONUTRIENT},
    {"name": "Calcio", "symbol": "Ca", "unit": "kg/ha", "description": "Fundamental para el desarrollo de células y paredes celulares", "category": NutrientCategory.MACRONUTRIENT},
    {"name": "Magnesio", "symbol": "Mg", "unit": "kg/ha", "description": "Esencial para la fotosíntesis y el metabolismo energético", "category": NutrientCategory.MACRONUTRIENT},
    {"name": "Azufre", "symbol": "S", "unit": "kg/ha", "description": "Importante para la formación de aminoácidos y enzimas", "category": NutrientCategory.MACRONUTRIENT},
]

# Micronutrientes
micronutrients = [
    {"name": "Hierro", "symbol": "Fe", "unit": "g/ha", "description": "Componente clave de las enzimas respiratorias y clorofila", "category": NutrientCategory.MICRONUTRIENT}, # Movido Fe aquí por frecuencia de deficiencia visual
    {"name": "Manganeso", "symbol": "Mn", "unit": "g/ha", "description": "Participa en la fotosíntesis y el metabolismo", "category": NutrientCategory.MICRONUTRIENT},
    {"name": "Zinc", "symbol": "Zn", "unit": "g/ha", "description": "Importante para hormonas de crecimiento y enzimas", "category": NutrientCategory.MICRONUTRIENT},
    {"name": "Cobre", "symbol": "Cu", "unit": "g/ha", "description": "Actúa como cofactor en varias enzimas", "category": NutrientCategory.MICRONUTRIENT},
    {"name": "Boro", "symbol": "B", "unit": "g/ha", "description": "Importante para la pared celular y el transporte de azúcares", "category": NutrientCategory.MICRONUTRIENT},
    {"name": "Molibdeno", "symbol": "Mo", "unit": "g/ha", "description": "Esencial en la fijación de nitrógeno y metabolismo del azufre", "category": NutrientCategory.MICRONUTRIENT},
    # Cloro y Silicio a menudo no se evalúan visualmente de esta forma, se omiten para esta estimación visual
    # {"name": "Cloro", "symbol": "Cl", "unit": "g/ha", "description": "Importante para la osmoregulación y el rendimiento", "category": NutrientCategory.MICRONUTRIENT},
    # {"name": "Silicio", "symbol": "Si", "unit": "kg/ha", "description": "Mejora la estructura de las plantas y su resistencia", "category": NutrientCategory.MICRONUTRIENT}, # Unidad cambiada a kg/ha en la definición original
]

all_nutrients_info = macronutrients + micronutrients

class VegetationIndex:
    """Clase base abstracta para calculadores de índices."""
    NAME = "BaseIndex" # Dar un nombre a cada índice
    REQUIRES_NIR = False # Por defecto, no requiere NIR

    def compute(self, bands: Dict[str, np.ndarray]) -> np.ndarray:
        """
        Calcula el índice.
        Args:
            bands: Un diccionario que contiene las bandas necesarias como arrays numpy
                   (ej. {'r': red_band, 'g': green_band, 'b': blue_band, 'nir': nir_band}).
        Returns:
            Un array numpy con los valores del índice calculado.
        Raises:
            NotImplementedError: Si la subclase no lo implementa.
            KeyError: Si falta una banda requerida en el diccionario 'bands'.
            ValueError: Si las dimensiones de las bandas no coinciden.
        """
        raise NotImplementedError("Subclases deben implementar 'compute'")

    def _check_bands(self, bands: Dict[str, np.ndarray], required_keys: List[str]):
        """Helper para verificar la presencia y forma de las bandas."""
        shape = None
        for key in required_keys:
            if key not in bands:
                raise KeyError(f"La banda requerida '{key}' no se encontró para calcular {self.NAME}")
            if shape is None:
                shape = bands[key].shape
            elif bands[key].shape != shape:
                raise ValueError(f"Las dimensiones de las bandas para {self.NAME} no coinciden.")
        return shape # Devuelve la forma común

class VI_Impl(VegetationIndex):
    """Calcula Simple Ratio (VI = G / R)."""
    NAME = "VI"
    def compute(self, bands: Dict[str, np.ndarray]) -> np.ndarray:
        self._check_bands(bands, ['g', 'r'])
        g = bands['g']
        r = bands['r']
        # Añadir epsilon para estabilidad
        return np.divide(g, r, out=np.zeros_like(g, dtype=np.float64), where=(r != 0), dtype=np.float64) # Usar float64

class GLI_Impl(VegetationIndex):
    """Calcula Green Leaf Index (GLI)."""
    NAME = "GLI"
    def compute(self, bands: Dict[str, np.ndarray]) -> np.ndarray:
        self._check_bands(bands, ['g', 'r', 'b'])
        g, r, b = bands['g'], bands['r'], bands['b']
        numerator = 2 * g - r - b
        denominator = 2 * g + r + b + 1e-10 # Epsilon
        return np.divide(numerator, denominator, out=np.zeros_like(g, dtype=np.float64), where=(denominator != 0), dtype=np.float64)

class VARI_Impl(VegetationIndex):
    """Calcula Visible Atmospherically Resistant Index (VARI)."""
    NAME = "VARI"
    def compute(self, bands: Dict[str, np.ndarray]) -> np.ndarray:
        self._check_bands(bands, ['g', 'r', 'b'])
        g, r, b = bands['g'], bands['r'], bands['b']
        numerator = g - r
        denominator = g + r - b + 1e-10 # Epsilon
        return np.divide(numerator, denominator, out=np.zeros_like(g, dtype=np.float64), where=(denominator != 0), dtype=np.float64)

# --- (Opcional Fase 2) Calculadores con NIR ---
# class NDVI_Impl(VegetationIndex):
#     NAME = "NDVI"
#     REQUIRES_NIR = True
#     def compute(self, bands: Dict[str, np.ndarray]) -> np.ndarray:
#         self._check_bands(bands, ['nir', 'r'])
#         nir = bands['nir']
#         red = bands['r']
#         denominator = nir + red + 1e-10
#         return np.divide(nir - red, denominator, out=np.zeros_like(red, dtype=np.float64), where=(denominator != 0), dtype=np.float64


    
# Clase de excepción personalizada para errores del procesador
class ProcessorError(Exception):
    """Excepción base para errores específicos del procesador de imágenes."""
    pass

# --- Fábrica ---
class VegetationIndexFactory:
    # Registrar las clases de implementación
    _calculators: Dict[str, Type[VegetationIndex]] = {
        cls.NAME.upper(): cls
        for cls in [VI_Impl, GLI_Impl, VARI_Impl] # Añadir NDVI_Impl, etc. si se implementan
    }

    @staticmethod
    def get_calculator(name: str) -> Optional[VegetationIndex]:
        """Obtiene una instancia del calculador de índice solicitado."""
        calculator_class = VegetationIndexFactory._calculators.get(name.upper())
        if calculator_class:
            return calculator_class() # Retorna una nueva instancia
        return None

    @staticmethod
    def get_available_indices() -> List[str]:
         """Devuelve una lista de los nombres de índices disponibles."""
         return list(VegetationIndexFactory._calculators.keys())
     
class OrthoPhotoProcessor:
    """
    Procesa ortofotos para calcular índices de vegetación basados en RGB
    y evaluar indicadores cualitativos de estado nutricional potencial.
    """
    def __init__(self, image_path: str, processed_folder: Optional[str] = None):
        self.image_path = image_path
        self.processed_folder = processed_folder
        self.bands: Dict[str, np.ndarray] = {} # Almacenar bandas aquí
        self.is_multispectral = False # Flag para indicar si se cargaron bandas NIR etc.
        self.calculated_indices: Dict[str, np.ndarray] = {} # Almacenar resultados

        self._load_bands() # Método para cargar bandas (usando rasterio/cv2)
        self._compute_indices() # Método para calcular índices disponibles

    def get_detailed_statistics(self) -> Dict[str, Dict[str, float]]:
        """Calcula estadísticas detalladas para cada índice calculado."""
        stats = {}
        # Iterar sobre los índices que SÍ se calcularon y están en el diccionario
        for name, data in self.calculated_indices.items():
            # Asegurarse de trabajar con datos válidos (ignorar NaN)
            valid_data = data[~np.isnan(data)]
            if valid_data.size == 0:
                 stats[name] = {'min': np.nan, 'max': np.nan, 'mean': np.nan, 'std': np.nan}
                 continue

            stats[name] = {
                'min': float(np.min(valid_data)),
                'max': float(np.max(valid_data)),
                'mean': float(np.mean(valid_data)), # Aquí puede ser mean, ya filtramos NaN
                'std': float(np.std(valid_data))
            }
        return stats

    def assess_potential_nutrient_status(self) -> Dict[str, Any]:
        """
        Evalúa indicadores cualitativos de posibles problemas nutricionales.
        Incluye ahora estadísticas detalladas.
        """
        # Obtener métricas promedio (como antes, tal vez no tan necesarias si tenemos las detalladas)
        # metrics = self.get_overall_metrics() # Podrías mantener esto o basarte en las detalladas

        # Obtener estadísticas detalladas
        detailed_stats = self.get_detailed_statistics()
        potential_issues = []
        overall_assessment = "Normal"

        # --- Lógica de Decisión Heurística (Usa ahora detailed_stats['INDEX']['mean'], etc.) ---
        # Ejemplo: Usar el promedio de GLI de las estadísticas detalladas
        avg_gli = detailed_stats.get('GLI', {}).get('mean', 0) # Valor por defecto 0 si falta
        avg_vari = detailed_stats.get('VARI', {}).get('mean', 0)
        # avg_hue = ... (necesitarías calcular estadísticas HSV también)

        if avg_gli < 0.1 or avg_vari < 0.0:
             # ... (lógica de bajo vigor como antes) ...
             overall_assessment = "Potencialmente Deficiente / Estresado"
             low_vigor = True

        # ... (resto de la lógica heurística adaptada para usar detailed_stats) ...


        # --- Compilar Resultados ---
        assessment = {
            "overall": overall_assessment,
            # Mantener métricas promedio por compatibilidad o quitarlas si no se usan
            "metrics": {k: f"{v['mean']:.3f}" for k, v in detailed_stats.items() if 'mean' in v},
            "statistics": detailed_stats, # <-- AÑADIR ESTADÍSTICAS DETALLADAS
            "potential_issues": potential_issues,
            "disclaimer": (
               # ... (disclaimer como antes) ...
            )
        }
        return assessment

    def _load_bands(self):
        """Carga las bandas R, G, B (y opcionalmente NIR, etc.) usando rasterio o cv2."""
        # --- (Fase 2) Lógica para intentar con rasterio ---
        try:
            # Intentar con rasterio (requiere import rasterio)
            # import rasterio
            # with rasterio.open(self.image_path) as src:
            #     if src.count >= 4: # Asumiendo R=1, G=2, B=3, NIR=4 - ¡CONFIGURAR!
            #         print(f"Detectado archivo multiespectral con {src.count} bandas.")
            #         # Leer las bandas necesarias (ajustar índices según el sensor!)
            #         # ¡MANEJO DE NODATA ES IMPORTANTE AQUÍ! src.nodata
            #         self.bands['r'] = src.read(1).astype(np.float64)
            #         self.bands['g'] = src.read(2).astype(np.float64)
            #         self.bands['b'] = src.read(3).astype(np.float64)
            #         self.bands['nir'] = src.read(4).astype(np.float64)
            #         self.is_multispectral = True
            #         # Convertir nodata a NaN si es necesario para cálculos
            #         # for key in self.bands:
            #         #    if src.nodata is not None:
            #         #        self.bands[key][self.bands[key] == src.nodata] = np.nan
            #         return # Salir si se cargó con rasterio exitosamente
            #     else:
            #          print(f"Archivo compatible con rasterio pero con solo {src.count} bandas. Tratando como RGB.")
            #          # Podrías leer las 3 primeras bandas como RGB si lo deseas
            pass # Continuar al fallback de OpenCV si no es multi o falla rasterio
        except Exception as e: # Ser más específico con las excepciones de rasterio si es posible
             print(f"Rasterio no pudo abrir o procesar el archivo (o no está instalado): {e}. Intentando con OpenCV.")

        # --- Fallback a OpenCV (Código existente adaptado) ---
        try:
            image = cv2.imread(self.image_path, cv2.IMREAD_COLOR)
            if image is None:
                # ... (manejo de fallback a IMREAD_UNCHANGED como antes) ...
                 raise ProcessorError(f"No se pudo leer la imagen con OpenCV: {os.path.basename(self.image_path)}")

            # ... (manejo de escala grises, alpha como antes) ...
            if len(image.shape) == 2: image = cv2.cvtColor(image, cv2.COLOR_GRAY2BGR)
            elif image.shape[2] == 4: image = cv2.cvtColor(image, cv2.COLOR_BGRA2BGR)
            elif image.shape[2] != 3: raise ProcessorError(f"Canales inesperados: {image.shape[2]}")

            bgr_float = image.astype(np.float64)
            b, g, r = cv2.split(bgr_float)
            self.bands['b'] = b
            self.bands['g'] = g
            self.bands['r'] = r
            self.is_multispectral = False # Asegurar que esté falso

        except cv2.error as e:
            raise ProcessorError(f"Error de OpenCV al cargar/procesar imagen: {e}")
        except Exception as e:
            raise ProcessorError(f"Error inesperado al cargar imagen: {e}")

    def _compute_indices(self):
        """Calcula todos los índices posibles con las bandas disponibles usando la fábrica."""
        available_calculators = VegetationIndexFactory.get_available_indices()
        for index_name in available_calculators:
            calculator = VegetationIndexFactory.get_calculator(index_name)
            if not calculator: continue

            # Saltar índices NIR si no tenemos datos multispectrales
            if calculator.REQUIRES_NIR and not self.is_multispectral:
                print(f"Saltando {index_name} porque requiere NIR y la imagen no es multispectral.")
                continue

            try:
                print(f"Calculando {index_name}...")
                # Pasar el diccionario completo de bandas disponibles
                result = calculator.compute(self.bands)
                # Almacenar el resultado (array numpy)
                self.calculated_indices[index_name.upper()] = result
                print(f"{index_name} calculado.")
            except KeyError as e:
                print(f"No se pudo calcular {index_name}: Falta la banda {e}")
            except ValueError as e:
                 print(f"No se pudo calcular {index_name}: Error de dimensiones - {e}")
            except Exception as e:
                print(f"Error inesperado al calcular {index_name}: {e}")

    def get_index_data(self, index_name: str) -> Optional[np.ndarray]:
         """Obtiene los datos calculados para un índice específico."""
         return self.calculated_indices.get(index_name.upper())        
        
    def _load_image(self) -> np.ndarray:
        """Carga la imagen."""
        if not os.path.exists(self.image_path):
            raise ProcessorError(f"Archivo no encontrado: {self.image_path}")
        try:
            image = cv2.imread(self.image_path, cv2.IMREAD_COLOR)
            if image is None:
                image_unchanged = cv2.imread(self.image_path, cv2.IMREAD_UNCHANGED)
                if image_unchanged is None:
                     raise ProcessorError(f"No se pudo leer la imagen: {os.path.basename(self.image_path)}")
                else:
                     print(f"Advertencia: Imagen leída como UNCHANGED. Se intentará convertir a BGR.")
                     # Intentar convertir a BGR
                     if len(image_unchanged.shape) == 2:
                         image = cv2.cvtColor(image_unchanged, cv2.COLOR_GRAY2BGR)
                     elif image_unchanged.shape[2] == 3:
                         image = image_unchanged
                     elif image_unchanged.shape[2] == 4:
                         image = cv2.cvtColor(image_unchanged, cv2.COLOR_BGRA2BGR)
                     else:
                          raise ProcessorError("Formato de imagen UNCHANGED no manejable tras conversión.")

            return image
        except cv2.error as e:
             raise ProcessorError(f"Error de OpenCV al cargar la imagen: {e}")
        except Exception as e:
            raise ProcessorError(f"Error inesperado al cargar la imagen: {e}")

    def _normalize_for_display(self, data: np.ndarray) -> np.ndarray:
        """Normaliza los datos del índice a 0-255 para visualización."""
        norm_data = data.astype(np.float32) # Asegurar float para normalización
        min_val = np.min(norm_data)
        max_val = np.max(norm_data)
        # Evitar nan si max == min
        if np.isclose(max_val, min_val):
             # Si todos los valores son iguales, devolver imagen gris media
             # o negra/blanca según el valor
             if min_val > 0: # Por ejemplo, para VI
                 return np.full(data.shape, 255, dtype=np.uint8)
             else: # Para GLI/VARI que pueden ser 0 o negativos
                 return np.full(data.shape, 128, dtype=np.uint8)

        # Escalar a 0-1. Ajustar para índices que van de -1 a 1 vs 0 a >1
        if min_val >= -1.01 and max_val <= 1.01: # Rango típico GLI/VARI
             norm_data = (norm_data + 1.0) / 2.0
        else: # Rango > 0 como VI o normalización genérica MinMax
            norm_data = (norm_data - min_val) / (max_val - min_val)

        # Asegurarse de que esté en [0, 1] después de normalizar
        norm_data = np.clip(norm_data, 0, 1)

        return (norm_data * 255).astype(np.uint8)

    def calculate_vi(self) -> np.ndarray:
        """Calcula VI = G / R."""
        return np.divide(self.g, self.r, out=np.zeros_like(self.g, dtype=np.float64), where=self.r != 0)

    def calculate_gli(self) -> np.ndarray:
        """Calcula GLI = (2*G - R - B) / (2*G + R + B)."""
        numerator = 2 * self.g - self.r - self.b
        denominator = 2 * self.g + self.r + self.b
        return np.divide(numerator, denominator, out=np.zeros_like(self.g, dtype=np.float64), where=denominator != 0)

    def calculate_vari(self) -> np.ndarray:
        """Calcula VARI = (G - R) / (G + R - B)."""
        numerator = self.g - self.r
        denominator = self.g + self.r - self.b
        return np.divide(numerator, denominator, out=np.zeros_like(self.g, dtype=np.float64), where=denominator != 0)

    def calculate_exg(self) -> np.ndarray:
        """Calcula Excess Green Index (ExG) = 2*G - R - B."""
        # Normalizar canales a 0-1 antes para que ExG sea comparable
        # Esto asume que BGR están en rango 0-255 originalmente
        norm_r = self.r / 255.0
        norm_g = self.g / 255.0
        norm_b = self.b / 255.0
        return 2 * norm_g - norm_r - norm_b

    def save_processed_image(self, data: np.ndarray, output_filename: str) -> str:
        """Guarda una imagen procesada normalizada."""
        if not self.processed_folder:
             raise ProcessorError("La carpeta de salida no está configurada.")
        if not output_filename.lower().endswith(('.png', '.jpg', '.jpeg', '.tiff', '.tif')):
             output_filename += '.png' # Añadir extensión si falta
             print(f"Advertencia: No se especificó extensión, guardando como {output_filename}")

        output_path = os.path.join(self.processed_folder, output_filename)

        try:
            display_image = self._normalize_for_display(data)
            # Opcional: Aplicar mapa de color
            # display_image = cv2.applyColorMap(display_image, cv2.COLORMAP_JET) # JET puede ser engañoso
            # display_image = cv2.applyColorMap(display_image, cv2.COLORMAP_VIRIDIS) # Mejor opción

            success = cv2.imwrite(output_path, display_image)
            if not success:
                raise ProcessorError(f"OpenCV no pudo guardar la imagen en {output_path}")
            return output_filename
        except cv2.error as e:
            raise ProcessorError(f"Error de OpenCV al guardar imagen {output_filename}: {e}")
        except Exception as e:
             raise ProcessorError(f"Error inesperado al guardar imagen {output_filename}: {e}")

    def get_overall_metrics(self) -> Dict[str, float]:
        """
        Calcula métricas promedio sobre toda la imagen.
        *** CORREGIDO para usar self.calculated_indices y np.nanmean ***
        """
        metrics = {}

        # Calcular promedios para los índices que se hayan calculado exitosamente
        for index_name in ['VI', 'GLI', 'VARI', 'EXG']: # Añadir otros índices si se calculan
            index_data = self.calculated_indices.get(index_name.upper())
            if index_data is not None and index_data.size > 0:
                # Usar nanmean para ignorar posibles NaNs
                avg_value = float(np.nanmean(index_data))
                metrics[f"avg_{index_name.lower()}"] = avg_value
            else:
                # Si el índice no se calculó o está vacío, asignar NaN o 0.0
                metrics[f"avg_{index_name.lower()}"] = np.nan

        # Calcular promedios para HSV (asumiendo que self.hsv_image existe y se calculó en __init__)
        if hasattr(self, 'hsv_image') and self.hsv_image is not None:
            # Promedio de Tono (Hue) en grados (0-179 en OpenCV -> 0-358)
            # El promedio de Hue es complicado por la naturaleza circular (0 y 360 son lo mismo)
            # Usar estadísticas circulares es lo correcto, pero una media simple puede ser indicativa (con cuidado)
            avg_hue_opencv = float(np.nanmean(self.hsv_image[:, :, 0]))
            metrics["avg_hue_circular_approx"] = avg_hue_opencv * 2

            # Promedio de Saturación (0-255 en OpenCV -> 0-1)
            metrics["avg_saturation"] = float(np.nanmean(self.hsv_image[:, :, 1])) / 255.0
            # Promedio de Valor/Brillo (0-255 en OpenCV -> 0-1)
            metrics["avg_value"] = float(np.nanmean(self.hsv_image[:, :, 2])) / 255.0
        else:
             metrics["avg_hue_circular_approx"] = np.nan
             metrics["avg_saturation"] = np.nan
             metrics["avg_value"] = np.nan

        return metrics
    
    def save_all_processed_images(self, photo_id: int, base_filename: str) -> Dict[str, str]:
         """Guarda todos los índices calculados como imágenes PNG."""
         saved_files = {}
         for index_name, data in self.calculated_indices.items():
             try:
                 # Crear nombre de archivo único
                 output_filename = f"{index_name.lower()}_{photo_id}_{base_filename}.png"
                 # Guardar usando el método existente (que normaliza)
                 saved_filename = self.save_processed_image(data, output_filename)
                 saved_files[index_name.upper()] = saved_filename # Guardar nombre base devuelto
             except Exception as e:
                  print(f"Error al guardar la imagen para el índice {index_name}: {e}")
         return saved_files
     
    def assess_potential_nutrient_status(self) -> Dict[str, Any]:
        """
        Evalúa indicadores cualitativos de posibles problemas nutricionales.
        Incluye estadísticas detalladas de índices y métricas HSV.
        """
        metrics = self.get_overall_metrics()
        detailed_stats = self.get_detailed_statistics()
        potential_issues = []
        overall_assessment = "Normal"

        # Lógica de decisión usando métricas principales
        avg_gli = metrics.get('avg_gli', 0)
        avg_vari = metrics.get('avg_vari', 0)
        avg_hue = metrics.get('avg_hue_circular_approx', 0)
        avg_saturation = metrics.get('avg_saturation', 0)

        # 1. Evaluar vigor general
        low_vigor = False
        if avg_gli < 0.1 or avg_vari < 0.0:
            potential_issues.append({
                "concern": "Bajo Vigor General",
                "possible_causes": ["N", "P", "K", "Mg", "S", "Fe"],
                "confidence": "Media",
                "suggestion": "Análisis foliar/suelo recomendado."
            })
            overall_assessment = "Potencialmente Deficiente"
            low_vigor = True

        # 2. Detectar clorosis
        if 40 <= avg_hue <= 70 and avg_saturation < 0.4:
            potential_issues.append({
                "concern": "Posible Clorosis",
                "possible_causes": ["N", "Mg", "Fe"],
                "confidence": "Media" if low_vigor else "Baja",
                "suggestion": "Verificar patrones en hojas."
            })
            overall_assessment = "Posible Deficiencia Nutricional"

        # 3. Detectar estrés por fósforo
        if (avg_hue >= 300 or avg_hue <= 30) and low_vigor:
            potential_issues.append({
                "concern": "Posible Deficiencia de Fósforo",
                "possible_causes": ["P"],
                "confidence": "Baja",
                "suggestion": "Validar con análisis de suelo."
            })

        assessment = {
            "overall": overall_assessment,
            "statistics": detailed_stats,
            "potential_issues": potential_issues,
            "disclaimer": "Evaluación cualitativa. Requiere validación con métodos tradicionales.",
            "metrics": metrics  # Asegúrate de que 'metrics' esté siempre presente
        }
        return assessment