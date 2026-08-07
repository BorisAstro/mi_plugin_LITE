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

# Campos que se copian de la entidad a la capa de errores lineales, con
# prefijo src_ y oth_. Con LANELET, left/right_line_type permite decidir si un
# solape es un duplicado real o dos bordes distintos que comparten traza.
if "CAMPOS_EXTRA" not in globals():
    CAMPOS_EXTRA = ["left_line_id", "right_line_id",
                    "left_line_type", "right_line_type"]
if isinstance(CAMPOS_EXTRA, str):
    CAMPOS_EXTRA = [x.strip() for x in CAMPOS_EXTRA.split(",") if x.strip()]

# Dictamen de cada solape. Lo decisivo no es el TIPO de linea sino su ID: dos
# lanelets que comparten las dos lineas son la misma geometria repetida; si al
# menos un lado apunta a otra linea, la via se esta dividiendo y el solape es
# legitimo.
if "EXCLUIR_DICTAMEN" not in globals():
    EXCLUIR_DICTAMEN = []      # ej. ["DIVISION_VIA", "TURNING_DOBLE"]
if isinstance(EXCLUIR_DICTAMEN, str):
    EXCLUIR_DICTAMEN = [x.strip().upper() for x in EXCLUIR_DICTAMEN.split(",") if x.strip()]
else:
    EXCLUIR_DICTAMEN = [str(x).strip().upper() for x in EXCLUIR_DICTAMEN if str(x).strip()]

# Un grupo de N lanelets identicos produce N*(N-1)/2 pares. Agrupandolos se
# lista UNA fila por grupo, con todos los fid implicados: al corregirlo
# desaparece la fila entera en vez de quedar los pares restantes.
if "AGRUPAR_DUPLICADOS" not in globals():
    AGRUPAR_DUPLICADOS = True
if "GRUPO_SALIDA" not in globals():
    GRUPO_SALIDA = "TOPOLOGIA"   # vacio = capas sueltas en la raiz
if "ABRIR_TABLAS" not in globals():
    ABRIR_TABLAS = True

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
    for c in CAMPOS_EXTRA:
        pr.addAttributes([QgsField("src_" + c, QVariant.String),
                          QgsField("oth_" + c, QVariant.String)])
    pr.addAttributes([QgsField("dictamen", QVariant.String),
                      QgsField("motivo", QVariant.String),
                      QgsField("n_miembros", QVariant.Int),
                      QgsField("fids", QVariant.String)])
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

def _txt(v):
    if v is None:
        return None
    s_ = str(v).strip()
    return s_ or None


def dictaminar(a, b):
    """Veredicto binario + motivo.

    Dos lanelets son el MISMO si citan las mismas dos lineas de borde y
    ejecutan la misma maniobra. Cualquier diferencia -en un borde o en el
    giro- significa que son lanelets distintos que comparten traza, y el
    solape es legitimo. Antes esto se repartia en clases separadas
    (DIVISION_VIA, DISTINTO_GIRO, SOLAPE_DISTINTO) segun que senal delataba
    la diferencia, lo que confundia el criterio con la evidencia.
    """
    if not a or not b:
        return "SIN_DATOS", ""
    la, ra = _txt(a.get("left_line_id")), _txt(a.get("right_line_id"))
    lb, rb = _txt(b.get("left_line_id")), _txt(b.get("right_line_id"))
    ga, gb = _txt(a.get("turn_direction")), _txt(b.get("turn_direction"))
    ta = (_txt(a.get("left_line_type")), _txt(a.get("right_line_type")))
    tb = (_txt(b.get("left_line_type")), _txt(b.get("right_line_type")))

    if ta == ("turning", "turning") or tb == ("turning", "turning"):
        return "TURNING_DOBLE", "turning en ambos lados"
    if la is None and ra is None and lb is None and rb is None:
        return "SIN_REFERENCIAS", ""

    motivos = []
    if la != lb:
        motivos.append("left_line_id")
    if ra != rb:
        motivos.append("right_line_id")
    if ga != gb:
        motivos.append("turn_direction")
    if not motivos:
        return "DUPLICADO", ""
    return "NO_DUPLICADO", "+".join(motivos)


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

def add_line_error(geom_work, err_type, src_layer, src_fid, other_layer, other_fid,
                   length_m, message, src_extra=None, oth_extra=None,
                   n_miembros=None, fids_txt=None):
    dic, mot = (dictaminar(src_extra, oth_extra)
                if err_type == "line_overlap" else ("", ""))
    if dic and dic in EXCLUIR_DICTAMEN:
        return
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
    ] + [v for c in CAMPOS_EXTRA
         for v in (None if not src_extra else _txt(src_extra.get(c)),
                   None if not oth_extra else _txt(oth_extra.get(c)))]
      + [dic, mot, n_miembros, fids_txt])
    line_err_features.append(f)
    inc(err_type)
    inc("dictamen:" + dic + (" (%s)" % mot if mot else ""))

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

            campos_feat = [f.name() for f in layer.fields()]
            # los 4 del dictamen se leen siempre, aunque no se escriban
            necesarios = set(CAMPOS_EXTRA) | {"left_line_id", "right_line_id",
                                              "left_line_type", "right_line_type",
                                              "turn_direction"}
            extra = {c: (feat[c] if c in campos_feat else None)
                     for c in necesarios}
            line_records[line_internal_id] = {
                "id": line_internal_id,
                "layer": layer_name,
                "fid": feat.id(),
                "part": part_idx,
                "geom": part_geom,
                "start": pts[0],
                "end": pts[-1],
                "extra": extra
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

pares_dup = []

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
                    if AGRUPAR_DUPLICADOS:
                        d_prev, _m = dictaminar(rec.get("extra"), other.get("extra"))
                        if d_prev == "DUPLICADO":
                            pares_dup.append((rec, other, inter, inter_len))
                            continue
                    add_line_error(
                        geom_work=inter,
                        err_type="line_overlap",
                        src_layer=rec["layer"],
                        src_fid=rec["fid"],
                        other_layer=other["layer"],
                        other_fid=other["fid"],
                        length_m=inter_len,
                        message="Solape lineal entre dos entidades",
                        src_extra=rec.get("extra"),
                        oth_extra=other.get("extra")
                    )

# ============================================================
# AGRUPAR LOS DUPLICADOS EN UNA FILA POR GRUPO
# ============================================================
if pares_dup:
    padre = {}

    def raiz(x):
        while padre.get(x, x) != x:
            padre[x] = padre.get(padre[x], padre[x])
            x = padre[x]
        return x

    def unir(x, y):
        rx, ry = raiz(x), raiz(y)
        if rx != ry:
            padre[ry] = rx

    for a, b, _g, _l in pares_dup:
        ka, kb = (a["layer"], a["fid"]), (b["layer"], b["fid"])
        padre.setdefault(ka, ka)
        padre.setdefault(kb, kb)
        unir(ka, kb)

    grupos = {}
    for a, b, g, l in pares_dup:
        r = raiz((a["layer"], a["fid"]))
        d = grupos.setdefault(r, {"recs": {}, "geoms": [], "largo": 0.0})
        d["recs"][(a["layer"], a["fid"])] = a
        d["recs"][(b["layer"], b["fid"])] = b
        d["geoms"].append(g)
        d["largo"] = max(d["largo"], l)

    log("")
    log(f"Duplicados: {len(pares_dup)} pares -> {len(grupos)} grupos")
    for r, d in grupos.items():
        recs = list(d["recs"].values())
        fids = sorted(x["fid"] for x in recs)
        geo = d["geoms"][0]
        for extra_g in d["geoms"][1:]:
            geo = geo.combine(extra_g)
        add_line_error(
            geom_work=geo,
            err_type="line_overlap",
            src_layer=recs[0]["layer"],
            src_fid=fids[0],
            other_layer=recs[0]["layer"],
            other_fid=fids[1] if len(fids) > 1 else None,
            length_m=d["largo"],
            message=f"Grupo de {len(fids)} lanelets duplicados",
            src_extra=recs[0].get("extra"),
            oth_extra=recs[1].get("extra") if len(recs) > 1 else None,
            n_miembros=len(fids),
            fids_txt=",".join(str(x) for x in fids))

# ============================================================
# AÑADIR CAPAS DE SALIDA
# ============================================================

def _pintar(capa, campo, colores, ancho):
    """Sin renderer propio QGIS asigna un color aleatorio en cada ejecucion."""
    from qgis.core import (QgsCategorizedSymbolRenderer, QgsRendererCategory,
                           QgsSymbol, QgsWkbTypes)
    from qgis.PyQt.QtGui import QColor
    cats = []
    for valor, rgb, etq in colores:
        sim = QgsSymbol.defaultSymbol(capa.geometryType())
        sim.setColor(QColor(*rgb))
        if capa.geometryType() == QgsWkbTypes.GeometryType.LineGeometry:
            sim.setWidth(ancho)
        else:
            sim.setSize(ancho)
        cats.append(QgsRendererCategory(valor, sim, etq))
    capa.setRenderer(QgsCategorizedSymbolRenderer(campo, cats))
    capa.triggerRepaint()


COLOR_DICTAMEN = [
    ("DUPLICADO", (227, 26, 28, 255), "duplicado — revisar"),
    ("NO_DUPLICADO", (31, 120, 180, 255), "solape legitimo"),
    ("TURNING_DOBLE", (200, 0, 200, 255), "turning en ambos lados"),
    ("SIN_REFERENCIAS", (140, 140, 140, 255), "sin referencias"),
    ("SIN_DATOS", (90, 90, 90, 255), "sin datos"),
]
COLOR_PUNTO = [
    ("dangling_endpoint", (227, 26, 28, 255), "extremo colgante"),
    ("gap_between_endpoints", (255, 140, 0, 255), "hueco entre extremos"),
    ("endpoint_near_line_not_snapped", (255, 215, 0, 255), "sin ajustar"),
    ("null_geometry", (120, 120, 120, 255), "geometria nula"),
    ("empty_geometry", (120, 120, 120, 255), "geometria vacia"),
    ("invalid_geometry", (200, 0, 200, 255), "geometria invalida"),
    ("invalid_or_non_line", (90, 90, 90, 255), "no interpretable"),
]

# Grupo unico donde caen todas las salidas del script. Se rehace en cada
# corrida para no acumular capas viejas con el mismo nombre.
grupo_salida = None
if GRUPO_SALIDA:
    _raiz = QgsProject.instance().layerTreeRoot()
    _ant = _raiz.findGroup(GRUPO_SALIDA)
    if _ant is not None:
        _raiz.removeChildNode(_ant)
    grupo_salida = _raiz.insertGroup(0, GRUPO_SALIDA)


def publicar(capa_nueva):
    """Deja la capa dentro del grupo de salida, o en la raiz si no hay grupo."""
    if grupo_salida is None:
        QgsProject.instance().addMapLayer(capa_nueva)
    else:
        QgsProject.instance().addMapLayer(capa_nueva, False)
        grupo_salida.addLayer(capa_nueva)
    return capa_nueva


if point_err_features:
    point_err_layer.dataProvider().addFeatures(point_err_features)
    point_err_layer.updateExtents()
    _pintar(point_err_layer, "error_type", COLOR_PUNTO, 2.6)
    publicar(point_err_layer)
    log(f"Capa creada: {POINT_ERROR_LAYER_NAME}")
else:
    log("No se detectaron errores puntuales.")

if line_err_features:
    line_err_layer.dataProvider().addFeatures(line_err_features)
    line_err_layer.updateExtents()
    _pintar(line_err_layer, "dictamen", COLOR_DICTAMEN, 1.0)
    publicar(line_err_layer)
    log(f"Capa creada: {LINE_ERROR_LAYER_NAME}")
else:
    log("No se detectaron errores lineales.")

# ============================================================
# RESUMEN
# ============================================================

def abrir_tablas_lado_a_lado(izq, der):
    """Deja las dos tablas de atributos una junto a otra, sin recolocarlas a mano."""
    try:
        from qgis.PyQt.QtWidgets import QApplication
        # cerrar las tablas ya abiertas para no apilar ventanas al repetir el proceso.
        # QgsAttributeTableDialog no esta expuesta a Python, asi que se identifica
        # por el nombre de clase de su metaobjeto.
        import qgis.utils as _qu
        for w in QApplication.topLevelWidgets():
            try:
                if w.metaObject().className() == "QgsAttributeTableDialog":
                    w.close()
            except RuntimeError:
                pass
        _qu._mi_plugin_tablas = []
        QApplication.processEvents()
        pantalla = QApplication.primaryScreen().availableGeometry()
        anchura = pantalla.width() // 2
        alto = int(pantalla.height() * 0.42)
        y = pantalla.bottom() - alto + 1
        # las ventanas pertenecen a Python: sin una referencia viva se destruyen
        # en cuanto termina el script, asi que se guardan en un modulo persistente
        import qgis.utils as _qu
        _qu._mi_plugin_tablas = []
        abiertas = 0
        for capa, x in ((izq, pantalla.left()), (der, pantalla.left() + anchura)):
            if capa is None:
                continue
            dlg = iface.showAttributeTable(capa)
            if dlg is None:
                continue
            dlg.setWindowFlag(Qt.WindowType.Window, True)
            dlg.setGeometry(x, y, anchura, alto)
            dlg.show()
            dlg.raise_()
            QApplication.processEvents()
            _qu._mi_plugin_tablas.append(dlg)
            abiertas += 1
        log(f"Tablas abiertas lado a lado: {abiertas}")
        return True
    except Exception as e:
        log("  no se pudieron colocar las tablas: %s" % str(e)[:80])
        return False


if ABRIR_TABLAS and line_err_features:
    from qgis.PyQt.QtCore import Qt
    from qgis.utils import iface as _if
    iface = globals().get("iface", _if)
    principal = None
    for nombre_c in LAYER_NAMES:
        c = QgsProject.instance().mapLayersByName(nombre_c)
        if c:
            principal = c[0]
            break
    abrir_tablas_lado_a_lado(principal, line_err_layer)

log("")
log("===== RESUMEN =====")
if summary:
    for k in sorted(summary.keys()):
        log(f"{k}: {summary[k]}")
else:
    log("Sin errores detectados.")

log("Proceso terminado. Las capas originales permanecen intactas en EPSG:4326.")


# ############################################################################
# ANEXO QC (portado de lanelet_qc_consolidado)
# ----------------------------------------------------------------------------
# Bloque independiente y opcional. NO toca nada del analisis de topologia de
# arriba: solo lee capas y escribe tres capas nuevas en su propio grupo.
#   remapeo_propuesto    lados rotos del LANELET -> linea huerfana mas cercana
#   duplicados_sobrantes copias repetidas con el candidato que conviene guardar
#   obs_solapes          solapes lineales entre las capas base referenciables
# Todos los nombres llevan prefijo _ax_ para no colisionar con el script.
# ############################################################################

if "ANEXO_QC" not in globals():
    ANEXO_QC = False
if "ANEXO_LANELET" not in globals():
    ANEXO_LANELET = "LANELET"
if "ANEXO_REFERENCIABLES" not in globals():
    ANEXO_REFERENCIABLES = ["LANE_MARKER", "VIRTUAL_LINE", "TURNING_LINE"]
if "ANEXO_GEOMETRICAS" not in globals():
    ANEXO_GEOMETRICAS = ["CURBSTONE", "ROAD_EDGE"]
if "ANEXO_ID_FIELD" not in globals():
    ANEXO_ID_FIELD = "id"
if "ANEXO_TOL_LANELET" not in globals():
    ANEXO_TOL_LANELET = 3.5      # distancia maxima lanelet-linea, en metros
if "ANEXO_EPS" not in globals():
    ANEXO_EPS = 0.19             # tolerancia de gemelas desplazadas (offset 25 cm)
if "ANEXO_RATIO_DUP" not in globals():
    ANEXO_RATIO_DUP = 0.95       # proporcion minima para considerar duplicado
if "ANEXO_MIN_SOLAPE" not in globals():
    ANEXO_MIN_SOLAPE = 0.10      # solape minimo que se reporta, en metros
if "ANEXO_GRUPO" not in globals():
    ANEXO_GRUPO = "QC_ANEXO"


def _ax_run():
    from qgis.core import (QgsFields, QgsSymbol, QgsCategorizedSymbolRenderer,
                           QgsRendererCategory)
    from qgis.PyQt.QtCore import QMetaType
    from qgis.PyQt.QtGui import QColor
    import hashlib

    prj = QgsProject.instance()
    log("")
    log("===== ANEXO QC =====")

    def capa(nombre, obligatoria=True):
        c = prj.mapLayersByName(nombre)
        if c:
            return c[0]
        if obligatoria:
            raise RuntimeError("El anexo no encontro la capa '%s'." % nombre)
        return None

    def lista(v):
        if isinstance(v, (list, tuple)):
            return [str(x).strip() for x in v if str(x).strip()]
        return [x.strip() for x in str(v).split(",") if x.strip()]

    def nid(v):
        if v is None:
            return None
        s = str(v).strip()
        if s == "" or s.upper() in ("NULL", "NONE"):
            return None
        try:
            f = float(s)
            return int(f) if f.is_integer() else s
        except ValueError:
            return s

    def tr_a_work(cp):
        if cp.crs().authid() == WORK_CRS.authid():
            return None
        return QgsCoordinateTransform(cp.crs(), WORK_CRS, prj)

    def gw(g, tr):
        h = QgsGeometry(g)
        if tr is not None:
            h.transform(tr)
        return h

    # ---- grupo propio, separado del resto de salidas del script ----
    # cuelga del grupo de salida del script para que todo quede en un arbol,
    # pero en su propio subgrupo porque son resultados complementarios
    padre = grupo_salida if grupo_salida is not None else prj.layerTreeRoot()
    # barre tambien restos del mismo nombre colgados de la raiz por corridas
    # anteriores, que si no quedan como grupos vacios
    for viejo_g in [prj.layerTreeRoot().findGroup(ANEXO_GRUPO),
                    padre.findGroup(ANEXO_GRUPO)]:
        if viejo_g is None:
            continue
        for n_ in list(viejo_g.findLayers()):
            if n_.layer() is not None:
                prj.removeMapLayer(n_.layer().id())
        if viejo_g.parent() is not None:
            viejo_g.parent().removeChildNode(viejo_g)
    grupo = padre.insertGroup(0, ANEXO_GRUPO)

    def al_grupo(c):
        prj.addMapLayer(c, False)
        grupo.addLayer(c)
        return c

    def nueva(nombre, campos, tipo="LineString"):
        remove_layer_if_exists(nombre)
        c = QgsVectorLayer("%s?crs=%s" % (tipo, OUTPUT_CRS.authid())
                           if tipo != "None" else "None", nombre, "memory")
        fl = QgsFields()
        for n_, t_ in campos:
            fl.append(QgsField(n_, t_))
        c.dataProvider().addAttributes(list(fl))
        c.updateFields()
        return c, fl

    lanelet = capa(ANEXO_LANELET)
    capas_ref = lista(ANEXO_REFERENCIABLES)
    capas_geom = lista(ANEXO_GEOMETRICAS)

    # ---- cache de lineas base en el CRS metrico de trabajo ----
    registros, capas_base = {}, {}
    for nombre, clase in ([(n, "REFERENCIABLE") for n in capas_ref]
                          + [(n, "GEOMETRICA") for n in capas_geom]):
        cp = capa(nombre, obligatoria=False)
        if cp is None:
            log("  aviso: la capa '%s' no esta cargada, se omite." % nombre)
            continue
        if QgsWkbTypes.geometryType(cp.wkbType()) != QgsWkbTypes.LineGeometry:
            log("  aviso: '%s' no es de tipo linea, se omite." % nombre)
            continue
        if cp.fields().indexOf(ANEXO_ID_FIELD) < 0:
            log("  aviso: '%s' no tiene el campo '%s', se omite."
                % (nombre, ANEXO_ID_FIELD))
            continue
        tr = tr_a_work(cp)
        for f in cp.getFeatures():
            g = f.geometry()
            if g is None or g.isEmpty():
                continue
            h = gw(g, tr)
            registros[(nombre, f.id())] = {
                "key": (nombre, f.id()), "capa": nombre, "clase": clase,
                "fid": f.id(), "id": nid(f[ANEXO_ID_FIELD]),
                "geom": h, "len": h.length()}
        capas_base[nombre] = cp

    if not any(r["clase"] == "REFERENCIABLE" for r in registros.values()):
        log("  ninguna capa referenciable cargada; el anexo se detiene.")
        return
    log("  lineas base cacheadas: %d en %d capas" % (len(registros), len(capas_base)))

    # ---- pares geometricos: duplicados y solapes en una sola pasada ----
    orden = list(registros.values())
    indice = QgsSpatialIndex()
    for i, r in enumerate(orden):
        r["idx"] = i
        fi = QgsFeature()
        fi.setId(i)
        fi.setGeometry(r["geom"])
        indice.addFeature(fi)

    pares, solapes, vistos = [], [], set()
    for r in orden:
        bb = r["geom"].boundingBox()
        bb.grow(ANEXO_EPS)
        for j in indice.intersects(bb):
            if j == r["idx"]:
                continue
            par = (min(r["idx"], j), max(r["idx"], j))
            if par in vistos:
                continue
            vistos.add(par)
            a, b = orden[par[0]], orden[par[1]]
            if a["len"] <= 0 or b["len"] <= 0:
                continue
            r_a = r_b = 0.0
            if a["geom"].intersects(b["geom"]):
                inter = a["geom"].intersection(b["geom"])
                if (not inter.isEmpty() and QgsWkbTypes.geometryType(inter.wkbType())
                        == QgsWkbTypes.LineGeometry):
                    li = inter.length()
                    if li >= ANEXO_MIN_SOLAPE:
                        r_a, r_b = li / a["len"], li / b["len"]
                        solapes.append((a, b, inter, li))
            haus = None
            if not (r_a >= ANEXO_RATIO_DUP and r_b >= ANEXO_RATIO_DUP):
                try:
                    haus = a["geom"].hausdorffDistance(b["geom"])
                except Exception:
                    haus = None
            prop = min(a["len"], b["len"]) / max(a["len"], b["len"])
            es_dup = ((r_a >= ANEXO_RATIO_DUP and r_b >= ANEXO_RATIO_DUP)
                      or (haus is not None and haus <= ANEXO_EPS
                          and prop >= ANEXO_RATIO_DUP))
            if es_dup and a["clase"] == b["clase"]:
                pares.append({"a": a, "b": b})
    log("  pares duplicados en capas base: %d  |  solapes lineales: %d"
        % (len(pares), len(solapes)))

    # ---- estado de los lados del LANELET ----
    idx_ref = {r["id"]: r for r in registros.values()
               if r["clase"] == "REFERENCIABLE" and r["id"] is not None}
    REF = {}
    tr_ll = tr_a_work(lanelet)
    lanelets = []
    for f in lanelet.getFeatures():
        g = f.geometry()
        if g is None or g.isEmpty():
            continue
        h = gw(g, tr_ll)
        lados = {"left": nid(f["left_line_id"]), "right": nid(f["right_line_id"])}
        for lado, ident in lados.items():
            if ident is not None:
                REF.setdefault(ident, []).append((nid(f[ANEXO_ID_FIELD]), lado))
        estado = {}
        for lado, ident in lados.items():
            if ident is None:
                estado[lado] = "SIN_ID"
            else:
                rec = idx_ref.get(ident)
                if rec is None:
                    estado[lado] = "ID_INEXISTENTE"
                elif h.distance(rec["geom"]) > ANEXO_TOL_LANELET:
                    estado[lado] = "LEJOS"
                else:
                    estado[lado] = "OK"
        lanelets.append({"fid": f.id(), "id": nid(f[ANEXO_ID_FIELD]), "geom": h,
                         "lados": lados, "estado": estado})
    cont = {}
    for ll in lanelets:
        for lado in ("left", "right"):
            cont[ll["estado"][lado]] = cont.get(ll["estado"][lado], 0) + 1
    for k in ("OK", "SIN_ID", "ID_INEXISTENTE", "LEJOS"):
        if cont.get(k):
            log("  lados %-15s %d" % (k, cont[k]))
    huerfanas = [r for r in registros.values()
                 if r["clase"] == "REFERENCIABLE" and r["id"] not in REF]
    log("  lineas referenciables huerfanas (nunca citadas): %d" % len(huerfanas))

    # ---- remapeo_propuesto ----
    ind_h = QgsSpatialIndex()
    for i, r in enumerate(huerfanas):
        fi = QgsFeature()
        fi.setId(i)
        fi.setGeometry(r["geom"])
        ind_h.addFeature(fi)
    remapeos = []
    for ll in lanelets:
        for lado in ("left", "right"):
            motivo = ll["estado"][lado]
            if motivo == "OK":
                continue
            caja = ll["geom"].boundingBox()
            caja.grow(ANEXO_TOL_LANELET)
            cands = []
            for j in ind_h.intersects(caja):
                r = huerfanas[j]
                d = ll["geom"].distance(r["geom"])
                if d <= ANEXO_TOL_LANELET:
                    cands.append((d, r))
            if not cands:
                continue
            cands.sort(key=lambda x: x[0])
            d, r = cands[0]
            remapeos.append((ll["id"], lado, ll["lados"][lado], r["id"], r["capa"],
                             d, motivo,
                             "INEQUIVOCO" if len(cands) == 1
                             else "AMBIGUO (%d candidatas)" % len(cands)))
    ineq = sum(1 for x in remapeos if x[7] == "INEQUIVOCO")
    log("  remapeos propuestos: %d  (%d inequivocos, %d ambiguos)"
        % (len(remapeos), ineq, len(remapeos) - ineq))
    if remapeos:
        cap, fl = nueva("remapeo_propuesto",
                        [("lanelet_id", QMetaType.Type.QString),
                         ("lado", QMetaType.Type.QString),
                         ("id_actual", QMetaType.Type.QString),
                         ("id_propuesto", QMetaType.Type.QString),
                         ("capa_propuesta", QMetaType.Type.QString),
                         ("distancia_m", QMetaType.Type.Double),
                         ("motivo", QMetaType.Type.QString),
                         ("certeza", QMetaType.Type.QString)], tipo="None")
        fr = []
        for a, lado, act, prop, cp_, d, mot, cert in remapeos:
            f = QgsFeature(fl)
            f.setAttributes([str(a), lado, str(act), str(prop), cp_,
                             round(d, 3), mot, cert])
            fr.append(f)
        cap.dataProvider().addFeatures(fr)
        al_grupo(cap)

    # ---- duplicados_sobrantes ----
    def puntua_lanelet(ll):
        """Menor es mejor: lados rotos, luego distancia total, luego id."""
        rotos = sum(1 for s in ll["estado"].values() if s != "OK")
        dist = 0.0
        for ident in ll["lados"].values():
            rec = idx_ref.get(ident)
            dist += ll["geom"].distance(rec["geom"]) if rec is not None else 1e6
        idv = ll["id"] if isinstance(ll["id"], int) else 0
        return (rotos, round(dist, 3), idv)

    def puntua_base(r):
        """Mejor candidato en capas base: referenciada > larga > id bajo."""
        ref = 0 if r["id"] in REF else 1
        idv = r["id"] if isinstance(r["id"], int) else 0
        return (ref, -r["len"], idv)

    grupos_geom = {}
    for ll in lanelets:
        h = hashlib.md5(ll["geom"].asWkt(3).encode("utf-8")).hexdigest()
        grupos_geom.setdefault(h, []).append(ll)
    dup_ll = {h: v for h, v in grupos_geom.items() if len(v) > 1}

    ll_sobrantes, ll_conservados, vistos_ll = [], [], set()
    for h, v in dup_ll.items():
        v2 = sorted(v, key=puntua_lanelet)
        ll_conservados.append(v2[0])
        for x in v2[1:]:
            if x["fid"] not in vistos_ll:
                vistos_ll.add(x["fid"])
                ll_sobrantes.append(x)
    log("  grupos de LANELET con geometria repetida: %d  |  copias sobrantes: %d"
        % (len(dup_ll), len(ll_sobrantes)))

    base_sobrantes, base_conflicto = [], []
    for par in pares:
        a, b = par["a"], par["b"]
        if a["id"] in REF and b["id"] in REF:
            base_conflicto.append((a, b))
            continue
        base_sobrantes.append(sorted([a, b], key=puntua_base)[-1])
    vistos_k = set()
    base_sobrantes = [r for r in base_sobrantes
                      if not (r["key"] in vistos_k or vistos_k.add(r["key"]))]
    log("  copias sobrantes en capas base: %d  |  conflictos (ambas citadas): %d"
        % (len(base_sobrantes), len(base_conflicto)))

    filas = ([(r["geom"], r["capa"], r["id"], "SOBRANTE",
               "duplicado en capa base; no referenciado o mas corto")
              for r in base_sobrantes]
             + [(ll["geom"], lanelet.name(), ll["id"], "SOBRANTE",
                 "lanelet con geometria repetida; peor candidato")
                for ll in ll_sobrantes]
             + [(ll["geom"], lanelet.name(), ll["id"], "CONSERVAR",
                 "mejor candidato del grupo duplicado")
                for ll in ll_conservados])
    if filas:
        cap, fl = nueva("duplicados_sobrantes",
                        [("capa", QMetaType.Type.QString),
                         ("id", QMetaType.Type.QString),
                         ("rol", QMetaType.Type.QString),
                         ("motivo", QMetaType.Type.QString)])
        fs = []
        for g, cp_, ident, rol, mot in filas:
            f = QgsFeature(fl)
            f.setGeometry(to_output_geometry(g))
            f.setAttributes([cp_, str(ident), rol, mot])
            fs.append(f)
        cap.dataProvider().addFeatures(fs)
        cap.updateExtents()
        cats = []
        for val, col in [("SOBRANTE", QColor(220, 0, 0)),
                         ("CONSERVAR", QColor(0, 170, 0))]:
            sy = QgsSymbol.defaultSymbol(cap.geometryType())
            sy.setColor(col)
            sy.setWidth(1.2)
            cats.append(QgsRendererCategory(val, sy, val))
        cap.setRenderer(QgsCategorizedSymbolRenderer("rol", cats))
        al_grupo(cap)

    # ---- obs_solapes ----
    if solapes:
        cap, fl = nueva("obs_solapes",
                        [("capa_a", QMetaType.Type.QString),
                         ("id_a", QMetaType.Type.QString),
                         ("capa_b", QMetaType.Type.QString),
                         ("id_b", QMetaType.Type.QString),
                         ("largo_m", QMetaType.Type.Double)])
        ff = []
        for a, b, inter, li in solapes:
            f = QgsFeature(fl)
            f.setGeometry(to_output_geometry(inter))
            f.setAttributes([a["capa"], str(a["id"]), b["capa"], str(b["id"]),
                             round(li, 3)])
            ff.append(f)
        cap.dataProvider().addFeatures(ff)
        cap.updateExtents()
        sy = QgsSymbol.defaultSymbol(cap.geometryType())
        sy.setColor(QColor(255, 140, 0))
        sy.setWidth(1.2)
        cap.renderer().setSymbol(sy)
        al_grupo(cap)

    log("  capas escritas en el grupo '%s'. No se borro ni modifico nada."
        % ANEXO_GRUPO)


if ANEXO_QC:
    _ax_run()
