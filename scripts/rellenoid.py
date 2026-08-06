# -*- coding: utf-8 -*-
"""rellenoID — rellena los IDs nulos de una capa o de TODO un grupo.

Regla por capa:
  - Si la capa YA tiene IDs numéricos: los vacíos continúan desde el último
    ID detectado (max + incremento).
  - Si la capa NO tiene ningún ID (todas las filas nulas): arranca desde el
    valor 'inicio' que la tabla CSV (template/idslayers.csv) asigna al nombre
    base de la capa (CURBSTONE, ROAD_EDGE, TURNING_LINE, ...).

Parámetros inyectados por la UI: capa (opcional), GRUPO (opcional, nombre del
grupo), ID_FIELD, INCREMENT, CSV_PATH.
"""
import os
import re

from qgis.core import QgsProject, QgsVectorLayer

if "ID_FIELD" not in globals() or not ID_FIELD:
    ID_FIELD = "id"
if "INCREMENT" not in globals() or not INCREMENT:
    INCREMENT = 1
if "capa" not in globals():
    capa = None
if "GRUPO" not in globals():
    GRUPO = None
if "CSV_PATH" not in globals() or not CSV_PATH:
    CSV_PATH = os.path.join(os.path.dirname(__file__), "..", "template", "idslayers.csv")


# ----------------------- tabla de IDs iniciales ----------------------------
def cargar_tabla(ruta):
    tabla = {}
    if not os.path.isfile(ruta):
        print(f"AVISO: no se encontró la tabla de IDs: {ruta}")
        return tabla
    with open(ruta, encoding="utf-8-sig") as fh:
        for i, linea in enumerate(fh):
            linea = linea.strip()
            if not linea or i == 0 and "inicio" in linea.lower():
                continue
            partes = re.split(r"[;,\t]", linea)
            if len(partes) < 2:
                continue
            nombre = partes[0].strip().upper()
            try:
                tabla[nombre] = int(partes[1].strip())
            except ValueError:
                pass
    return tabla


TABLA = cargar_tabla(CSV_PATH)


def nombre_base(nombre):
    """CURBSTONE_1784818719 -> CURBSTONE ; STOP_LINE_og_.. -> STOP_LINE_OG"""
    return re.sub(r"_\d+$", "", nombre).upper()


def inicio_de(nombre):
    """Busca el ID inicial en la tabla: exacto o por prefijo del nombre base."""
    base = nombre_base(nombre)
    if base in TABLA:
        return TABLA[base]
    for clave, val in TABLA.items():
        if base == clave or base.startswith(clave + "_") or base.startswith(clave):
            return val
    return None


# --------------------------- capas objetivo --------------------------------
capas = []
if GRUPO:
    g = QgsProject.instance().layerTreeRoot().findGroup(GRUPO)
    if g is None:
        raise ValueError(f"No existe el grupo '{GRUPO}' en el panel.")
    capas = [tl.layer() for tl in g.findLayers()
             if isinstance(tl.layer(), QgsVectorLayer)]
    if not capas:
        raise ValueError(f"El grupo '{GRUPO}' no tiene capas vectoriales.")
elif capa is not None:
    capas = [capa]
else:
    raise ValueError("Elige una capa o el nombre de un grupo.")


# ------------------------------ proceso ------------------------------------
def procesar(lyr):
    idx = lyr.fields().indexOf(ID_FIELD)
    if idx < 0:
        print(f"[{lyr.name()}] sin campo '{ID_FIELD}' — se omite.")
        return
    max_id, vacios, con_valor = None, [], 0
    for f in lyr.getFeatures():
        v = f[ID_FIELD]
        if v is None or (isinstance(v, str) and not v.strip()):
            vacios.append(f.id())
            continue
        con_valor += 1
        try:
            n = int(v)
            max_id = n if max_id is None else max(max_id, n)
        except (TypeError, ValueError):
            pass

    if not vacios:
        print(f"[{lyr.name()}] {con_valor} con ID, 0 vacíos — nada que rellenar.")
        return

    # decidir el punto de partida
    if max_id is not None:
        start = max_id + INCREMENT
        origen = f"continúa desde max {max_id}"
    else:
        ini = inicio_de(lyr.name())
        if ini is None:
            print(f"[{lyr.name()}] TODAS las filas nulas y sin entrada en la tabla "
                  f"para '{nombre_base(lyr.name())}' — se OMITE.")
            return
        start = ini
        origen = f"desde tabla ({nombre_base(lyr.name())}={ini})"

    if not lyr.startEditing():
        print(f"[{lyr.name()}] no se pudo poner en edición — se omite.")
        return
    nid = start
    for fid in vacios:
        lyr.changeAttributeValue(fid, idx, nid)
        nid += INCREMENT
    if not lyr.commitChanges():
        lyr.rollBack()
        print(f"[{lyr.name()}] ERROR al guardar — sin cambios.")
        return
    print(f"[{lyr.name()}] {len(vacios)} IDs rellenados {origen}: "
          f"{start}..{nid - INCREMENT}")


print(f"Tabla de IDs: {len(TABLA)} entradas | campo: {ID_FIELD} | incremento: {INCREMENT}")
print("=" * 60)
for lyr in capas:
    procesar(lyr)
print("Proceso terminado.")
