# -*- coding: utf-8 -*-
"""Convierte masivamente los archivos del origen elegido entre CRS.
Salida: subcarpeta CRS<código destino> junto a cada archivo."""
import os
import processing
from qgis.core import QgsVectorLayer, QgsCoordinateReferenceSystem

if "ENTRADAS" not in globals():
    raise ValueError("Falta ENTRADAS (elige el origen en la interfaz).")
if "crs_src" not in globals() or not crs_src:
    crs_src = "EPSG:32614"
if "crs_dst" not in globals() or not crs_dst:
    crs_dst = "EPSG:4326"

dst = QgsCoordinateReferenceSystem(str(crs_dst))
src = QgsCoordinateReferenceSystem(str(crs_src))
sub = "CRS" + dst.authid().split(":")[-1]

ok, err = 0, 0
for ruta in ENTRADAS:
    lyr = QgsVectorLayer(ruta, os.path.basename(ruta), "ogr")
    if not lyr.isValid():
        print(f"[ERROR] no se pudo abrir: {ruta}")
        err += 1
        continue
    if not lyr.crs().isValid():
        lyr.setCrs(src)
    carpeta = os.path.join(os.path.dirname(ruta), sub)
    os.makedirs(carpeta, exist_ok=True)
    salida = os.path.join(carpeta, os.path.basename(ruta))
    try:
        processing.run("native:reprojectlayer",
                       {"INPUT": lyr, "TARGET_CRS": dst, "OUTPUT": salida})
        ok += 1
        print(f"[OK] {salida}")
    except Exception as e:
        err += 1
        print(f"[ERROR] {ruta}: {e}")

print(f"Convertidos: {ok} | errores: {err} | destino: {dst.authid()} (subcarpeta {sub})")
