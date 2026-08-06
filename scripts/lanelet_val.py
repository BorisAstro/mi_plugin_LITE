# -*- coding: utf-8 -*-
"""lanelet_val — validación/QC de LANELET contra capas de apoyo (fusión de
lanelet_val + 04ok_laneletqc; código original de 04ok_laneletqc.py).

Para cada lanelet busca sus left_line_id / right_line_id en LANE_MARKER,
VIRTUAL_LINE y TURNING_LINE, mide distancias y clasifica:
  OK / LEFT_FAIL / RIGHT_FAIL / BOTH_FAIL
Salida: capa temporal 'lanelet_validacion' con simbología por estado y campos
left_dist, right_dist, check_left, check_right, status.

Nota: BUFFER_DIST y DIST_TOLERANCE están en unidades del CRS de la capa
LANELET (grados si es EPSG:4326, metros si es UTM).
"""

from qgis.core import (
    QgsCategorizedSymbolRenderer,
    QgsFeature,
    QgsField,
    QgsFields,
    QgsProject,
    QgsRendererCategory,
    QgsSymbol,
    QgsVectorLayer,
)
from qgis.PyQt.QtCore import QMetaType
from qgis.PyQt.QtGui import QColor

# ----------------------- parámetros (inyectados por la UI) -----------------
if "nombre_lanelet" not in globals():
    nombre_lanelet = "LANELET"
if "nombre_lane_marker" not in globals():
    nombre_lane_marker = "LANE_MARKER"
if "nombre_virtual_line" not in globals():
    nombre_virtual_line = "VIRTUAL_LINE"
if "nombre_turning_line" not in globals():
    nombre_turning_line = "TURNING_LINE"
if "BUFFER_DIST" not in globals():
    BUFFER_DIST = 2.0        # buffer alrededor del lanelet
if "DIST_TOLERANCE" not in globals():
    DIST_TOLERANCE = 2.0     # distancia máxima considerada correcta
if "OUTPUT_TXT" not in globals():
    OUTPUT_TXT = None        # vacío = junto al archivo de la capa LANELET

import os
import tempfile
from datetime import datetime

_LOG = []


def out(s=""):
    print(s)
    _LOG.append(str(s))


def guardar_reporte(capa_ref):
    ruta = (OUTPUT_TXT or "").strip() or None
    if ruta is None:
        src = capa_ref.source().split("|")[0]
        carpeta = os.path.dirname(src) if os.path.isfile(src) else tempfile.gettempdir()
        ruta = os.path.join(
            carpeta, f"lanelet_val_{datetime.now().strftime('%Y%m%d_%H%M%S')}.txt")
    with open(ruta, "w", encoding="utf-8") as fh:
        fh.write("\n".join(_LOG))
    print(f"Reporte guardado: {ruta}")


def capa_por_nombre(nombre):
    capas = QgsProject.instance().mapLayersByName(nombre)
    if not capas:
        raise RuntimeError(f"No se encontró la capa '{nombre}' en el proyecto.")
    return capas[0]


lanelet_layer = capa_por_nombre(nombre_lanelet)
lane_marker_layer = capa_por_nombre(nombre_lane_marker)
virtual_line_layer = capa_por_nombre(nombre_virtual_line)
turning_line_layer = capa_por_nombre(nombre_turning_line)


# ----------------------------- índices por ID ------------------------------
def build_id_index(layer):
    """Diccionario id -> feature para acceso rápido."""
    idx = {}
    id_idx = layer.fields().indexOf("id")
    if id_idx < 0:
        raise RuntimeError(f"La capa '{layer.name()}' no tiene campo 'id'.")
    for f in layer.getFeatures():
        idx[f["id"]] = f
    return idx


lm_idx = build_id_index(lane_marker_layer)
vl_idx = build_id_index(virtual_line_layer)
tl_idx = build_id_index(turning_line_layer)


def get_by_id(id_val):
    """Busca una feature por ID en las tres capas de apoyo."""
    if id_val is None:
        return None
    for idx in (lm_idx, vl_idx, tl_idx):
        if id_val in idx:
            return idx[id_val]
    return None


# --------------------------- capa de resultados ----------------------------
crs_authid = lanelet_layer.crs().authid() or "EPSG:32615"
mem_layer = QgsVectorLayer(f"LineString?crs={crs_authid}",
                           "lanelet_validacion", "memory")
prov = mem_layer.dataProvider()

out_fields = QgsFields()
for f in lanelet_layer.fields():
    out_fields.append(f)
out_fields.append(QgsField("left_dist", QMetaType.Type.Double))
out_fields.append(QgsField("right_dist", QMetaType.Type.Double))
out_fields.append(QgsField("check_left", QMetaType.Type.QString))
out_fields.append(QgsField("check_right", QMetaType.Type.QString))
out_fields.append(QgsField("status", QMetaType.Type.QString))

prov.addAttributes(list(out_fields))
mem_layer.updateFields()

# ----------------------------- procesamiento -------------------------------
conteo = {"OK": 0, "LEFT_FAIL": 0, "RIGHT_FAIL": 0, "BOTH_FAIL": 0}

for feat in lanelet_layer.getFeatures():
    geom = feat.geometry()
    left_feat = get_by_id(feat["left_line_id"])
    right_feat = get_by_id(feat["right_line_id"])

    left_dist = right_dist = None
    check_left = check_right = "NO"
    buffer_geom = geom.buffer(BUFFER_DIST, 8)

    if left_feat:
        lgeom = left_feat.geometry()
        left_dist = geom.distance(lgeom)
        if left_dist <= DIST_TOLERANCE or buffer_geom.intersects(lgeom):
            check_left = "SI"

    if right_feat:
        rgeom = right_feat.geometry()
        right_dist = geom.distance(rgeom)
        if right_dist <= DIST_TOLERANCE or buffer_geom.intersects(rgeom):
            check_right = "SI"

    if check_left == "SI" and check_right == "SI":
        status = "OK"
    elif check_left != "SI" and check_right == "SI":
        status = "LEFT_FAIL"
    elif check_left == "SI" and check_right != "SI":
        status = "RIGHT_FAIL"
    else:
        status = "BOTH_FAIL"
    conteo[status] += 1

    new_feat = QgsFeature(out_fields)
    new_feat.setGeometry(geom)
    new_feat.setAttributes(list(feat.attributes())
                           + [left_dist, right_dist, check_left, check_right, status])
    prov.addFeature(new_feat)

mem_layer.updateExtents()
QgsProject.instance().addMapLayer(mem_layer)

# ------------------------------ simbología ---------------------------------
colores = [("OK", QColor(0, 180, 0), "OK ambos lados"),
           ("LEFT_FAIL", QColor(255, 200, 0), "Falla lado izquierdo"),
           ("RIGHT_FAIL", QColor(0, 150, 255), "Falla lado derecho"),
           ("BOTH_FAIL", QColor(220, 0, 0), "Falla ambos lados")]
categories = []
for valor, color, etiqueta in colores:
    sym = QgsSymbol.defaultSymbol(mem_layer.geometryType())
    sym.setColor(color)
    categories.append(QgsRendererCategory(valor, sym, etiqueta))

mem_layer.setRenderer(QgsCategorizedSymbolRenderer("status", categories))
mem_layer.triggerRepaint()

total = sum(conteo.values())
out("REPORTE lanelet_val — validación LANELET vs capas de apoyo")
out("=" * 60)
out(f"fecha: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
out(f"LANELET: {nombre_lanelet}  |  LANE_MARKER: {nombre_lane_marker}  |  "
    f"VIRTUAL_LINE: {nombre_virtual_line}  |  TURNING_LINE: {nombre_turning_line}")
out(f"BUFFER_DIST: {BUFFER_DIST}  |  DIST_TOLERANCE: {DIST_TOLERANCE} "
    f"(unidades del CRS de {nombre_lanelet})")
out(f"total lanelets: {total}")
out()
for k in ("OK", "LEFT_FAIL", "RIGHT_FAIL", "BOTH_FAIL"):
    n = conteo[k]
    pct = 100.0 * n / total if total else 0
    out(f"  {k}: {n}  ({pct:.1f}%)")
fallas = total - conteo["OK"]
out()
out(f"lanelets con alguna falla: {fallas} ({100.0*fallas/total if total else 0:.1f}%)")
out("Capa 'lanelet_validacion' creada con simbología por estado.")

guardar_reporte(lanelet_layer)
