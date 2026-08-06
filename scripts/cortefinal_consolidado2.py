import geopandas as gpd
from shapely.geometry import LineString, MultiLineString, Point
from shapely.geometry.base import BaseGeometry
from shapely.ops import split, linemerge
from shapely.strtree import STRtree
import numpy as np
import math
import os
from pathlib import Path

# =================================
# CONFIGURACIÓN
# =================================
# Inyectados por la UI del plugin
if "BASE" not in globals():
    BASE = r"C:\Users\boris\Downloads\complemento\complemento"
BASE = Path(BASE)

VIRTUAL_FILE   = BASE / "VIRTUAL_LINE.geojson"
LANE_FILE      = BASE / "LANE_MARKER.geojson"
CURBSTONE_FILE = BASE / "CURBSTONE.geojson"
CUT_FILE       = BASE / "CUT_LINE.geojson"

if "UTM_EPSG" not in globals():
    UTM_EPSG = 32612
if "SNAP_TOL" not in globals():
    SNAP_TOL = 0.005
if "SMALL_LEN" not in globals():
    SMALL_LEN = 0.05
if "EXTEND_LEN" not in globals():
    EXTEND_LEN = 0.01
if "MERGE_TOL" not in globals():
    MERGE_TOL = 0.05

# =================================
# CARGA
# =================================
virtual   = gpd.read_file(str(VIRTUAL_FILE))
lane      = gpd.read_file(str(LANE_FILE))
curbstone = gpd.read_file(str(CURBSTONE_FILE))
cuts      = gpd.read_file(str(CUT_FILE))

virtual_crs   = virtual.crs
lane_crs      = lane.crs
curbstone_crs = curbstone.crs

virtual_utm   = virtual.to_crs(epsg=UTM_EPSG)
lane_utm      = lane.to_crs(epsg=UTM_EPSG)
curbstone_utm = curbstone.to_crs(epsg=UTM_EPSG)
cuts_utm      = cuts.to_crs(epsg=UTM_EPSG)

# =================================
# LONGITUD
# =================================
def add_length_field(gdf, utm_epsg=UTM_EPSG, field_name="length_m"):
    if gdf.empty:
        gdf[field_name] = []
        return gdf

    gdf_utm = gdf.to_crs(epsg=utm_epsg)
    gdf[field_name] = gdf_utm.geometry.length.values
    return gdf

# =================================
# EXTENDER CUT
# =================================
def extend_line(line, distance):
    if line is None or line.is_empty:
        return line
    coords = list(line.coords)
    if len(coords) < 2:
        return line

    coords_2d = [(float(c[0]), float(c[1])) for c in coords]

    x1, y1 = coords_2d[0]
    x2, y2 = coords_2d[1]
    dx, dy = x1 - x2, y1 - y2
    length = math.hypot(dx, dy)
    new_start = (x1 + dx * distance / length, y1 + dy * distance / length) if length else (x1, y1)

    x3, y3 = coords_2d[-2]
    x4, y4 = coords_2d[-1]
    dx, dy = x4 - x3, y4 - y3
    length = math.hypot(dx, dy)
    new_end = (x4 + dx * distance / length, y4 + dy * distance / length) if length else (x4, y4)

    return LineString([new_start] + coords_2d[1:-1] + [new_end])

cut_geoms = []
for g in cuts_utm.geometry:
    if g is None or g.is_empty:
        continue
    if g.geom_type == "LineString":
        cut_geoms.append(extend_line(g, EXTEND_LEN))
    elif g.geom_type == "MultiLineString":
        for part in g.geoms:
            cut_geoms.append(extend_line(part, EXTEND_LEN))

cut_index = STRtree(cut_geoms)

def resolve_geom(item, geom_list):
    if isinstance(item, (int, np.integer)):
        return geom_list[int(item)]
    return item

# =================================
# UTILIDADES
# =================================
def explode_to_lines(geom):
    if not isinstance(geom, BaseGeometry):
        return []
    if geom.is_empty:
        return []
    if geom.geom_type == "LineString":
        return [geom]
    if geom.geom_type == "MultiLineString":
        return list(geom.geoms)
    return []

def snap_line(line):
    if not isinstance(line, BaseGeometry) or line.is_empty:
        return None
    coords = [(float(c[0]), float(c[1])) for c in line.coords]
    for i in (0, -1):
        p = Point(coords[i])
        for item in cut_index.query(p.buffer(SNAP_TOL)):
            cut = resolve_geom(item, cut_geoms)
            if not isinstance(cut, BaseGeometry) or cut.is_empty:
                continue
            proj = cut.interpolate(cut.project(p))
            if p.distance(proj) <= SNAP_TOL:
                coords[i] = (proj.x, proj.y)
                break
    return LineString(coords) if len(coords) >= 2 else None

def split_line(line):
    parts = [line]
    for item in cut_index.query(line):
        cut = resolve_geom(item, cut_geoms)
        if cut is None or cut.is_empty:
            continue
        new_parts = []
        for g in parts:
            if not g.intersects(cut):
                new_parts.append(g)
                continue
            try:
                new_parts.extend(split(g, cut).geoms)
            except Exception:
                new_parts.append(g)
        parts = new_parts
    return parts

def endpoint_dist(l1, l2):
    pts1 = [l1.coords[0], l1.coords[-1]]
    pts2 = [l2.coords[0], l2.coords[-1]]
    return min(math.hypot(a[0]-b[0], a[1]-b[1]) for a in pts1 for b in pts2)

# =================================
# MERGE
# =================================
def merge_segments_smart(segments, merge_tol=MERGE_TOL):
    segments = [g for g in segments if g is not None and not g.is_empty]
    if not segments:
        return []

    changed = True
    while changed:
        changed = False
        big   = [g for g in segments if g.length >= SMALL_LEN]
        small = [g for g in segments if g.length < SMALL_LEN]

        if not small or not big:
            break

        big_index = STRtree(big)
        new_big = list(big)

        for s in small:
            candidates = big_index.query(s.buffer(merge_tol))

            best_dist = float("inf")
            best_idx  = None

            for item in candidates:
                idx = int(item) if isinstance(item, (int, np.integer)) else None
                if idx is None:
                    continue
                d = endpoint_dist(s, big[idx])
                if d < best_dist:
                    best_dist = d
                    best_idx  = idx

            if best_idx is not None and best_dist <= merge_tol:
                new_big[best_idx] = linemerge([new_big[best_idx], s])
                changed = True

        segments = [g for g in new_big if g is not None and not g.is_empty]

    return segments

def merge_segments_by_attr(records_by_key):
    result = {}
    for key, geoms in records_by_key.items():
        result[key] = merge_segments_smart(geoms)
    return result

# =================================
# PROCESOS
# =================================
def process_simple(gdf):
    # 🛡️ Eliminar filas con geometría nula o inválida
    gdf = gdf[gdf.geometry.apply(lambda g: isinstance(g, BaseGeometry) and not g.is_empty)].copy()

    records = []
    attr_cols = [c for c in gdf.columns if c != "geometry"]

    for _, r in gdf.iterrows():
        for line in explode_to_lines(r.geometry):
            snapped = snap_line(line)
            if snapped is None:
                continue

            parts = split_line(snapped)

            for part in parts:
                new_r = r.copy()
                new_r.geometry = part
                records.append(new_r)

    if not records:
        return gpd.GeoDataFrame(columns=gdf.columns, crs=UTM_EPSG)

    grouped = {}
    for r in records:
        key = tuple((k, r[k]) for k in attr_cols)
        grouped.setdefault(key, []).append(r.geometry)

    merged_groups = merge_segments_by_attr(grouped)

    rows = []
    for key, geoms in merged_groups.items():
        attr_dict = dict(key)
        for geom in geoms:
            row = {k: v for k, v in attr_dict.items()}
            row["geometry"] = geom
            rows.append(row)

    result = gpd.GeoDataFrame(rows, crs=UTM_EPSG)
    return result[gdf.columns]

def process_lane(gdf):
    # 🛡️ Eliminar filas con geometría nula o inválida
    gdf = gdf[gdf.geometry.apply(lambda g: isinstance(g, BaseGeometry) and not g.is_empty)].copy()

    records = []
    attr_cols = [c for c in gdf.columns if c != "geometry"]

    for _, r in gdf.iterrows():
        for line in explode_to_lines(r.geometry):
            snapped = snap_line(line)
            if snapped is None:
                continue
            parts = split_line(snapped)
            for part in parts:
                new_r = r.copy()
                new_r.geometry = part
                records.append(new_r)

    if not records:
        return gpd.GeoDataFrame(columns=gdf.columns, crs=UTM_EPSG)

    grouped = {}
    for r in records:
        key = tuple((k, r[k]) for k in attr_cols)
        grouped.setdefault(key, []).append(r.geometry)

    merged_groups = merge_segments_by_attr(grouped)

    rows = []
    for key, geoms in merged_groups.items():
        attr_dict = dict(key)
        for geom in geoms:
            row = {k: v for k, v in attr_dict.items()}
            row["geometry"] = geom
            rows.append(row)

    result = gpd.GeoDataFrame(rows, crs=UTM_EPSG)
    cols = attr_cols + ["geometry"]
    return result[[c for c in cols if c in result.columns]]

# =================================
# EJECUCIÓN
# =================================
print("✔ Procesando VIRTUAL_LINE …")
virtual_out = process_simple(virtual_utm).to_crs(virtual_crs)
virtual_out = add_length_field(virtual_out)

print("✔ Procesando LANE_MARKER …")
lane_out = process_lane(lane_utm).to_crs(lane_crs)
lane_out = add_length_field(lane_out)

print("✔ Procesando CURBSTONE …")
curbstone_out = process_simple(curbstone_utm).to_crs(curbstone_crs)
curbstone_out = add_length_field(curbstone_out)

# =================================
# GUARDADO
# =================================
# Convención de nombres (igual que fix_geojson): el resultado CONSERVA el
# nombre base y el archivo original se copia a <base>_corte.geojson.
import shutil as _shutil
import tempfile as _tempfile


def _rotar_original(ruta, proceso="corte"):
    """Copia el original a <base>_<proceso>.geojson antes de sobrescribirlo.

    Se copia en vez de renombrar porque en Windows QGIS bloquea el rename de
    los archivos que tiene cargados."""
    ruta = Path(ruta)
    destino = ruta.with_name(f"{ruta.stem}_{proceso}{ruta.suffix}")
    if destino.exists():
        raise RuntimeError(
            f"Ya existe {destino.name}; muévelo o bórralo antes de repetir.")
    _shutil.copy2(str(ruta), str(destino))
    return destino


def _recargar(ruta):
    """Refresca en QGIS las capas que apuntan a ese archivo."""
    try:
        from qgis.core import QgsProject
    except ImportError:
        return
    objetivo = os.path.normcase(os.path.normpath(str(ruta)))
    for lyr in QgsProject.instance().mapLayers().values():
        try:
            fuente = lyr.source().split("|")[0]
        except AttributeError:
            continue
        if os.path.normcase(os.path.normpath(fuente)) == objetivo:
            lyr.dataProvider().forceReload()
            # updateFields() es imprescindible: forceReload refresca los datos
            # pero NO el esquema, asi que los campos nuevos o con tipo cambiado
            # no aparecen en la tabla de atributos hasta recargar la capa.
            lyr.updateFields()
            lyr.triggerRepaint()


def guardar_conservando_nombre(gdf, ruta):
    """Escribe gdf en 'ruta' tras poner a salvo el original.

    Escribe primero a un temporal y vuelca los bytes sobre el archivo destino:
    así no se pierde el original si el guardado falla a medias, y funciona
    aunque QGIS tenga la capa abierta."""
    ruta = Path(ruta)
    original = _rotar_original(ruta) if ruta.exists() else None

    tmp = Path(_tempfile.mkdtemp(prefix="cortefinal_")) / ruta.name
    try:
        gdf.to_file(str(tmp), driver="GeoJSON")
        with open(tmp, "rb") as fh_in, open(ruta, "wb") as fh_out:
            _shutil.copyfileobj(fh_in, fh_out)
    finally:
        _shutil.rmtree(tmp.parent, ignore_errors=True)

    _recargar(ruta)
    marca = f" | original → {original.name}" if original else " (no existía)"
    print(f"✔ {ruta.name}: {len(gdf)} features{marca}")


guardar_conservando_nombre(virtual_out, VIRTUAL_FILE)
guardar_conservando_nombre(lane_out, LANE_FILE)
guardar_conservando_nombre(curbstone_out, CURBSTONE_FILE)

print("✔ PROCESO FINALIZADO CORRECTAMENTE")
