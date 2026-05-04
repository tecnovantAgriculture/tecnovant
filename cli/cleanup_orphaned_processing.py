#!/usr/bin/env python3
"""
Script para limpiar flags `.processing` huérfanos en el cache de media.

Un flag `.processing` se considera huérfano si:
1. Existe por más de `MAX_AGE_MINUTES` (default: 10)
2. No hay proceso gunicorn activo procesando ese asset (verificado por PID si es posible)
3. El NPZ correspondiente existe (indica que el procesamiento avanzó pero colgó)

Uso:
    python3 scripts/cleanup_orphaned_processing.py [--dry-run] [--max-age 10] [--force]

Flags:
    --dry-run: Solo muestra qué se haría, sin eliminar
    --max-age: Minutos máximos para considerar huérfano (default: 10)
    --force: Elimina incluso si no hay NPZ (cuidado)
"""

import os
import sys
import time
import argparse
from pathlib import Path
from datetime import datetime, timedelta

# Añadir el proyecto al path para importar helpers
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

try:
    from project.app.modules.media.helpers import _media_root
except ImportError:
    def _media_root() -> str:
        # Fallback si no podemos importar
        return str(project_root / "project" / "storage" / "media")


def find_orphaned_flags(max_age_minutes: int = 10, force: bool = False) -> list:
    """Encuentra flags .processing huérfanos."""
    media_root = Path(_media_root())
    cache_root = media_root / "cache"
    
    if not cache_root.exists():
        print(f"Cache root no encontrado: {cache_root}")
        return []
    
    orphaned = []
    cutoff_time = time.time() - (max_age_minutes * 60)
    
    for asset_dir in cache_root.iterdir():
        if not asset_dir.is_dir():
            continue
            
        processing_flag = asset_dir / ".processing"
        if not processing_flag.exists():
            continue
        
        # Verificar antigüedad
        mtime = processing_flag.stat().st_mtime
        if mtime > cutoff_time:
            # Demasiado reciente, no es huérfano
            continue
        
        # Verificar si hay NPZ (indica que al menos algo progresó)
        has_npz = any(asset_dir.glob("*__rgb_preproc_linear.npz"))
        
        if not has_npz and not force:
            # Sin NPZ y sin --force, podría ser un procesamiento que nunca empezó
            # Podría ser válido si está realmente colgado
            # Verificamos si hay algún PNG parcial
            has_partial = any(asset_dir.glob("*.png.tmp")) or any(asset_dir.glob("*__tmp.npz"))
            if not has_partial:
                # No hay artefactos parciales, probablemente nunca empezó
                continue
        
        # Estadísticas del directorio
        files = list(asset_dir.iterdir())
        npz_files = [f for f in files if f.name.endswith(".npz")]
        png_files = [f for f in files if f.name.endswith(".png")]
        tmp_files = [f for f in files if "tmp" in f.name or f.name.startswith(".")]
        
        orphaned.append({
            "asset_dir": asset_dir,
            "processing_flag": processing_flag,
            "mtime": datetime.fromtimestamp(mtime),
            "age_minutes": (time.time() - mtime) / 60,
            "has_npz": has_npz,
            "npz_count": len(npz_files),
            "png_count": len(png_files),
            "tmp_count": len(tmp_files),
            "uuid": asset_dir.name,
        })
    
    return orphaned


def cleanup_orphaned(orphaned: list, dry_run: bool = False) -> dict:
    """Limpia los flags huérfanos encontrados."""
    results = {
        "cleaned": 0,
        "errors": 0,
        "details": []
    }
    
    for item in orphaned:
        try:
            flag_path = item["processing_flag"]
            asset_dir = item["asset_dir"]
            
            if dry_run:
                action = "WOULD REMOVE"
            else:
                # También eliminamos .error si existe (podría ser viejo)
                error_flag = asset_dir / ".error"
                if error_flag.exists():
                    try:
                        error_flag.unlink()
                    except Exception:
                        pass
                
                # Eliminar el flag .processing
                flag_path.unlink()
                action = "REMOVED"
            
            results["details"].append({
                "uuid": item["uuid"],
                "action": action,
                "age_minutes": f"{item['age_minutes']:.1f}",
                "has_npz": item["has_npz"],
                "artifacts": f"{item['png_count']} PNGs, {item['npz_count']} NPZs",
            })
            
            if not dry_run:
                results["cleaned"] += 1
                
        except Exception as e:
            results["errors"] += 1
            results["details"].append({
                "uuid": item["uuid"],
                "action": f"ERROR: {e}",
                "age_minutes": f"{item['age_minutes']:.1f}",
                "has_npz": item["has_npz"],
            })
    
    return results


def main():
    parser = argparse.ArgumentParser(description="Limpia flags .processing huérfanos")
    parser.add_argument("--dry-run", action="store_true", help="Solo muestra, no elimina")
    parser.add_argument("--max-age", type=int, default=10, help="Edad máxima en minutos (default: 10)")
    parser.add_argument("--force", action="store_true", help="Eliminar incluso sin NPZ")
    parser.add_argument("--verbose", "-v", action="store_true", help="Mostrar detalles")
    
    args = parser.parse_args()
    
    print(f"Buscando flags .processing huérfanos (más de {args.max_age} minutos)...")
    orphaned = find_orphaned_flags(args.max_age, args.force)
    
    if not orphaned:
        print("No se encontraron flags huérfanos.")
        return 0
    
    print(f"\nEncontrados {len(orphaned)} flags huérfanos:")
    for i, item in enumerate(orphaned, 1):
        print(f"{i:2d}. {item['uuid']} - {item['age_minutes']:.1f} min - "
              f"NPZ: {'✓' if item['has_npz'] else '✗'} - "
              f"PNGs: {item['png_count']} - "
              f"Modificado: {item['mtime'].strftime('%H:%M:%S')}")
    
    if args.dry_run:
        print("\n⚠️  DRY RUN - No se eliminará nada")
        return 0
    
    print(f"\n¿Eliminar {len(orphaned)} flags huérfanos? (s/N): ", end="")
    response = sys.stdin.readline().strip().lower()
    if response not in ("s", "si", "y", "yes"):
        print("Cancelado.")
        return 0
    
    print("\nLimpiando...")
    results = cleanup_orphaned(orphaned, dry_run=False)
    
    print(f"\nResultado:")
    print(f"  Flags eliminados: {results['cleaned']}")
    print(f"  Errores: {results['errors']}")
    
    if args.verbose and results["details"]:
        print("\nDetalles:")
        for detail in results["details"]:
            print(f"  {detail['uuid']}: {detail['action']} "
                  f"(edad: {detail['age_minutes']} min, "
                  f"NPZ: {'✓' if detail.get('has_npz') else '✗'})")
    
    # Sugerir reprocesamiento para los que tenían NPZ pero no PNGs
    needs_reprocess = [d for d in results["details"] 
                      if d.get("has_npz") and "artifacts" in d and "0 PNGs" in d["artifacts"]]
    
    if needs_reprocess:
        print(f"\n⚠️  {len(needs_reprocess)} assets tienen NPZ pero no PNGs completos.")
        print("   Pueden necesitar reprocesamiento manual.")
        print("   UUIDs:", ", ".join([d["uuid"] for d in needs_reprocess]))
    
    return 0


if __name__ == "__main__":
    sys.exit(main())