# -*- coding: utf-8 -*-
"""Quita del lienzo todas las capas cuyo archivo de origen esté dentro de la
carpeta indicada. Cableado a la UI: usa root_folder inyectado."""
import os
from qgis.core import QgsProject

if "root_folder" not in globals():
    raise ValueError("Falta root_folder (elige la carpeta en la interfaz).")

root = os.path.normcase(os.path.normpath(root_folder))
proj = QgsProject.instance()
quitar = []
for lyr in list(proj.mapLayers().values()):
    src = lyr.source().split("|")[0]
    if not src:
        continue
    p = os.path.normcase(os.path.normpath(src))
    if p == root or p.startswith(root + os.sep):
        quitar.append(lyr.id())

proj.removeMapLayers(quitar)
print(f"{len(quitar)} capas quitadas del lienzo (origen bajo: {root_folder}).")
