# -*- coding: utf-8 -*-
"""Crea una capa 2D de puntos a partir de una capa 3D, para etiquetar bien."""
from qgis.core import QgsProject, QgsVectorLayer, QgsFeature, QgsGeometry

if "capa" not in globals() or capa is None:
    capa = iface.activeLayer()
if capa is None:
    raise ValueError("Selecciona una capa (o activa una en el panel).")
if "nombre_salida" not in globals() or not nombre_salida:
    nombre_salida = capa.name() + "_2D"

out = QgsVectorLayer("Point?crs=" + capa.crs().authid(), nombre_salida, "memory")
out.dataProvider().addAttributes(list(capa.fields()))
out.updateFields()

feats = []
for f in capa.getFeatures():
    g = f.geometry()
    if g is None or g.isEmpty():
        continue
    g2 = QgsGeometry(g)
    geom_abs = g2.get()
    if geom_abs is not None and geom_abs.is3D():
        geom_abs.dropZValue()
    nf = QgsFeature(out.fields())
    nf.setGeometry(g2)
    nf.setAttributes(f.attributes())
    feats.append(nf)

out.dataProvider().addFeatures(feats)
out.updateExtents()
QgsProject.instance().addMapLayer(out)
print(f"{nombre_salida}: {len(feats)} puntos 2D creados.")
