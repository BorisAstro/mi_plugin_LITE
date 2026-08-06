from qgis.PyQt.QtCore import QVariant
from qgis.core import (
    QgsProject,
    QgsVectorLayer,
    QgsFeature,
    QgsGeometry,
    QgsField,
    QgsSpatialIndex,
    QgsRectangle,
    QgsWkbTypes,
    QgsCoordinateTransform,
    QgsCoordinateReferenceSystem,
    QgsPointXY
)
import os
import math

# ============================================================
# CONFIGURACIÓN
# ============================================================

# Inyectado por la UI del plugin (lista separada por comas)
if "LAYER_NAMES" not in globals():
    LAYER_NAMES = ["VIRTUAL_LINE", "LANE_MARKER", "CURBSTONE", "TURNING_LINE"]

# Si las capas ya están cargadas en QGIS, deja None.
# Si no, puedes poner aquí las rutas a los GeoJSON.
LAYER_PATHS = {
    "virtual_line": None,
    "lane_marker": None,
    "curbestone": None,
    "turning_line": None,
}

# CRS de trabajo temporal para cálculos métricos (inyectado por la UI
# como texto "EPSG:xxxxx"; métrico, ej. 32612 zona 12 / 32615 zona 15)
if "WORK_CRS" not in globals() or not WORK_CRS:
    WORK_CRS = "EPSG:32615"
if isinstance(WORK_CRS, str):
    WORK_CRS = QgsCoordinateReferenceSystem(WORK_CRS)
if not WORK_CRS.isValid():
    raise ValueError("CRS de trabajo inválido.")

# CRS de salida para visualizar encima de las capas originales
if "OUTPUT_CRS" not in globals() or not OUTPUT_CRS:
    OUTPUT_CRS = "EPSG:4326"
if isinstance(OUTPUT_CRS, str):
    OUTPUT_CRS = QgsCoordinateReferenceSystem(OUTPUT_CRS)
if not OUTPUT_CRS.isValid():
    raise ValueError("CRS de salida inválido.")

# Tolerancias en metros, porque el análisis se hace en EPSG:32615
CONNECT_TOL = 0.05        # conexión real entre endpoint-endpoint o endpoint-línea
GAP_TOL = 0.50            # hueco detectable entre endpoints
SNAP_TOL = 0.75           # endpoint cerca de otra línea, pero sin tocarla
OVERLAP_MIN_LENGTH = 0.10 # solape mínimo para reportar

REPORT_DANGLING = True
CHECK_OVERLAPS = True

POINT_ERROR_LAYER_NAME = "topology_errors_points_4326"
LINE_ERROR_LAYER_NAME = "topology_errors_lines_4326"

# ============================================================
# UTILIDADES
# ============================================================

def log(msg):
    print(msg)

def remove_layer_if_exists(layer_name):
    for lyr in QgsProject.instance().mapLayersByName(layer_name):
        QgsProject.instance().removeMapLayer(lyr.id())

def point_distance(p1, p2):
    return math.hypot(p1.x() - p2.x(), p1.y() - p2.y())

def point_bbox(pt, tol):
    return QgsRectangle(pt.x() - tol, pt.y() - tol, pt.x() + tol, pt.y() + tol)

def get_layer_by_name_or_path(name, path=None):
    layers = QgsProject.instance().mapLayersByName(name)
    if layers:
        return layers[0]

    if path:
        if not os.path.exists(path):
            raise Exception(f"No existe el archivo para la capa '{name}': {path}")
        vl = QgsVectorLayer(path, name, "ogr")
        if not vl.isValid():
            raise Exception(f"No se pudo cargar la capa '{name}'")
        QgsProject.instance().addMapLayer(vl)
        return vl

    raise Exception(f"No se encontró la capa '{name}' y no se indicó ruta.")

def transform_geometry(geom, src_crs, dst_crs):
    if geom is None:
        return None
    if src_crs.authid() == dst_crs.authid():
        return QgsGeometry(geom)

    g = QgsGeometry(geom)
    tr = QgsCoordinateTransform(src_crs, dst_crs, QgsProject.instance())
    result = g.transform(tr)
    if result != 0:
        raise Exception(f"Error transformando geometría de {src_crs.authid()} a {dst_crs.authid()}")
    return g

def transform_point(pt, src_crs, dst_crs):
    if pt is None:
        return None
    if src_crs.authid() == dst_crs.authid():
        return QgsPointXY(pt)
    tr = QgsCoordinateTransform(src_crs, dst_crs, QgsProject.instance())
    return tr.transform(pt)

def extract_line_parts(geom):
    if geom is None or geom.isEmpty():
        return []

    if QgsWkbTypes.geometryType(geom.wkbType()) != QgsWkbTypes.LineGeometry:
        return []

    parts = []
    if geom.isMultipart():
        multi = geom.asMultiPolyline()
        for p in multi:
            if p and len(p) >= 2:
                parts.append(p)
    else:
        p = geom.asPolyline()
        if p and len(p) >= 2:
            parts.append(p)

    return parts

def to_output_geometry(geom_work):
    if geom_work is None or geom_work.isEmpty():
        return None
    return transform_geometry(geom_work, WORK_CRS, OUTPUT_CRS)

def ensure_multiline(geom):
    if geom is None or geom.isEmpty():
        return geom
    g = QgsGeometry(geom)
    if not g.isMultipart():
        g.convertToMultiType()
    return g

def create_point_error_layer():
    remove_layer_if_exists(POINT_ERROR_LAYER_NAME)
    layer = QgsVectorLayer(f"Point?crs={OUTPUT_CRS.authid()}", POINT_ERROR_LAYER_NAME, "memory")
    pr = layer.dataProvider()
    pr.addAttributes([
        QgsField("error_type", QVariant.String),
        QgsField("src_layer", QVariant.String),
        QgsField("src_fid", QVariant.LongLong),
        QgsField("src_part", QVariant.Int),
        QgsField("endpoint", QVariant.String),
        QgsField("other_layer", QVariant.String),
        QgsField("other_fid", QVariant.LongLong),
        QgsField("dist_m", QVariant.Double),
        QgsField("message", QVariant.String),
    ])
    layer.updateFields()
    return layer

def create_line_error_layer():
    remove_layer_if_exists(LINE_ERROR_LAYER_NAME)
    layer = QgsVectorLayer(f"MultiLineString?crs={OUTPUT_CRS.authid()}", LINE_ERROR_LAYER_NAME, "memory")
    pr = layer.dataProvider()
    pr.addAttributes([
        QgsField("error_type", QVariant.String),
        QgsField("src_layer", QVariant.String),
        QgsField("src_fid", QVariant.LongLong),
        QgsField("other_layer", QVariant.String),
        QgsField("other_fid", QVariant.LongLong),
        QgsField("length_m", QVariant.Double),
        QgsField("message", QVariant.String),
    ])
    layer.updateFields()
    return layer

# ============================================================
# CARGA DE CAPAS
# ============================================================

layers = {}
for name in LAYER_NAMES:
    layers[name] = get_layer_by_name_or_path(name, LAYER_PATHS.get(name))

for name, lyr in layers.items():
    if not lyr.isValid():
        raise Exception(f"La capa '{name}' no es válida.")

log("Capas cargadas correctamente.")
log(f"CRS temporal de trabajo: {WORK_CRS.authid()}")
log(f"CRS de salida: {OUTPUT_CRS.authid()}")
log("Las capas originales no serán modificadas.")

# ============================================================
# CAPAS DE SALIDA
# ============================================================

point_err_layer = create_point_error_layer()
line_err_layer = create_line_error_layer()

point_err_features = []
line_err_features = []
summary = {}

def inc(err_type):
    summary[err_type] = summary.get(err_type, 0) + 1

def add_point_error(pt_work, err_type, src_layer, src_fid, src_part, endpoint, other_layer, other_fid, dist_m, message):
    f = QgsFeature(point_err_layer.fields())
    if pt_work is not None:
        pt_out = transform_point(pt_work, WORK_CRS, OUTPUT_CRS)
        f.setGeometry(QgsGeometry.fromPointXY(pt_out))
    f.setAttributes([
        err_type,
        src_layer,
        int(src_fid) if src_fid is not None else None,
        int(src_part) if src_part is not None else None,
        endpoint,
        other_layer,
        int(other_fid) if other_fid is not None else None,
        float(dist_m) if dist_m is not None else None,
        message
    ])
    point_err_features.append(f)
    inc(err_type)

def add_line_error(geom_work, err_type, src_layer, src_fid, other_layer, other_fid, length_m, message):
    f = QgsFeature(line_err_layer.fields())
    geom_out = to_output_geometry(geom_work)
    if geom_out is not None:
        geom_out = ensure_multiline(geom_out)
        f.setGeometry(geom_out)
    f.setAttributes([
        err_type,
        src_layer,
        int(src_fid) if src_fid is not None else None,
        other_layer,
        int(other_fid) if other_fid is not None else None,
        float(length_m) if length_m is not None else None,
        message
    ])
    line_err_features.append(f)
    inc(err_type)

# ============================================================
# INDEXADO EN CRS TEMPORAL EPSG:32615
# ============================================================

line_records = {}
endpoint_records = {}

line_index = QgsSpatialIndex()
endpoint_index = QgsSpatialIndex()

line_internal_id = 0
endpoint_internal_id = 0

for layer_name, layer in layers.items():
    if QgsWkbTypes.geometryType(layer.wkbType()) != QgsWkbTypes.LineGeometry:
        raise Exception(f"La capa '{layer_name}' no es de tipo línea.")

    src_crs = layer.crs()

    for feat in layer.getFeatures():
        geom_src = feat.geometry()

        if geom_src is None:
            add_point_error(
                pt_work=None,
                err_type="null_geometry",
                src_layer=layer_name,
                src_fid=feat.id(),
                src_part=None,
                endpoint=None,
                other_layer=None,
                other_fid=None,
                dist_m=None,
                message="Geometría nula"
            )
            continue

        if geom_src.isEmpty():
            add_point_error(
                pt_work=None,
                err_type="empty_geometry",
                src_layer=layer_name,
                src_fid=feat.id(),
                src_part=None,
                endpoint=None,
                other_layer=None,
                other_fid=None,
                dist_m=None,
                message="Geometría vacía"
            )
            continue

        geom_work = transform_geometry(geom_src, src_crs, WORK_CRS)

        if not geom_work.isGeosValid():
            centroid = geom_work.centroid()
            pt_work = centroid.asPoint() if centroid and not centroid.isEmpty() else None
            add_point_error(
                pt_work=pt_work,
                err_type="invalid_geometry",
                src_layer=layer_name,
                src_fid=feat.id(),
                src_part=None,
                endpoint=None,
                other_layer=None,
                other_fid=None,
                dist_m=None,
                message="Geometría inválida según GEOS"
            )

        parts = extract_line_parts(geom_work)
        if not parts:
            centroid = geom_work.centroid()
            pt_work = centroid.asPoint() if centroid and not centroid.isEmpty() else None
            add_point_error(
                pt_work=pt_work,
                err_type="invalid_or_non_line",
                src_layer=layer_name,
                src_fid=feat.id(),
                src_part=None,
                endpoint=None,
                other_layer=None,
                other_fid=None,
                dist_m=None,
                message="No se pudo interpretar como línea válida"
            )
            continue

        for part_idx, pts in enumerate(parts):
            if len(pts) < 2:
                continue

            part_geom = QgsGeometry.fromPolylineXY(pts)

            line_records[line_internal_id] = {
                "id": line_internal_id,
                "layer": layer_name,
                "fid": feat.id(),
                "part": part_idx,
                "geom": part_geom,
                "start": pts[0],
                "end": pts[-1]
            }

            idx_feat = QgsFeature()
            idx_feat.setId(line_internal_id)
            idx_feat.setGeometry(part_geom)
            line_index.addFeature(idx_feat)

            for endpoint_name, pt in [("start", pts[0]), ("end", pts[-1])]:
                endpoint_records[endpoint_internal_id] = {
                    "id": endpoint_internal_id,
                    "layer": layer_name,
                    "fid": feat.id(),
                    "part": part_idx,
                    "endpoint": endpoint_name,
                    "point": pt,
                    "line_id": line_internal_id
                }
                ep_feat = QgsFeature()
                ep_feat.setId(endpoint_internal_id)
                ep_feat.setGeometry(QgsGeometry.fromPointXY(pt))
                endpoint_index.addFeature(ep_feat)
                endpoint_internal_id += 1

            line_internal_id += 1

log(f"Líneas indexadas en temporal: {len(line_records)}")
log(f"Endpoints indexados en temporal: {len(endpoint_records)}")

# ============================================================
# VALIDACIÓN DE ENDPOINTS
# ============================================================

for ep_id, ep in endpoint_records.items():
    pt = ep["point"]
    pt_geom = QgsGeometry.fromPointXY(pt)

    connected = False
    gap_candidates = []
    near_line_candidate = None

    # Buscar endpoints cercanos
    candidate_ep_ids = endpoint_index.intersects(point_bbox(pt, GAP_TOL))
    for other_ep_id in candidate_ep_ids:
        if other_ep_id == ep_id:
            continue

        other = endpoint_records[other_ep_id]

        if (
            ep["layer"] == other["layer"] and
            ep["fid"] == other["fid"] and
            ep["part"] == other["part"] and
            ep["endpoint"] == other["endpoint"]
        ):
            continue

        d = point_distance(pt, other["point"])

        if d <= CONNECT_TOL:
            connected = True
            break
        elif d <= GAP_TOL:
            gap_candidates.append((d, other))

    if connected:
        continue

    # Buscar proximidad a otra línea
    candidate_line_ids = line_index.intersects(point_bbox(pt, SNAP_TOL))
    on_line = False

    for cand_line_id in candidate_line_ids:
        lrec = line_records[cand_line_id]

        if cand_line_id == ep["line_id"]:
            continue

        d = lrec["geom"].distance(pt_geom)

        if d <= CONNECT_TOL:
            on_line = True
            break

        if d <= SNAP_TOL:
            if near_line_candidate is None or d < near_line_candidate[0]:
                near_line_candidate = (d, lrec)

    if on_line:
        continue

    # Clasificación
    if gap_candidates:
        dmin, other = sorted(gap_candidates, key=lambda x: x[0])[0]
        add_point_error(
            pt_work=pt,
            err_type="gap_between_endpoints",
            src_layer=ep["layer"],
            src_fid=ep["fid"],
            src_part=ep["part"],
            endpoint=ep["endpoint"],
            other_layer=other["layer"],
            other_fid=other["fid"],
            dist_m=dmin,
            message="Endpoint cerca de otro endpoint, pero sin conexión dentro de tolerancia"
        )
    elif near_line_candidate is not None:
        dmin, other_line = near_line_candidate
        add_point_error(
            pt_work=pt,
            err_type="endpoint_near_line_not_snapped",
            src_layer=ep["layer"],
            src_fid=ep["fid"],
            src_part=ep["part"],
            endpoint=ep["endpoint"],
            other_layer=other_line["layer"],
            other_fid=other_line["fid"],
            dist_m=dmin,
            message="Endpoint cerca de otra línea, pero no está ajustado sobre ella"
        )
    elif REPORT_DANGLING:
        add_point_error(
            pt_work=pt,
            err_type="dangling_endpoint",
            src_layer=ep["layer"],
            src_fid=ep["fid"],
            src_part=ep["part"],
            endpoint=ep["endpoint"],
            other_layer=None,
            other_fid=None,
            dist_m=None,
            message="Extremo colgante sin conexión"
        )

# ============================================================
# VALIDACIÓN DE SOLAPES
# ============================================================

if CHECK_OVERLAPS:
    visited = set()

    for lid, rec in line_records.items():
        candidate_ids = line_index.intersects(rec["geom"].boundingBox())

        for other_id in candidate_ids:
            if other_id == lid:
                continue

            pair = tuple(sorted((lid, other_id)))
            if pair in visited:
                continue
            visited.add(pair)

            other = line_records[other_id]

            if not rec["geom"].boundingBox().intersects(other["geom"].boundingBox()):
                continue

            if not rec["geom"].intersects(other["geom"]):
                continue

            inter = rec["geom"].intersection(other["geom"])
            if inter.isEmpty():
                continue

            if QgsWkbTypes.geometryType(inter.wkbType()) == QgsWkbTypes.LineGeometry:
                inter_len = inter.length()
                if inter_len >= OVERLAP_MIN_LENGTH:
                    add_line_error(
                        geom_work=inter,
                        err_type="line_overlap",
                        src_layer=rec["layer"],
                        src_fid=rec["fid"],
                        other_layer=other["layer"],
                        other_fid=other["fid"],
                        length_m=inter_len,
                        message="Solape lineal entre dos entidades"
                    )

# ============================================================
# AÑADIR CAPAS DE SALIDA
# ============================================================

if point_err_features:
    point_err_layer.dataProvider().addFeatures(point_err_features)
    point_err_layer.updateExtents()
    QgsProject.instance().addMapLayer(point_err_layer)
    log(f"Capa creada: {POINT_ERROR_LAYER_NAME}")
else:
    log("No se detectaron errores puntuales.")

if line_err_features:
    line_err_layer.dataProvider().addFeatures(line_err_features)
    line_err_layer.updateExtents()
    QgsProject.instance().addMapLayer(line_err_layer)
    log(f"Capa creada: {LINE_ERROR_LAYER_NAME}")
else:
    log("No se detectaron errores lineales.")

# ============================================================
# RESUMEN
# ============================================================

log("")
log("===== RESUMEN =====")
if summary:
    for k in sorted(summary.keys()):
        log(f"{k}: {summary[k]}")
else:
    log("Sin errores detectados.")

log("Proceso terminado. Las capas originales permanecen intactas en EPSG:4326.")
