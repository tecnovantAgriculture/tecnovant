#!/usr/bin/env python3
"""
Versión simple para limpiar flags .processing huérfanos.
"""

import os
import time
from pathlib import Path

def main():
    media_root = Path("project/storage/media")
    cache_root = media_root / "cache"
    
    if not cache_root.exists():
        print(f"Cache root no encontrado: {cache_root}")
        return
    
    cutoff_time = time.time() - (10 * 60)  # 10 minutos
    
    for asset_dir in cache_root.iterdir():
        if not asset_dir.is_dir():
            continue
            
        processing_flag = asset_dir / ".processing"
        if not processing_flag.exists():
            continue
        
        # Verificar antigüedad
        mtime = processing_flag.stat().st_mtime
        if mtime > cutoff_time:
            continue
        
        # Verificar si hay NPZ
        has_npz = any(asset_dir.glob("*__rgb_preproc_linear.npz"))
        
        print(f"Encontrado: {asset_dir.name}")
        print(f"  Edad: {(time.time() - mtime) / 60:.1f} minutos")
        print(f"  Tiene NPZ: {'Sí' if has_npz else 'No'}")
        print(f"  PNGs: {len(list(asset_dir.glob('*.png')))}")
        
        try:
            processing_flag.unlink()
            print(f"  ✅ Flag eliminado")
        except Exception as e:
            print(f"  ❌ Error al eliminar: {e}")
        
        print()

if __name__ == "__main__":
    main()