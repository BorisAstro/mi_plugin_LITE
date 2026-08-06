# -*- coding: utf-8 -*-
"""Convierte SHP a GeoJSON con el esquema de un GeoJSON de referencia:
1) coincidencia exacta (sin mayúsculas), 2) ref empieza con nombre shp
(truncado), 3) shp empieza con nombre ref. Campos de referencia sin par → null.

CRS: si el .prj del SHP trae un CRS problemático (compuesto/ESRI, error
"CRS cannot be converted to a WKT string of a 'WKT1_GDAL' version"), usa
"CRS de origen" para forzarlo. "CRS de salida" reproyecta el resultado
(vacío = se mantiene el de origen). Además el CRS se normaliza a su código
EPSG cuando es posible, lo que evita ese error en la mayoría de los casos."""
import json
import os
import re

import geopandas as gpd
from shapely import force_2d

for v in ("shp_in", "out_geojson"):
    if v not in globals() or not globals()[v]:
        raise ValueError(f"Falta el parámetro {v}.")
if "ref_geojson" not in globals():
    ref_geojson = None
if "APLANAR_2D" not in globals():
    APLANAR_2D = True      # los templates son 2D: se descarta la Z del SHP
if "CARPETA_TEMPLATES" not in globals() or not CARPETA_TEMPLATES:
    CARPETA_TEMPLATES = os.path.join(
        os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "template")


def plantilla_por_nombre(ruta_shp, carpeta):
    """Busca en template/ un GeoJSON cuyo nombre case con el del SHP.

    CURBSTONE_3d.shp -> template/CURBSTONE.geojson
    LANE_MARKER_1785237823.shp -> template/LANE_MARKER.geojson
    """
    if not os.path.isdir(carpeta):
        return None, []
    base = os.path.splitext(os.path.basename(ruta_shp))[0]
    base = re.sub(r"(_\d{4,})+$", "", base)          # sufijos de exportacion
    base = re.sub(r"[_-]?(3d|2d|z|fix|final)$", "", base, flags=re.I)
    clave = re.sub(r"[^a-z0-9]", "", base.lower())
    candidatos = []
    for f in sorted(os.listdir(carpeta)):
        if not f.lower().endswith(".geojson"):
            continue
        k = re.sub(r"[^a-z0-9]", "", os.path.splitext(f)[0].lower())
        if k == clave:
            return os.path.join(carpeta, f), []
        if k and (clave.startswith(k) or k.startswith(clave)):
            candidatos.append(os.path.join(carpeta, f))
    return (candidatos[0] if len(candidatos) == 1 else None,
            [os.path.basename(c) for c in candidatos])


if not ref_geojson:
    auto, cands = plantilla_por_nombre(shp_in, CARPETA_TEMPLATES)
    if auto:
        ref_geojson = auto
        print("Plantilla detectada automaticamente: %s"
              % os.path.basename(ref_geojson))
    else:
        disponibles = [f for f in sorted(os.listdir(CARPETA_TEMPLATES))
                       if f.lower().endswith(".geojson")] \
            if os.path.isdir(CARPETA_TEMPLATES) else []
        raise ValueError(
            "No se indico GeoJSON de referencia y no hay una plantilla que "
            "case con '%s'.%s\n  Plantillas en %s: %s"
            % (os.path.basename(shp_in),
               ("  Ambiguo entre: %s" % ", ".join(cands)) if cands else "",
               CARPETA_TEMPLATES, ", ".join(disponibles) or "(ninguna)"))
if "CRS_ORIGEN" not in globals():
    CRS_ORIGEN = None      # ej. "EPSG:32612"; vacío = usar el .prj del SHP
if "CRS_SALIDA" not in globals():
    CRS_SALIDA = None      # ej. "EPSG:4326"; vacío = mantener el de origen

gdf = gpd.read_file(shp_in)

# ----------------------------- manejo de CRS -------------------------------
if CRS_ORIGEN:
    gdf = gdf.set_crs(CRS_ORIGEN, allow_override=True)
    print(f"CRS de origen forzado a {CRS_ORIGEN}.")
elif gdf.crs is None:
    raise ValueError("El SHP no tiene CRS (.prj ausente): indica el CRS de origen.")

with open(ref_geojson, encoding="utf-8") as fh:
    ref = json.load(fh)
feats = ref.get("features", [])
ref_cols = list(feats[0].get("properties", {}).keys()) if feats else []

cols_shp = [c for c in gdf.columns if c != "geometry"]
mapa = {}
for rc in ref_cols:
    b = rc.lower()
    for sc in cols_shp:
        a = sc.lower()
        if a == b or b.startswith(a) or a.startswith(b):
            mapa[rc] = sc
            break

geom = gdf.geometry
tenia_z = bool(getattr(geom, "has_z", None) is not None and geom.has_z.any())
if APLANAR_2D and tenia_z:
    geom = gpd.GeoSeries(force_2d(geom.values), crs=gdf.crs, index=geom.index)
    print("Geometria aplanada a 2D (se descarto la Z del SHP).")
elif tenia_z:
    print("AVISO: el SHP trae Z y no se aplano; el template es 2D.")

out = gpd.GeoDataFrame(geometry=geom, crs=gdf.crs)
for rc in ref_cols:
    out[rc] = gdf[mapa[rc]] if rc in mapa else None

if CRS_SALIDA:
    out = out.to_crs(CRS_SALIDA)
    print(f"Reproyectado a {CRS_SALIDA}.")

# Normalizar a EPSG puro si es posible (evita el error WKT1_GDAL con CRS
# compuestos/ESRI provenientes del .prj)
if out.crs is not None:
    epsg = out.crs.to_epsg()
    if epsg is not None and f"EPSG:{epsg}" != out.crs.srs:
        out = out.set_crs(f"EPSG:{epsg}", allow_override=True)
        print(f"CRS normalizado a EPSG:{epsg}.")

try:
    out.to_file(out_geojson, driver="GeoJSON")
except Exception as e:
    if "WKT" in str(e) or "CRS" in str(e):
        raise RuntimeError(
            f"El CRS del SHP no se pudo escribir en GeoJSON ({e}). "
            "Solución: elige explícitamente 'CRS de origen' (el real del SHP, "
            "ej. EPSG:32612) y 'CRS de salida' (ej. EPSG:4326) en la interfaz.")
    raise

print(f"{out_geojson}: {len(out)} entidades | campos mapeados: "
      f"{len(mapa)}/{len(ref_cols)} | plantilla: {os.path.basename(ref_geojson)}")
for rc in ref_cols:
    print(f"  {rc} ← {mapa.get(rc, 'null')}")
