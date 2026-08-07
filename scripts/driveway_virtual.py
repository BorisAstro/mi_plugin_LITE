# -*- coding: utf-8 -*-
"""driveway_virtual — crea las VIRTUAL_LINE de un driveway y sus LANELET.

Flujo (3 clics con el boton izquierdo):
  1er clic   inicio del BORDE DERECHO del carril de entrada
  2do clic   fin de ese borde  -> define el sentido de circulacion de entrada
  3er clic   borde opuesto del driveway -> define el ancho total
  Enter/F11  escribe        Esc cancela        Backspace deshace el ultimo clic

Regla confirmada contra los datos del proyecto (2265 lanelets con ambos lados
virtuales): cada VIRTUAL_LINE se digitaliza en el sentido de marcha del lanelet
para el que es la linea DERECHA (99.5% de los casos). La linea central de un
driveway de doble carril es la IZQUIERDA de los dos lanelets, asi que no hay
regla que la determine; por convenio sigue al carril de entrada.

Ancho total > UMBRAL  -> 3 virtual lines + 2 lanelets (one_way=yes)
Ancho total <= UMBRAL -> 2 virtual lines + 1 lanelet  (one_way=no)
"""
import math

from qgis.core import (
    Qgis, QgsCoordinateReferenceSystem, QgsCoordinateTransform, QgsFeature,
    QgsGeometry, QgsMessageLog, QgsPointXY, QgsProject, QgsWkbTypes, NULL,
)
from qgis.gui import QgsMapTool, QgsRubberBand
from qgis.PyQt.QtCore import Qt
from qgis.PyQt.QtGui import QColor, QKeySequence
from qgis.PyQt.QtWidgets import QShortcut
import qgis.utils as _qu

P = globals().get("PLUGIN_PARAMS", {}) or {}
IFACE = globals().get("iface", None) or _qu.iface


def _p(k, d=None):
    v = P.get(k, globals().get(k, d))
    return d if v is None or v == "" else v


VL_N = str(_p("CAPA_VIRTUAL", "VIRTUAL_LINE"))
LL_N = str(_p("CAPA_LANELET", "LANELET"))
UMBRAL = float(_p("UMBRAL_ANCHO", 6.0))       # metros, ancho total
AVISO_MIN = float(_p("AVISO_DESDE", 6.0))     # franja ambigua: aviso en el log
AVISO_MAX = float(_p("AVISO_HASTA", 7.0))
PASO_ID = int(_p("PASO_ID", 2))
REFERENCIA = str(_p("REFERENCIA", "borde derecho"))
CENTRAL = str(_p("SENTIDO_CENTRAL", "entrada"))
TECLA_GEN = str(_p("TECLA_GENERAR", "Shift+F11"))
TECLA_UNA = str(_p("TECLA_UNA_VIA", "Shift+F12"))
COMMIT = bool(_p("COMMIT", True))
DESACTIVAR = bool(_p("DESACTIVAR", False))
DW_PARTICIPANT = str(_p("DW_PARTICIPANT", "all-vehicles"))
DW_SURFACE = str(_p("DW_SURFACE", "asphalt"))
DW_SUBTYPE = str(_p("DW_SUBTYPE", "road"))
DW_SPEED = str(_p("DW_SPEED", "15mph"))
DW_TURN = str(_p("DW_TURN", "straight"))
DW_FUNCTION = _p("DW_FUNCTION", "")           # vacio = NULL, como en tus driveways
DW_CREATOR = str(_p("DW_CREATOR", "BO_46"))

prj = QgsProject.instance()
canvas = IFACE.mapCanvas()


def log(m):
    print(m)
    try:
        QgsMessageLog.logMessage(str(m), "Mi Plugin", level=Qgis.MessageLevel.Info)
    except Exception:
        pass


def barra(m, nivel=Qgis.MessageLevel.Info, seg=5):
    IFACE.messageBar().pushMessage("Driveway", m, level=nivel, duration=seg)


def capa(n):
    c = prj.mapLayersByName(n)
    return c[0] if c else None


def utm_auto(cp):
    e = cp.extent()
    c = QgsPointXY((e.xMinimum() + e.xMaximum()) / 2.0,
                   (e.yMinimum() + e.yMaximum()) / 2.0)
    if not cp.crs().isGeographic():
        c = QgsCoordinateTransform(
            cp.crs(), QgsCoordinateReferenceSystem("EPSG:4326"), prj).transform(c)
    zona = int(math.floor((c.x() + 180.0) / 6.0) + 1)
    return (32600 if c.y() >= 0 else 32700) + zona


def unit(vx, vy):
    n = math.hypot(vx, vy)
    return (0.0, 0.0) if n == 0 else (vx / n, vy / n)


class HerramientaDriveway(QgsMapTool):
    def __init__(self, canvas_):
        super().__init__(canvas_)
        self.clics = []
        self.work = QgsCoordinateReferenceSystem("EPSG:%d" % utm_auto(capa(VL_N)))
        self.tr_in = QgsCoordinateTransform(
            canvas_.mapSettings().destinationCrs(), self.work, prj)
        self.tr_out = QgsCoordinateTransform(
            self.work, canvas_.mapSettings().destinationCrs(), prj)
        self.b_vl = QgsRubberBand(canvas_, QgsWkbTypes.LineGeometry)
        self.b_vl.setColor(QColor(0, 200, 255))
        self.b_vl.setWidth(3)
        self.b_ll = QgsRubberBand(canvas_, QgsWkbTypes.LineGeometry)
        self.b_ll.setColor(QColor(255, 200, 0))
        self.b_ll.setWidth(2)
        self.b_ll.setLineStyle(Qt.PenStyle.DashLine)

    # ------------------------------------------------ interaccion
    def canvasReleaseEvent(self, e):
        if e.button() != Qt.MouseButton.LeftButton:
            return
        p = self.toMapCoordinates(e.pos())
        self.clics.append(self.tr_in.transform(p))
        if len(self.clics) > 3:
            self.clics = self.clics[-1:]
        n = len(self.clics)
        barra({1: "Ahora el FIN del borde derecho (sentido de entrada).",
               2: "Ahora el borde opuesto del driveway.",
               3: "Listo: %s o Enter escribe el driveway completo; %s o "
                  "Shift+Enter solo la entrada." % (TECLA_GEN, TECLA_UNA)}[n])
        self.previsualizar()

    def keyPressEvent(self, e):
        k = e.key()
        if k == Qt.Key.Key_Escape:
            self.limpiar()
            barra("Cancelado.")
        elif k == Qt.Key.Key_Backspace and self.clics:
            self.clics.pop()
            self.previsualizar()
            barra("Ultimo clic descartado (quedan %d)." % len(self.clics))
        elif k in (Qt.Key.Key_Return, Qt.Key.Key_Enter):
            self.generar(bool(e.modifiers() & Qt.KeyboardModifier.ShiftModifier))

    def limpiar(self):
        self.clics = []
        self.b_vl.reset(QgsWkbTypes.LineGeometry)
        self.b_ll.reset(QgsWkbTypes.LineGeometry)

    # ------------------------------------------------ geometria
    def resolver(self, solo_entrada=False):
        """Devuelve (lineas_vl, lanelets, ancho, invertido) en CRS de trabajo.

        lineas_vl: [(clave, [(x,y),(x,y)])] en el sentido que toca digitalizar
        lanelets : [(clave, pts, id_izq, id_der, one_way)]
        """
        if len(self.clics) < 3:
            return None
        p0, p1, p2 = self.clics[0], self.clics[1], self.clics[2]
        ux, uy = unit(p1.x() - p0.x(), p1.y() - p0.y())
        if ux == 0 and uy == 0:
            return None
        largo = math.hypot(p1.x() - p0.x(), p1.y() - p0.y())
        nx, ny = -uy, ux                      # normal izquierda del sentido de entrada
        s = (p2.x() - p0.x()) * nx + (p2.y() - p0.y()) * ny
        invertido = s < 0
        if invertido:
            # el borde opuesto cayo a la derecha: el borde se dibujo al reves
            ux, uy = -ux, -uy
            nx, ny = -nx, -ny
            p0 = QgsPointXY(p1.x(), p1.y())
            s = -s
        ancho = abs(s)
        if REFERENCIA.lower().startswith("eje"):
            # el primer trazo era el eje del driveway: el ancho es el doble y
            # el borde derecho queda medio ancho a la derecha del eje
            ancho = 2.0 * ancho
            p0 = QgsPointXY(p0.x() - nx * ancho / 2.0, p0.y() - ny * ancho / 2.0)

        def linea(desp, hacia_adelante):
            ax = p0.x() + nx * desp
            ay = p0.y() + ny * desp
            bx, by = ax + ux * largo, ay + uy * largo
            return [(ax, ay), (bx, by)] if hacia_adelante else [(bx, by), (ax, ay)]

        if solo_entrada:
            # entrada independiente: todo el ancho es un unico carril de ida.
            # La salida se digitaliza aparte, en otro sitio.
            vls = [("derecha_entrada", linea(0.0, True)),
                   ("izquierda", linea(ancho, True))]
            lls = [("solo entrada", linea(ancho / 2.0, True), "izquierda",
                    "derecha_entrada", "yes")]
            return vls, lls, ancho, invertido
        if ancho > UMBRAL:
            central_adelante = (CENTRAL.lower() != "salida")
            vls = [("derecha_entrada", linea(0.0, True)),
                   ("central", linea(ancho / 2.0, central_adelante)),
                   ("derecha_salida", linea(ancho, False))]
            lls = [("entra", linea(ancho / 4.0, True), "central",
                    "derecha_entrada", "yes"),
                   ("sale", linea(3.0 * ancho / 4.0, False), "central",
                    "derecha_salida", "yes")]
        else:
            vls = [("derecha_entrada", linea(0.0, True)),
                   ("izquierda", linea(ancho, True))]
            lls = [("doble sentido", linea(ancho / 2.0, True), "izquierda",
                    "derecha_entrada", "no")]
        return vls, lls, ancho, invertido

    def previsualizar(self, solo_entrada=False):
        self.b_vl.reset(QgsWkbTypes.LineGeometry)
        self.b_ll.reset(QgsWkbTypes.LineGeometry)
        r = self.resolver(solo_entrada)
        if not r:
            if len(self.clics) == 2:
                g = QgsGeometry.fromPolylineXY(
                    [QgsPointXY(self.clics[0]), QgsPointXY(self.clics[1])])
                g.transform(self.tr_out)
                self.b_vl.addGeometry(g, None)
            return
        vls, lls, ancho, inv = r
        for banda, grupo in ((self.b_vl, vls), (self.b_ll, [(a, b) for a, b, _c, _d, _e in lls])):
            for _clave, pts in grupo:
                for g in self._con_flecha(pts):
                    g.transform(self.tr_out)
                    banda.addGeometry(g, None)
        log("  preview: ancho %.2f m -> %d virtual lines, %d lanelets%s"
            % (ancho, len(vls), len(lls), "  (sentido invertido)" if inv else ""))

    @staticmethod
    def _con_flecha(pts):
        """La linea mas una punta de flecha al final, para ver el sentido."""
        (ax, ay), (bx, by) = pts[0], pts[-1]
        salida = [QgsGeometry.fromPolylineXY([QgsPointXY(ax, ay), QgsPointXY(bx, by)])]
        ux, uy = unit(bx - ax, by - ay)
        d = 0.7
        for signo in (1, -1):
            cx = bx - ux * d + (-uy) * d * 0.5 * signo
            cy = by - uy * d + (ux) * d * 0.5 * signo
            salida.append(QgsGeometry.fromPolylineXY(
                [QgsPointXY(cx, cy), QgsPointXY(bx, by)]))
        return salida

    # ------------------------------------------------ escritura
    def _siguiente(self, cp, extra=0):
        ids = [int(f["id"]) for f in cp.getFeatures()
               if f["id"] not in (None, NULL) and int(f["id"]) < 10 ** 7]
        return ((max(ids) + PASO_ID) if ids else PASO_ID) + extra * PASO_ID

    def _recta(self, pts, cp):
        g = QgsGeometry.fromPolylineXY([QgsPointXY(x, y) for x, y in pts])
        g.get().addZValue(0.0)
        g.transform(QgsCoordinateTransform(self.work, cp.crs(), prj))
        return g

    @staticmethod
    def _guardar(cp, feats):
        estaba = cp.isEditable()
        if not estaba:
            cp.startEditing()
        if not cp.addFeatures(feats):
            cp.rollBack(False)
            return False
        if COMMIT:
            if not cp.commitChanges(False):
                for err in cp.commitErrors()[:4]:
                    log("  ERROR %s: %s" % (cp.name(), err))
                cp.rollBack(False)
                return False
        return True

    def generar(self, solo_entrada=False):
        # la vista previa se rehace con el modo elegido antes de escribir, para
        # que lo dibujado en pantalla sea exactamente lo que se guarda
        if solo_entrada:
            self.previsualizar(True)
        r = self.resolver(solo_entrada)
        if not r:
            barra("Faltan clics: llevo %d de 3." % len(self.clics),
                  Qgis.MessageLevel.Warning)
            return
        vls, lls, ancho, invertido = r
        cvl, cll = capa(VL_N), capa(LL_N)
        if cvl is None or cll is None:
            barra("No estan cargadas '%s' y/o '%s'." % (VL_N, LL_N),
                  Qgis.MessageLevel.Critical)
            return

        campos_v = cvl.fields()
        nom_v = [f.name() for f in campos_v]
        ids_vl, feats_v = {}, []
        for k, (clave, pts) in enumerate(vls):
            ident = self._siguiente(cvl, k)
            ids_vl[clave] = ident
            f = QgsFeature(campos_v)
            f.setGeometry(self._recta(pts, cvl))
            if "id" in nom_v:
                f["id"] = ident
            if "creator" in nom_v:
                f["creator"] = DW_CREATOR
            feats_v.append(f)
        if not self._guardar(cvl, feats_v):
            barra("No se pudieron escribir las VIRTUAL_LINE.",
                  Qgis.MessageLevel.Critical, 7)
            return

        campos_l = cll.fields()
        nom_l = [f.name() for f in campos_l]
        feats_l, ids_ll = [], []
        for k, (clave, pts, c_izq, c_der, one_way) in enumerate(lls):
            ident = self._siguiente(cll, k)
            ids_ll.append((clave, ident, one_way))
            f = QgsFeature(campos_l)
            f.setGeometry(self._recta(pts, cll))
            valores = {"id": ident,
                       "left_line_id": ids_vl[c_izq],
                       "right_line_id": ids_vl[c_der],
                       "left_line_type": "virtual",
                       "right_line_type": "virtual",
                       "participant": DW_PARTICIPANT,
                       "surface": DW_SURFACE,
                       "one_way": one_way,
                       "subtype": DW_SUBTYPE,
                       "speed_limit": DW_SPEED,
                       "turn_direction": DW_TURN,
                       "function": (DW_FUNCTION or None),
                       "creator": DW_CREATOR}
            for nombre, valor in valores.items():
                if nombre in nom_l:
                    f[nombre] = valor
            feats_l.append(f)
        if not self._guardar(cll, feats_l):
            barra("Se escribieron las VIRTUAL_LINE pero fallo el LANELET.",
                  Qgis.MessageLevel.Critical, 9)
            return

        log("DRIVEWAY%s  ancho total %.2f m  (umbral %.1f m)"
            % ("  [SOLO ENTRADA]" if solo_entrada else "", ancho, UMBRAL))
        if invertido:
            log("   se invirtio el sentido: el borde opuesto quedaba a la derecha")
        for clave, ident in ids_vl.items():
            log("   VIRTUAL_LINE  %-16s id=%d" % (clave, ident))
        for clave, ident, ow in ids_ll:
            log("   LANELET       %-16s id=%d  one_way=%s" % (clave, ident, ow))
        if solo_entrada:
            log("   entrada independiente: la salida se digitaliza por separado")
        elif AVISO_MIN < ancho <= AVISO_MAX:
            log("   AVISO: %.2f m cae en la franja donde tus datos mezclan los dos "
                "patrones (%.1f a %.1f m). Revisa el resultado."
                % (ancho, AVISO_MIN, AVISO_MAX))
        barra("Driveway: %d virtual lines + %d lanelets  (ancho %.2f m)"
              % (len(vls), len(lls), ancho), Qgis.MessageLevel.Success, 7)
        self.limpiar()
        canvas.refreshAllLayers()


# ------------------------------ activacion ----------------------------------
def _quitar():
    for a in ("_dw_gen", "_dw_una"):
        s = getattr(_qu, a, None)
        if s is not None:
            try:
                s.setEnabled(False)
                s.deleteLater()
            except Exception:
                pass
            delattr(_qu, a)


def _ocupadas():
    """Atajos que QGIS ya tiene asignados, para avisar de choques."""
    d = {}
    try:
        from qgis.gui import QgsGui
        for a in QgsGui.shortcutsManager().listActions():
            t = a.shortcut().toString()
            if t:
                d.setdefault(t, a.text().replace("&", ""))
        for a in QgsGui.shortcutsManager().listShortcuts():
            t = a.key().toString()
            if t:
                d.setdefault(t, a.objectName() or "(atajo)")
    except Exception:
        pass
    return d


if DESACTIVAR:
    _quitar()
    h = getattr(_qu, "_dw_tool", None)
    if h is not None:
        h.limpiar()
        from qgis.gui import QgsMapToolPan
        canvas.setMapTool(QgsMapToolPan(canvas))
        delattr(_qu, "_dw_tool")
    log("Herramienta de driveways DESACTIVADA.")
else:
    for n in (VL_N, LL_N):
        if capa(n) is None:
            raise RuntimeError("No esta cargada la capa '%s'." % n)
    _quitar()
    herr = HerramientaDriveway(canvas)
    _qu._dw_tool = herr
    ocupadas = _ocupadas()
    for tecla, uso in ((TECLA_GEN, "escribir"), (TECLA_UNA, "solo entrada")):
        if tecla in ocupadas:
            log("  AVISO: %s ya esta asignada en QGIS a '%s'; no funcionara "
                "para %s. Elige otra en el dialogo."
                % (tecla, ocupadas[tecla], uso))
    s = QShortcut(QKeySequence(TECLA_GEN), IFACE.mainWindow())
    s.activated.connect(lambda: herr.generar(False))
    _qu._dw_gen = s
    s2 = QShortcut(QKeySequence(TECLA_UNA), IFACE.mainWindow())
    s2.activated.connect(lambda: herr.generar(True))
    _qu._dw_una = s2
    canvas.setMapTool(herr)
    canvas.setFocus()
    log("Herramienta de driveways ACTIVA")
    log("  virtual line: %s   |   lanelet: %s" % (VL_N, LL_N))
    log("  umbral de ancho: %.2f m   |   paso de id: %d" % (UMBRAL, PASO_ID))
    log("  referencia: %s   |   sentido de la central: %s" % (REFERENCIA, CENTRAL))
    log("  1er clic inicio del borde DERECHO de entrada")
    log("  2do clic fin de ese borde (marca el sentido de circulacion)")
    log("  3er clic borde opuesto del driveway (marca el ancho)")
    log("  %s o Enter        escribe el driveway completo" % TECLA_GEN)
    log("  %s o Shift+Enter  escribe SOLO la entrada (un carril, one_way=yes)"
        % TECLA_UNA)
    log("  Esc cancela | Backspace deshace el ultimo clic")
    barra("Driveway activo: 1) inicio del borde derecho de entrada.")
