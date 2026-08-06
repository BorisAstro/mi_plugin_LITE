# -*- coding: utf-8 -*-
"""Offsets de los segmentos SELECCIONADOS de la CAPA ACTIVA usando CRS
proyectado (metros). Los resultados se ACUMULAN en un GeoPackage fijo en la
carpeta temporal (offsets_acumulados.gpkg): cada ejecución añade los nuevos
segmentos desplazados sin borrar los anteriores."""
import os
import tempfile

from qgis.core import (Qgis, QgsProject, QgsVectorLayer, QgsFeature, QgsField,
                       QgsFields, QgsGeometry, QgsCoordinateReferenceSystem,
                       QgsCoordinateTransform, QgsVectorFileWriter, QgsWkbTypes)
from qgis.PyQt.QtCore import QMetaType

# Capa: siempre la activa del panel (sin desplegable)
capa = iface.activeLayer()
if capa is None or not isinstance(capa, QgsVectorLayer):
    raise ValueError("Selecciona (activa) una capa de líneas en el panel.")
if "distancia" not in globals():
    distancia = 0.5
if "UTM_EPSG" not in globals():
    UTM_EPSG = 32612

sel = capa.selectedFeatures()
if not sel:
    raise ValueError("No hay entidades seleccionadas en el lienzo.")

ctx = QgsProject.instance().transformContext()
crs_utm = QgsCoordinateReferenceSystem(f"EPSG:{UTM_EPSG}")
crs_out = QgsCoordinateReferenceSystem("EPSG:4326")
ida = QgsCoordinateTransform(capa.crs(), crs_utm, QgsProject.instance())
vuelta = QgsCoordinateTransform(crs_utm, crs_out, QgsProject.instance())

# archivo fijo en temp donde se acumulan los offsets
GPKG = os.path.join(tempfile.gettempdir(), "offsets_acumulados.gpkg")
CAPA_NOMBRE = "offsets"

# campos: origen + trazabilidad
campos = QgsFields()
for fld in capa.fields():
    campos.append(fld)
campos.append(QgsField("src_layer", QMetaType.Type.QString))
campos.append(QgsField("offset_m", QMetaType.Type.Double))

feats = []
for f in sel:
    g = QgsGeometry(f.geometry())
    g.transform(ida)
    off = g.offsetCurve(float(distancia), 8, Qgis.JoinStyle.Round, 2.0)
    if off is None or off.isEmpty():
        continue
    off.transform(vuelta)
    nf = QgsFeature(campos)
    nf.setGeometry(off)
    nf.setAttributes(list(f.attributes()) + [capa.name(), float(distancia)])
    feats.append(nf)

if not feats:
    raise ValueError("Ningún segmento pudo desplazarse (revisa la geometría).")

existe = os.path.exists(GPKG)
opts = QgsVectorFileWriter.SaveVectorOptions()
opts.driverName = "GPKG"
opts.layerName = CAPA_NOMBRE
opts.fileEncoding = "UTF-8"
if existe:
    # añadir a la capa existente (acumula entre ejecuciones)
    opts.actionOnExistingFile = QgsVectorFileWriter.ActionOnExistingFile.AppendToLayerNoNewFields
else:
    opts.actionOnExistingFile = QgsVectorFileWriter.ActionOnExistingFile.CreateOrOverwriteFile

tmp = QgsVectorLayer("LineString?crs=EPSG:4326", "tmp", "memory")
tmp.dataProvider().addAttributes(list(campos))
tmp.updateFields()
tmp.dataProvider().addFeatures(feats)

res = QgsVectorFileWriter.writeAsVectorFormatV3(tmp, GPKG, ctx, opts)
if res[0] != QgsVectorFileWriter.WriterError.NoError:
    raise RuntimeError(f"No se pudo escribir {GPKG}: {res[1]}")

uri = f"{GPKG}|layername={CAPA_NOMBRE}"
# refrescar si ya está cargada; si no, cargarla
cargada = None
for lyr in QgsProject.instance().mapLayers().values():
    if lyr.source().split("|")[0] == GPKG and CAPA_NOMBRE in lyr.source():
        cargada = lyr
        break
if cargada is not None:
    cargada.dataProvider().reloadData()
    cargada.updateExtents()
    cargada.triggerRepaint()
else:
    capa_gpkg = QgsVectorLayer(uri, "offsets_acumulados", "ogr")
    if capa_gpkg.isValid():
        QgsProject.instance().addMapLayer(capa_gpkg)
        cargada = capa_gpkg

total = cargada.featureCount() if cargada else len(feats)
print(f"Offset {distancia} m: {len(feats)} de {len(sel)} segmentos añadidos → "
      f"{GPKG} (total acumulado: {total}).")
