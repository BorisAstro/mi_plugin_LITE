# -*- coding: utf-8 -*-
"""Aplica estilos QML/SLD a las capas por nombre base: quita el sufijo
_<numeros> de la capa, ignora mayusculas/guiones bajos y el prefijo
'estilo'/'estilo_' de los archivos.

Alcance seleccionable: todo el proyecto, un grupo del panel, o solo las capas
que tengas resaltadas en el panel de capas.
"""
import os
import re

from qgis.PyQt.QtWidgets import QFileDialog
from qgis.core import QgsProject, QgsLayerTreeGroup, QgsLayerTreeLayer
import qgis.utils as _qu

P = globals().get("PLUGIN_PARAMS", {}) or {}
IFACE = globals().get("iface", None) or _qu.iface


def _p(clave, defecto=None):
    v = P.get(clave, globals().get(clave, defecto))
    return defecto if v is None or v == "" else v


CARPETA = _p("carpeta_estilos", r"E:\phoenix")
GRUPO = str(_p("GRUPO", "") or "").strip()
SOLO_SEL = bool(_p("SOLO_SELECCIONADAS", False))

if not CARPETA or not os.path.isdir(str(CARPETA)):
    if CARPETA:
        print("La carpeta '%s' no existe; se pedira una." % CARPETA)
    CARPETA = QFileDialog.getExistingDirectory(
        IFACE.mainWindow(), "Carpeta con estilos .qml / .sld")
if not CARPETA:
    raise ValueError("No se eligio carpeta de estilos.")

prj = QgsProject.instance()
raiz = prj.layerTreeRoot()


def _norm(s):
    s = re.sub(r"[^a-z0-9]", "", s.lower())
    return s[6:] if s.startswith("estilo") else s


# ------------------------------ alcance -------------------------------------
if SOLO_SEL:
    nodos = IFACE.layerTreeView().selectedLayerNodes()
    capas = [n.layer() for n in nodos if n.layer() is not None]
    alcance = "capas resaltadas en el panel (%d)" % len(capas)
    if not capas:
        raise ValueError("No hay capas resaltadas en el panel de capas. "
                         "Selecciona alguna o desmarca 'Solo las resaltadas'.")
elif GRUPO:
    nodo = raiz.findGroup(GRUPO)
    if nodo is None:
        disponibles = [g.name() for g in raiz.findGroups()]
        raise ValueError("No existe el grupo '%s'. Grupos en el proyecto: %s"
                         % (GRUPO, ", ".join(disponibles) or "(ninguno)"))
    capas = [n.layer() for n in nodo.findLayers() if n.layer() is not None]
    alcance = "grupo '%s' (%d capas, incluye subgrupos)" % (GRUPO, len(capas))
else:
    capas = list(prj.mapLayers().values())
    alcance = "todo el proyecto (%d capas)" % len(capas)

# ------------------------------ indice de estilos ---------------------------
indice = {}
for f in sorted(os.listdir(CARPETA)):
    stem, ext = os.path.splitext(f)
    if ext.lower() in (".qml", ".sld"):
        clave = _norm(stem)
        if clave not in indice or ext.lower() == ".qml":
            indice[clave] = os.path.join(CARPETA, f)

print("Carpeta de estilos : %s" % CARPETA)
print("Estilos encontrados: %d" % len(indice))
print("Alcance            : %s" % alcance)
print("-" * 66)

aplicados, sin_estilo, errores = 0, [], []
for lyr in capas:
    base = re.sub(r"_\d+$", "", lyr.name())
    ruta = indice.get(_norm(base)) or indice.get(_norm(lyr.name()))
    if not ruta:
        sin_estilo.append(lyr.name())
        continue
    if ruta.lower().endswith(".qml"):
        _msg, ok = lyr.loadNamedStyle(ruta)
    else:
        _msg, ok = lyr.loadSldStyle(ruta)
    if ok:
        lyr.triggerRepaint()
        aplicados += 1
        print("[OK]    %-34s <- %s" % (lyr.name(), os.path.basename(ruta)))
    else:
        errores.append(lyr.name())
        print("[ERROR] %-34s <- %s" % (lyr.name(), os.path.basename(ruta)))

IFACE.layerTreeView().refreshLayerSymbology
try:
    IFACE.mapCanvas().refreshAllLayers()
except Exception:
    pass

print("-" * 66)
print("Aplicados: %d | sin estilo: %d | errores: %d"
      % (aplicados, len(sin_estilo), len(errores)))
if sin_estilo:
    print("Sin estilo: " + ", ".join(sin_estilo[:25])
          + (" ..." if len(sin_estilo) > 25 else ""))
