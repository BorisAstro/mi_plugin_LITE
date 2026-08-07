# -*- coding: utf-8 -*-
"""Crea una capa 2D a partir de una capa 3D, para etiquetar bien.

Acepta cualquier geometria de entrada: punto, linea o poligono, con o sin Z.
Los poligonos y lineas (traffic_light_box, traffic_sign_box, crosswalk...) se
reducen a un punto representativo, que es lo que hace falta para etiquetar.

Punto interior  usa pointOnSurface(): el punto queda SIEMPRE dentro de la
                geometria, incluso en poligonos en L o con agujeros.
Centroide       es el centro de masa; en formas concavas puede caer fuera.
"""
from qgis.core import QgsProject, QgsVectorLayer, QgsFeature, QgsGeometry, QgsWkbTypes

P = globals().get("PLUGIN_PARAMS", {}) or {}


def _p(k, d=None):
    v = P.get(k, globals().get(k, d))
    return d if v is None or v == "" else v


if "capa" not in globals() or capa is None:
    capa = iface.activeLayer()
if capa is None:
    raise ValueError("Selecciona una capa (o activa una en el panel).")
if "nombre_salida" not in globals() or not nombre_salida:
    nombre_salida = capa.name() + "_2D"

SALIDA = str(_p("SALIDA", "punto"))
METODO = str(_p("METODO", "punto interior"))
ESTILO_DE = str(_p("ESTILO_DE", "") or "").strip()
ESTILO_QML = str(_p("ESTILO_QML", "") or "").strip()
FILTRO = str(_p("FILTRO", "") or "").strip()
ETIQUETA = str(_p("ETIQUETA", "") or "").strip()
COPIAR_FILTRO = bool(_p("COPIAR_FILTRO", True))
# El estilo y el filtro son especificos de un tipo de capa: un filtro por
# "type" IN ('R2-1','R1-1') no significa nada en TRAFFIC_LIGHT_BOX o CROSSWALK.
# Con esto la conversion de otras capas sale limpia aunque el dialogo conserve
# la capa de referencia de la vez anterior.
SOLO_SI_ORIGEN = str(_p("SOLO_SI_ORIGEN", "TRAFFIC_SIGN_BOX") or "").strip()

tipo_geom = capa.geometryType()
nombre_tipo = {QgsWkbTypes.GeometryType.PointGeometry: "Point",
               QgsWkbTypes.GeometryType.LineGeometry: "LineString",
               QgsWkbTypes.GeometryType.PolygonGeometry: "Polygon"}
if tipo_geom not in nombre_tipo:
    raise ValueError("La capa '%s' no tiene geometria vectorial." % capa.name())

a_punto = SALIDA.lower().startswith("punto")
txt = "Point" if a_punto else nombre_tipo[tipo_geom]
if not a_punto and capa.wkbType() != QgsWkbTypes.singleType(capa.wkbType()):
    txt = "Multi" + txt

out = QgsVectorLayer("%s?crs=%s" % (txt, capa.crs().authid()), nombre_salida, "memory")
out.dataProvider().addAttributes(list(capa.fields()))
out.updateFields()

feats, saltadas = [], 0
for f in capa.getFeatures():
    g = f.geometry()
    if g is None or g.isEmpty():
        saltadas += 1
        continue
    g2 = QgsGeometry(g)
    if a_punto and tipo_geom != QgsWkbTypes.GeometryType.PointGeometry:
        g2 = (g2.pointOnSurface() if METODO.lower().startswith("punto")
              else g2.centroid())
        if g2 is None or g2.isEmpty():
            saltadas += 1
            continue
    elif a_punto and g2.isMultipart():
        # multipunto -> un solo punto, para no duplicar etiquetas
        g2 = g2.centroid()
    abs_ = g2.get()
    if abs_ is not None and abs_.is3D():
        abs_.dropZValue()
    nf = QgsFeature(out.fields())
    nf.setGeometry(g2)
    nf.setAttributes(f.attributes())
    feats.append(nf)

ok, _ = out.dataProvider().addFeatures(feats)
out.updateExtents()


def _aplicar_estilo(destino):
    """Copia simbologia y etiquetado de una capa de referencia o de un .qml.

    El QML no guarda el filtro de capa, asi que el subsetString se copia
    aparte. Solo tiene sentido entre capas de la misma geometria: un estilo de
    poligono aplicado a puntos deja la capa sin simbolo visible.
    """
    import os
    import re
    import tempfile
    hechos = []
    if SOLO_SI_ORIGEN:
        patrones = [x.strip().upper() for x in SOLO_SI_ORIGEN.split(",") if x.strip()]
        # se compara contra el nombre sin el sufijo numerico de exportacion
        base = re.sub(r"(_\d{6,})+$", "", capa.name()).upper()
        if not any(p in base for p in patrones):
            print("   estilo y filtro omitidos: '%s' no coincide con %s"
                  % (capa.name(), " / ".join(patrones)))
            return hechos
    ref = None
    if ESTILO_DE:
        c = QgsProject.instance().mapLayersByName(ESTILO_DE)
        ref = c[0] if c else None
        if ref is None:
            print("   AVISO: no se encontro la capa de estilo '%s'." % ESTILO_DE)
        elif ref.geometryType() != destino.geometryType():
            print("   AVISO: '%s' es de otra geometria; el estilo se ignora."
                  % ESTILO_DE)
            ref = None
    if ref is not None:
        qml = os.path.join(tempfile.gettempdir(), "_estilo_ref.qml")
        ref.saveNamedStyle(qml)
        destino.loadNamedStyle(qml)
        hechos.append("simbologia y etiquetas de '%s'" % ref.name())
        if COPIAR_FILTRO and ref.subsetString():
            destino.setSubsetString(ref.subsetString())
            hechos.append("filtro %s" % ref.subsetString())
    elif ESTILO_QML:
        if os.path.exists(ESTILO_QML):
            destino.loadNamedStyle(ESTILO_QML)
            hechos.append("estilo %s" % os.path.basename(ESTILO_QML))
        else:
            print("   AVISO: no existe el QML '%s'." % ESTILO_QML)

    if FILTRO:
        destino.setSubsetString(FILTRO)
        hechos.append("filtro %s" % FILTRO)
    if ETIQUETA:
        from qgis.core import (QgsPalLayerSettings, QgsTextFormat,
                               QgsTextBufferSettings, QgsVectorLayerSimpleLabeling,
                               QgsUnitTypes)
        from qgis.PyQt.QtGui import QColor, QFont
        base = (destino.labeling().settings() if destino.labeling()
                else QgsPalLayerSettings())
        base.fieldName = ETIQUETA
        base.isExpression = True
        if not destino.labeling():
            fmt = QgsTextFormat()
            fnt = QFont("Arial")
            fnt.setBold(True)
            fmt.setFont(fnt)
            fmt.setSize(9)
            fmt.setSizeUnit(QgsUnitTypes.RenderUnit.RenderPoints)
            fmt.setColor(QColor(255, 255, 255))
            buf = QgsTextBufferSettings()
            buf.setEnabled(True)
            buf.setSize(1.0)
            buf.setSizeUnit(QgsUnitTypes.RenderUnit.RenderMillimeters)
            buf.setColor(QColor(0, 0, 0))
            fmt.setBuffer(buf)
            base.setFormat(fmt)
            base.placement = QgsPalLayerSettings.Placement.OverPoint
            base.quadOffset = QgsPalLayerSettings.QuadrantPosition.QuadrantAboveRight
            base.dist = 1.5
            base.distUnits = QgsUnitTypes.RenderUnit.RenderMillimeters
        destino.setLabeling(QgsVectorLayerSimpleLabeling(base))
        destino.setLabelsEnabled(True)
        hechos.append("etiqueta %s" % ETIQUETA)
    return hechos


aplicados = _aplicar_estilo(out)
QgsProject.instance().addMapLayer(out)
out.triggerRepaint()
print("%s: %d entidades 2D creadas desde %s (%s -> %s)."
      % (nombre_salida, out.featureCount(), capa.name(),
         QgsWkbTypes.displayString(capa.wkbType()),
         QgsWkbTypes.displayString(out.wkbType())))
if a_punto and tipo_geom != QgsWkbTypes.GeometryType.PointGeometry:
    print("   metodo: %s" % METODO)
for h in aplicados:
    print("   aplicado: %s" % h)
if aplicados and out.subsetString():
    print("   visibles tras el filtro: %d de %d"
          % (out.featureCount(), len(feats)))
if saltadas:
    print("   %d entidades saltadas por geometria vacia o no reducible." % saltadas)
if not ok:
    print("   AVISO: addFeatures devolvio False; revisa el tipo de geometria.")
