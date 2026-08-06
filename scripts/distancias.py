# -*- coding: utf-8 -*-
"""distancias — capa con campos id/meters/miles: longitud calculada en
coordenadas planas (UTM) y salida geodésica EPSG:4326, GUARDADA físicamente.

Convención de nombres (adoptar_nombre): la capa NUEVA queda con el nombre base
(ej. LANELET) y la ORIGINAL se renombra LANELET_distancias en el panel. Si el
archivo de salida chocara con el de la capa original, el original se rota a
<base>_distancias.geojson y el lienzo se actualiza a la nueva ruta.
"""
import os
import shutil

from qgis.PyQt.QtCore import QMetaType
from qgis.core import (QgsProject, QgsVectorLayer, QgsField, QgsFeature,
                       QgsGeometry, QgsCoordinateReferenceSystem,
                       QgsCoordinateTransform, QgsVectorFileWriter,
                       QgsWkbTypes)

if "LAYER_NAME" not in globals() or not LAYER_NAME:
    raise ValueError("Selecciona la capa de entrada.")
if "FIELD_ID" not in globals() or not FIELD_ID:
    FIELD_ID = "id"
if "UTM_EPSG" not in globals():
    UTM_EPSG = 32612
if "CARPETA_SALIDA" not in globals():
    CARPETA_SALIDA = None   # vacío = carpeta del archivo de la capa original

PROCESO = "distancias"

if "adoptar_nombre" not in globals():
    def adoptar_nombre(nombre_base, capa_nueva, capa_original=None, proceso="original"):
        if capa_original is not None:
            capa_original.setName(f"{nombre_base}_{proceso}")
        capa_nueva.setName(nombre_base)
        return capa_nueva

capas = QgsProject.instance().mapLayersByName(LAYER_NAME)
if not capas:
    raise ValueError(f"No hay capa '{LAYER_NAME}' en el proyecto.")
capa = capas[0]

# ------------------- resolver ruta física de salida ------------------------
src = capa.source().split("|")[0]
src = src if os.path.isfile(src) else None
carpeta = (CARPETA_SALIDA or "").strip() or (os.path.dirname(src) if src else None)
if not carpeta:
    raise ValueError(f"'{LAYER_NAME}' es una capa temporal: indica la carpeta de salida.")
os.makedirs(carpeta, exist_ok=True)
ruta_nueva = os.path.join(carpeta, f"{LAYER_NAME}.geojson")


def _norm(p):
    return os.path.normcase(os.path.normpath(p))


rotada = None
if src and _norm(ruta_nueva) == _norm(src):
    # el resultado ocuparía el archivo de la capa original: rotar el original.
    # En Windows QGIS bloquea el rename del archivo cargado, pero permite
    # copiar y reescribir: se COPIA el original a _<proceso> y se reapunta la
    # capa a la copia; el archivo base queda libre para el resultado nuevo.
    base, ext = os.path.splitext(src)
    rotada = f"{base}_{PROCESO}{ext}"
    if os.path.exists(rotada):
        raise RuntimeError(f"Ya existe {rotada}; muévelo o bórralo antes de repetir.")
    shutil.copy2(src, rotada)
    capa.setDataSource(rotada, f"{LAYER_NAME}_{PROCESO}", "ogr")  # lienzo actualizado
elif os.path.exists(ruta_nueva):
    raise RuntimeError(f"Ya existe {ruta_nueva}; no se sobrescribe. "
                       f"Elige otra carpeta o muévelo.")

# ------------------------------ cálculo ------------------------------------
crs_utm = QgsCoordinateReferenceSystem(f"EPSG:{UTM_EPSG}")
proyecto = QgsProject.instance()
tr_utm = QgsCoordinateTransform(capa.crs(), crs_utm, proyecto)
tr_out = QgsCoordinateTransform(capa.crs(),
                                QgsCoordinateReferenceSystem("EPSG:4326"), proyecto)

tipo = QgsWkbTypes.displayString(capa.wkbType())
out = QgsVectorLayer(f"{tipo}?crs=EPSG:4326", "tmp_distancias", "memory")
prov = out.dataProvider()
prov.addAttributes([QgsField(FIELD_ID, QMetaType.Type.LongLong),
                    QgsField("meters", QMetaType.Type.Double),
                    QgsField("miles", QMetaType.Type.Double)])
out.updateFields()

idx_id = capa.fields().indexOf(FIELD_ID)
feats = []
for f in capa.getFeatures():
    g = f.geometry()
    if g is None or g.isEmpty():
        continue
    g_utm = QgsGeometry(g)
    g_utm.transform(tr_utm)
    metros = g_utm.length()
    g_out = QgsGeometry(g)
    g_out.transform(tr_out)
    nf = QgsFeature(out.fields())
    nf.setGeometry(g_out)
    ident = f[FIELD_ID] if idx_id >= 0 else f.id()
    try:
        ident = int(ident)
    except (TypeError, ValueError):
        ident = f.id()
    nf.setAttributes([ident, metros, metros / 1609.344])
    feats.append(nf)

prov.addFeatures(feats)
out.updateExtents()

# --------------------- guardar físicamente y cargar ------------------------
opts = QgsVectorFileWriter.SaveVectorOptions()
opts.driverName = "GeoJSON"
opts.fileEncoding = "UTF-8"
res = QgsVectorFileWriter.writeAsVectorFormatV3(out, ruta_nueva,
                                                proyecto.transformContext(), opts)
if res[0] != QgsVectorFileWriter.WriterError.NoError:
    raise RuntimeError(f"No se pudo escribir {ruta_nueva}: {res[1]}")

nueva = QgsVectorLayer(ruta_nueva, LAYER_NAME, "ogr")
if not nueva.isValid():
    raise RuntimeError(f"Se escribió pero no se pudo cargar: {ruta_nueva}")
proyecto.addMapLayer(nueva)
adoptar_nombre(LAYER_NAME, nueva, capa, proceso=PROCESO)

print(f"{LAYER_NAME}: {len(feats)} entidades → {ruta_nueva} "
      f"(longitud plana EPSG:{UTM_EPSG}, salida EPSG:4326).")
print(f"Capa original renombrada a {LAYER_NAME}_{PROCESO}"
      + (f" (archivo rotado a {os.path.basename(rotada)})" if rotada else "") + ".")
