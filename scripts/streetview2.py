# -*- coding: utf-8 -*-
"""Activa una herramienta de clic en el lienzo: abre Google Street View en el
navegador en la posición del clic. Vuelve a la herramienta normal con Pan."""
import webbrowser
from qgis.gui import QgsMapToolEmitPoint
from qgis.core import QgsProject, QgsCoordinateReferenceSystem, QgsCoordinateTransform

canvas = iface.mapCanvas()
_tool = QgsMapToolEmitPoint(canvas)

def _clic(punto, _boton):
    tr = QgsCoordinateTransform(QgsProject.instance().crs(),
                                QgsCoordinateReferenceSystem("EPSG:4326"),
                                QgsProject.instance())
    p = tr.transform(punto)
    webbrowser.open(f"https://www.google.com/maps?q=&layer=c&cbll={p.y()},{p.x()}")

_tool.canvasClicked.connect(_clic)
canvas.setMapTool(_tool)
canvas._streetview_tool = _tool  # evitar que lo recoja el GC
print("Street View activo: haz clic en el lienzo. (Cambia a Pan para desactivar.)")
