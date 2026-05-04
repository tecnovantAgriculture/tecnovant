#!/usr/bin/env python3
"""
Prueba simple de preprocesamiento sin dependencias de Flask.
"""

import numpy as np
from pathlib import Path
import sys

# Buscar el archivo helpers.py
project_root = Path(__file__).parent
helpers_path = project_root / "project" / "app" / "modules" / "media" / "helpers.py"

if not helpers_path.exists():
    print(f"❌ No se encuentra helpers.py en {helpers_path}")
    sys.exit(1)

# Añadir al path
sys.path.insert(0, str(project_root / "project" / "app" / "modules" / "media"))
sys.path.insert(0, str(project_root))

# Monkey patch para evitar dependencias de Flask
import types
mock_flask = types.ModuleType('flask')
mock_flask.current_app = types.SimpleNamespace()
mock_flask.current_app.logger = types.SimpleNamespace()
mock_flask.current_app.logger.info = lambda *args, **kwargs: None
mock_flask.current_app.logger.warning = lambda *args, **kwargs: None
mock_flask.current_app.logger.exception = lambda *args, **kwargs: None
sys.modules['flask'] = mock_flask

# Mock para rasterio si no está instalado
try:
    import rasterio
except ImportError:
    print("⚠️  rasterio no instalado, usando mock")
    mock_rasterio = types.ModuleType('rasterio')
    sys.modules['rasterio'] = mock_rasterio

print("✅ Mocks configurados")

# Ahora importar helpers
try:
    from helpers import PreprocessConfig, preprocess_rgb_once, _media_root
    print("✅ Helpers importado correctamente")
    
    # Buscar archivo de prueba
    test_image = project_root / "project" / "storage" / "media" / "local" / "d4" / "fd" / "d4fd8de5-fd4a-4dd0-b004-e32a630b60a6.tiff"
    
    if test_image.exists():
        print(f"✅ Imagen de prueba encontrada: {test_image}")
        print(f"   Tamaño: {test_image.stat().st_size / (1024*1024):.1f} MB")
        
        # Configurar cache
        cache_dir = project_root / "test_cache"
        cache_dir.mkdir(exist_ok=True)
        
        cfg = PreprocessConfig(
            cache_dir=cache_dir,
            preview_max_dim=512,  # Pequeño para prueba rápida
        )
        
        print("\n🔧 Ejecutando preprocesamiento...")
        import time
        start = time.time()
        
        try:
            result = preprocess_rgb_once(test_image, cfg)
            elapsed = time.time() - start
            
            print(f"✅ Preprocesamiento completado en {elapsed:.1f} segundos")
            print(f"   Resultados: {len(result)} elementos")
            
            # Listar archivos generados
            print("\n📁 Archivos generados:")
            for f in cache_dir.iterdir():
                if f.is_file():
                    size_kb = f.stat().st_size / 1024
                    print(f"   {f.name} ({size_kb:.1f} KB)")
                    
        except Exception as e:
            print(f"❌ Error: {e}")
            import traceback
            traceback.print_exc()
            
    else:
        print(f"❌ Imagen no encontrada: {test_image}")
        print("   Buscando cualquier imagen .tiff...")
        tiff_files = list(project_root.glob("**/*.tiff")) + list(project_root.glob("**/*.tif"))
        if tiff_files:
            print(f"   Encontrados {len(tiff_files)} archivos TIFF:")
            for f in tiff_files[:3]:
                print(f"   - {f.relative_to(project_root)}")
        else:
            print("   No hay archivos TIFF en el proyecto")
            
except Exception as e:
    print(f"❌ Error importando/ejecutando: {e}")
    import traceback
    traceback.print_exc()