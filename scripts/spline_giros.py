# -*- coding: utf-8 -*-
"""spline_giros — genera lineas de giro en VIRTUAL_LINE con atajos de teclado.

Flujo:
  F8        modo ENTRADA  -> arrastra un rectangulo sobre los 2 extremos
  F9        modo SALIDA   -> otro rectangulo
  F10       genera las dos splines (izquierda->izquierda, derecha->derecha)
  Esc       cancela y limpia
  Backspace borra la ultima captura sin salir de la herramienta

Geometria: BIARCO. Un solo arco circular solo empalma con tangencia exacta en
los dos extremos cuando |I-P0| == |I-P1| (caso isosceles), lo que con vertices
tomados a mano casi nunca ocurre. El biarco son dos arcos circulares con
tangente comun en el punto de union: mantiene continuidad G1 en ambos extremos
y en la juntura, y sigue siendo geometria circular.

La tangente de cada extremo se toma de la propia linea a la que pertenece el
vertice, no del poligono, para que el giro empalme sin quiebre.
"""
import math

from qgis.core import (
    Qgis, QgsCoordinateReferenceSystem, QgsCoordinateTransform, QgsFeature,
    QgsGeometry, QgsMessageLog, QgsPointXY, QgsProject, QgsVectorLayer,
    QgsWkbTypes, NULL,
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


DESTINO_N = _p("CAPA_DESTINO", "VIRTUAL_LINE")
FUENTES = _p("CAPAS_FUENTE", "LANE_MARKER,VIRTUAL_LINE")
ESPACIADO = float(_p("ESPACIADO", 0.89))
PASO_ID = int(_p("PASO_ID", 2))
RADIO_MIN = float(_p("RADIO_MIN", 0.0))
TOL_NODO = float(_p("TOL_NODO", 0.10))
TECLA_ENT = str(_p("TECLA_ENTRADA", "F8"))
TECLA_SAL = str(_p("TECLA_SALIDA", "F9"))
TECLA_GEN = str(_p("TECLA_GENERAR", "F10"))
COMMIT = bool(_p("COMMIT", True))
DESACTIVAR = bool(_p("DESACTIVAR", False))
# --- giro recto: TURNING_LINE + LANELET, ademas del biarco en VIRTUAL_LINE
CREAR_GIRO = bool(_p("CREAR_GIRO", False))
TURNING_N = str(_p("CAPA_TURNING", "TURNING_LINE"))
LANELET_N = str(_p("CAPA_LANELET", "LANELET"))
UMBRAL_RECTO = float(_p("UMBRAL_RECTO", 20.0))   # grados; por debajo -> straight
LL_PARTICIPANT = str(_p("LL_PARTICIPANT", "all-vehicles"))
LL_SURFACE = str(_p("LL_SURFACE", "asphalt"))
LL_ONE_WAY = str(_p("LL_ONE_WAY", "yes"))
LL_SUBTYPE = str(_p("LL_SUBTYPE", "road"))
LL_FUNCTION = str(_p("LL_FUNCTION", "turn"))
LL_SPEED = str(_p("LL_SPEED", "10mph"))
GIRO_CREATOR = str(_p("GIRO_CREATOR", "BO_46"))

if isinstance(FUENTES, str):
    FUENTES = [x.strip() for x in FUENTES.split(",") if x.strip()]

prj = QgsProject.instance()
canvas = IFACE.mapCanvas()


def log(m):
    print(m)
    try:
        QgsMessageLog.logMessage(str(m), "Mi Plugin", level=Qgis.MessageLevel.Info)
    except Exception:
        pass


def barra(m, nivel=Qgis.MessageLevel.Info, seg=4):
    IFACE.messageBar().pushMessage("Spline giros", m, level=nivel, duration=seg)


def capa(n):
    c = prj.mapLayersByName(n)
    return c[0] if c else None


# ------------------------------- geometria ----------------------------------
def utm_auto(cp):
    e = cp.extent()
    c = QgsPointXY((e.xMinimum() + e.xMaximum()) / 2.0,
                   (e.yMinimum() + e.yMaximum()) / 2.0)
    if not cp.crs().isGeographic():
        c = QgsCoordinateTransform(
            cp.crs(), QgsCoordinateReferenceSystem("EPSG:4326"), prj).transform(c)
    z = int(math.floor((c.x() + 180.0) / 6.0) + 1)
    return (32600 if c.y() >= 0 else 32700) + z


def unit(vx, vy):
    n = math.hypot(vx, vy)
    return (0.0, 0.0) if n == 0 else (vx / n, vy / n)


def arco(p0, t0, p1, esp):
    """Muestrea un arco circular desde p0 con tangente t0 hasta p1.

    Devuelve (puntos, radio). Si la curvatura es despreciable, recta.
    """
    cx, cy = p1[0] - p0[0], p1[1] - p0[1]
    nx, ny = -t0[1], t0[0]              # normal a la tangente
    den = 2.0 * (cx * nx + cy * ny)
    if abs(den) < 1e-9:
        return [p0, p1], float("inf")
    r = (cx * cx + cy * cy) / den       # con signo: lado del centro
    centro = (p0[0] + r * nx, p0[1] + r * ny)
    a0 = math.atan2(p0[1] - centro[1], p0[0] - centro[0])
    a1 = math.atan2(p1[1] - centro[1], p1[0] - centro[0])
    horario = r < 0
    d = a1 - a0
    if horario:
        while d > 0:
            d -= 2 * math.pi
        while d < -2 * math.pi:
            d += 2 * math.pi
    else:
        while d < 0:
            d += 2 * math.pi
        while d > 2 * math.pi:
            d -= 2 * math.pi
    rad = abs(r)
    largo = rad * abs(d)
    n = max(2, int(math.ceil(largo / max(esp, 0.05))) + 1)
    pts = []
    for i in range(n):
        a = a0 + d * i / (n - 1.0)
        pts.append((centro[0] + rad * math.cos(a), centro[1] + rad * math.sin(a)))
    return pts, rad


def biarco(p0, t0, p1, t1, esp):
    """Dos arcos circulares con tangente comun. Devuelve (puntos, radio_min)."""
    vx, vy = p1[0] - p0[0], p1[1] - p0[1]
    a = 2.0 * (1.0 - (t0[0] * t1[0] + t0[1] * t1[1]))
    b = 2.0 * (vx * (t0[0] + t1[0]) + vy * (t0[1] + t1[1]))
    c = -(vx * vx + vy * vy)
    if abs(a) < 1e-9:
        if abs(b) < 1e-12:
            return [p0, p1], float("inf")
        d = -c / b
    else:
        disc = b * b - 4 * a * c
        if disc < 0:
            return [p0, p1], float("inf")
        r1 = (-b + math.sqrt(disc)) / (2 * a)
        r2 = (-b - math.sqrt(disc)) / (2 * a)
        cand = [x for x in (r1, r2) if x > 1e-6]
        if not cand:
            return [p0, p1], float("inf")
        d = min(cand)
    pm = ((p0[0] + d * t0[0] + p1[0] - d * t1[0]) / 2.0,
          (p0[1] + d * t0[1] + p1[1] - d * t1[1]) / 2.0)
    a1_pts, ra = arco(p0, t0, pm, esp)
    # el segundo arco se calcula al reves para imponer la tangente de salida
    a2_pts, rb = arco(p1, (-t1[0], -t1[1]), pm, esp)
    a2_pts = list(reversed(a2_pts))
    pts = a1_pts + a2_pts[1:]
    return pts, min(ra, rb)


def extremos_en(poligono_wkt_pts, work, layers):
    """Extremos de lineas cuyo vertice cae dentro del poligono dibujado.

    Devuelve [(punto_metrico, tangente_saliente, capa, id)].
    """
    poli = QgsGeometry.fromPolygonXY([[QgsPointXY(x, y) for x, y in poligono_wkt_pts]])
    salida = []
    for lyr in layers:
        if lyr is None:
            continue
        tr = None
        if lyr.crs().authid() != work.authid():
            tr = QgsCoordinateTransform(lyr.crs(), work, prj)
        for f in lyr.getFeatures():
            g = f.geometry()
            if g is None or g.isEmpty():
                continue
            gg = QgsGeometry(g)
            if tr is not None:
                gg.transform(tr)
            partes = (gg.asMultiPolyline() if gg.isMultipart()
                      else [gg.asPolyline()])
            for pts in partes:
                if not pts or len(pts) < 2:
                    continue
                for idx, vecino in ((0, 1), (len(pts) - 1, len(pts) - 2)):
                    pt = pts[idx]
                    if not poli.contains(QgsGeometry.fromPointXY(pt)):
                        continue
                    vx = pt.x() - pts[vecino].x()
                    vy = pt.y() - pts[vecino].y()
                    salida.append(((pt.x(), pt.y()), unit(vx, vy),
                                   lyr.name(), f["id"] if "id" in
                                   [x.name() for x in lyr.fields()] else f.id()))
    return salida


def agrupar(crudos, tol):
    """Colapsa extremos coincidentes en nodos.

    Donde termina una linea y empieza la siguiente hay 2 o mas vertices en la
    misma posicion; para el giro son un solo punto. Cada nodo conserva todas
    las tangentes salientes de las lineas que concurren en el.
    """
    nodos = []
    for pt, tg, capa_n, ident in crudos:
        destino = None
        for n in nodos:
            if math.dist(pt, n["pt"]) <= tol:
                destino = n
                break
        if destino is None:
            nodos.append({"pt": pt, "tangentes": [tg],
                          "fuentes": [(capa_n, ident)], "n": 1})
        else:
            k = destino["n"]
            destino["pt"] = ((destino["pt"][0] * k + pt[0]) / (k + 1.0),
                             (destino["pt"][1] * k + pt[1]) / (k + 1.0))
            destino["n"] = k + 1
            destino["tangentes"].append(tg)
            destino["fuentes"].append((capa_n, ident))
    return nodos


def dos_extremos(nodos):
    """Si sobran nodos, deja los dos mas separados: los bordes del carril."""
    if len(nodos) <= 2:
        return nodos, ""
    mejor, dmax = None, -1.0
    for i in range(len(nodos)):
        for j in range(i + 1, len(nodos)):
            d = math.dist(nodos[i]["pt"], nodos[j]["pt"])
            if d > dmax:
                dmax, mejor = d, (nodos[i], nodos[j])
    return list(mejor), (" (de %d nodos se tomaron los 2 mas separados, %.2f m)"
                         % (len(nodos), dmax))


def tangente_hacia(nodo, dx, dy, alejandose):
    """Elige, entre las tangentes del nodo, la coherente con el sentido del giro.

    En un nodo donde una linea termina y otra empieza, las tangentes salientes
    apuntan en sentidos opuestos. Se resuelve con la direccion entrada->salida.
    """
    mejor, mejor_v = None, None
    for t in nodo["tangentes"]:
        v = t[0] * dx + t[1] * dy
        if mejor is None or (v > mejor_v if alejandose else v < mejor_v):
            mejor, mejor_v = t, v
    return mejor


def capa_acumulada(dst):
    """Capa temporal donde se acumulan las lineas cuando no se guarda en disco.

    Se reutiliza entre generaciones para que los ids sigan siendo correlativos
    y no se pierda lo dibujado antes.
    """
    nombre = "%s_nuevas" % dst.name()
    existente = capa(nombre)
    if existente is not None:
        return existente, False
    tmp = QgsVectorLayer("LineString?crs=%s" % dst.crs().authid(), nombre, "memory")
    tmp.dataProvider().addAttributes(list(dst.fields()))
    tmp.updateFields()
    sim = tmp.renderer().symbol()
    sim.setColor(QColor(0, 200, 255))
    sim.setWidth(1.0)
    prj.addMapLayer(tmp)
    return tmp, True


# ------------------------------ herramienta ---------------------------------
class HerramientaGiro(QgsMapTool):
    def __init__(self, canvas_):
        super().__init__(canvas_)
        self.modo = "entrada"
        self.vertices_poly = []
        self.ini = None
        self.arrastrando = False
        self.entrada = []
        self.salida = []
        self.banda = QgsRubberBand(canvas_, QgsWkbTypes.PolygonGeometry)
        self.banda.setColor(QColor(255, 120, 0, 70))
        self.banda.setStrokeColor(QColor(255, 120, 0))
        self.banda.setWidth(2)
        self.prev = QgsRubberBand(canvas_, QgsWkbTypes.LineGeometry)
        self.prev.setColor(QColor(0, 200, 255))
        self.prev.setWidth(3)
        self.work = QgsCoordinateReferenceSystem(
            "EPSG:%d" % utm_auto(capa(DESTINO_N)))
        self.tr_in = QgsCoordinateTransform(
            canvas_.mapSettings().destinationCrs(), self.work, prj)
        self.tr_out = QgsCoordinateTransform(
            self.work, canvas_.mapSettings().destinationCrs(), prj)

    # ---- captura por rectangulo arrastrado
    def _rect_geom(self, a, b):
        return QgsGeometry.fromPolygonXY([[
            QgsPointXY(a.x(), a.y()), QgsPointXY(b.x(), a.y()),
            QgsPointXY(b.x(), b.y()), QgsPointXY(a.x(), b.y()),
            QgsPointXY(a.x(), a.y())]])

    def canvasPressEvent(self, e):
        if e.button() != Qt.MouseButton.LeftButton:
            return
        self.ini = self.toMapCoordinates(e.pos())
        self.arrastrando = True
        self.banda.reset(QgsWkbTypes.PolygonGeometry)

    def canvasMoveEvent(self, e):
        if not getattr(self, "arrastrando", False) or self.ini is None:
            return
        act = self.toMapCoordinates(e.pos())
        self.banda.setToGeometry(self._rect_geom(self.ini, act), None)

    def canvasReleaseEvent(self, e):
        if e.button() != Qt.MouseButton.LeftButton:
            return
        if not getattr(self, "arrastrando", False) or self.ini is None:
            return
        self.arrastrando = False
        fin = self.toMapCoordinates(e.pos())
        anchura = abs(fin.x() - self.ini.x())
        altura = abs(fin.y() - self.ini.y())
        if anchura <= 0 or altura <= 0:
            self.banda.reset(QgsWkbTypes.PolygonGeometry)
            barra("Arrastra para formar un rectangulo, no un solo clic.",
                  Qgis.MessageLevel.Warning)
            self.ini = None
            return
        self.vertices_poly = [
            QgsPointXY(self.ini.x(), self.ini.y()),
            QgsPointXY(fin.x(), self.ini.y()),
            QgsPointXY(fin.x(), fin.y()),
            QgsPointXY(self.ini.x(), fin.y())]
        self.ini = None
        self.cerrar_poligono()

    def cerrar_poligono(self):
        if len(self.vertices_poly) < 3:
            return
        pm = [self.tr_in.transform(p) for p in self.vertices_poly]
        capas = [capa(n) for n in FUENTES]
        hallados = extremos_en([(p.x(), p.y()) for p in pm], self.work, capas)
        nodos = agrupar(hallados, TOL_NODO)
        nodos, nota = dos_extremos(nodos)
        if self.modo == "entrada":
            self.entrada = nodos
        else:
            self.salida = nodos
        self.vertices_poly = []
        self.banda.reset(QgsWkbTypes.PolygonGeometry)
        log("  %s: %d vertices -> %d nodos%s"
            % (self.modo.upper(), len(hallados), len(nodos), nota))
        for n in nodos:
            log("      nodo con %d lineas: %s" % (n["n"], n["fuentes"][:4]))
        barra("%s: %d nodos%s. %s" % (self.modo.upper(), len(nodos), nota,
              "%s para la salida" % TECLA_SAL if self.modo == "entrada"
              else "%s para generar" % TECLA_GEN))
        self.previsualizar()

    # ---- emparejado y preview
    def emparejar(self):
        if len(self.entrada) != 2 or len(self.salida) != 2:
            return None
        ce = ((self.entrada[0]["pt"][0] + self.entrada[1]["pt"][0]) / 2.0,
              (self.entrada[0]["pt"][1] + self.entrada[1]["pt"][1]) / 2.0)
        cs = ((self.salida[0]["pt"][0] + self.salida[1]["pt"][0]) / 2.0,
              (self.salida[0]["pt"][1] + self.salida[1]["pt"][1]) / 2.0)
        dx, dy = unit(cs[0] - ce[0], cs[1] - ce[1])
        if dx == 0 and dy == 0:
            return None

        ent, sal = {}, {}
        for n in self.entrada:
            cruz = dx * (n["pt"][1] - ce[1]) - dy * (n["pt"][0] - ce[0])
            ent["izq" if cruz > 0 else "der"] = n
        for n in self.salida:
            cruz = dx * (n["pt"][1] - cs[1]) - dy * (n["pt"][0] - cs[0])
            sal["izq" if cruz > 0 else "der"] = n
        if len(ent) != 2 or len(sal) != 2:
            return None

        pares = []
        for lado in ("izq", "der"):
            e, sn = ent[lado], sal[lado]
            t0 = tangente_hacia(e, dx, dy, True)      # entra hacia el giro
            ts = tangente_hacia(sn, dx, dy, False)    # sale continuando la via
            t1 = (-ts[0], -ts[1])
            pts, rad = biarco(e["pt"], t0, sn["pt"], t1, ESPACIADO)
            pares.append((lado, pts, rad, e, sn))
        return pares

    def previsualizar(self):
        self.prev.reset(QgsWkbTypes.LineGeometry)
        pares = self.emparejar()
        if not pares:
            return
        for lado, pts, rad, e, s in pares:
            geo = QgsGeometry.fromPolylineXY([QgsPointXY(x, y) for x, y in pts])
            geo.transform(self.tr_out)
            self.prev.addGeometry(geo, None)
        log("  preview: %s" % ", ".join("%s r=%.1f m %d vertices"
                                        % (l, r, len(p)) for l, p, r, _, _ in pares))

    # ---- teclado
    def keyPressEvent(self, e):
        k = e.key()
        if k == Qt.Key.Key_Escape:
            self.limpiar()
            barra("Captura cancelada.")
        elif k == Qt.Key.Key_Backspace:
            if self.modo == "salida" and self.salida:
                self.salida = []
                self.prev.reset(QgsWkbTypes.LineGeometry)
                barra("Salida borrada.")
            elif self.entrada:
                self.entrada = []
                self.prev.reset(QgsWkbTypes.LineGeometry)
                barra("Entrada borrada.")

    def limpiar(self):
        self.vertices_poly = []
        self.ini = None
        self.arrastrando = False
        self.entrada = []
        self.salida = []
        self.banda.reset(QgsWkbTypes.PolygonGeometry)
        self.prev.reset(QgsWkbTypes.LineGeometry)

    # ---- escritura
    def generar(self):
        pares = self.emparejar()
        if not pares:
            barra("Necesito exactamente 2 extremos de entrada y 2 de salida "
                  "(tengo %d y %d)." % (len(self.entrada), len(self.salida)),
                  Qgis.MessageLevel.Warning, 6)
            return
        dst = capa(DESTINO_N)
        if dst is None:
            barra("No existe la capa '%s'." % DESTINO_N, Qgis.MessageLevel.Critical)
            return
        campos = dst.fields()
        nombres = [f.name() for f in campos]

        # el ultimo id se consulta SIEMPRE sobre la capa real, y ademas sobre la
        # temporal, para que lo acumulado no repita ids
        ids = [int(f["id"]) for f in dst.getFeatures()
               if f["id"] not in (None, NULL) and int(f["id"]) < 10 ** 7]
        escribir = dst
        nueva_tmp = False
        if not COMMIT:
            escribir, nueva_tmp = capa_acumulada(dst)
            ids += [int(f["id"]) for f in escribir.getFeatures()
                    if f["id"] not in (None, NULL) and int(f["id"]) < 10 ** 7]
            campos = escribir.fields()
            nombres = [f.name() for f in campos]
        siguiente = (max(ids) + PASO_ID) if ids else PASO_ID

        tr_dst = QgsCoordinateTransform(self.work, escribir.crs(), prj)
        estaba = escribir.isEditable()
        if COMMIT and not estaba:
            escribir.startEditing()

        nuevos, avisos = [], []
        for lado, pts, rad, e, s in pares:
            if RADIO_MIN > 0 and rad < RADIO_MIN:
                avisos.append("%s r=%.1f m < minimo %.1f m" % (lado, rad, RADIO_MIN))
            geo = QgsGeometry.fromPolylineXY([QgsPointXY(x, y) for x, y in pts])
            geo.transform(tr_dst)
            f = QgsFeature(campos)
            f.setGeometry(geo)
            # en esta capa solo se gestiona el id; el resto queda como venga
            if "id" in nombres:
                f["id"] = siguiente
            nuevos.append((f, siguiente, lado, rad, len(pts)))
            siguiente += PASO_ID

        if COMMIT:
            ok = escribir.addFeatures([n[0] for n in nuevos])
        else:
            ok = escribir.dataProvider().addFeatures([n[0] for n in nuevos])
            escribir.updateExtents()
            escribir.triggerRepaint()
        if not ok:
            if COMMIT:
                escribir.rollBack(False)
            barra("addFeatures fallo.", Qgis.MessageLevel.Critical)
            return
        if COMMIT:
            if not escribir.commitChanges(False):
                for err in escribir.commitErrors()[:4]:
                    log("  ERROR: %s" % err)
                escribir.rollBack(False)
                barra("Commit fallido, se revirtio.", Qgis.MessageLevel.Critical, 6)
                return
        else:
            log("  (no se guarda en disco: acumulando en '%s'%s; total %d)"
                % (escribir.name(), " recien creada" if nueva_tmp else "",
                   escribir.featureCount()))
        log("GENERADAS %d lineas en '%s':" % (len(nuevos), escribir.name()))
        for f, i, lado, rad, nv in nuevos:
            log("   id=%d  %-3s  radio_min=%.2f m  %d vertices" % (i, lado, rad, nv))
        for a in avisos:
            log("   AVISO radio: %s" % a)
        barra("Creadas %d lineas (id %d y %d)%s"
              % (len(nuevos), nuevos[0][1], nuevos[-1][1],
                 "  |  " + "; ".join(avisos) if avisos else ""),
              Qgis.MessageLevel.Success, 6)
        if CREAR_GIRO:
            self.generar_giro_recto(pares)

        self.limpiar()
        canvas.refreshAllLayers()

    # ---- giro recto: dos TURNING_LINE + su LANELET
    @staticmethod
    def _giro_de(pts):
        """turn_direction a partir del biarco: signo del giro y angulo total."""
        if len(pts) < 3:
            return "straight", 0.0
        v0 = (pts[1][0] - pts[0][0], pts[1][1] - pts[0][1])
        v1 = (pts[-1][0] - pts[-2][0], pts[-1][1] - pts[-2][1])
        cruz = v0[0] * v1[1] - v0[1] * v1[0]
        punto = v0[0] * v1[0] + v0[1] * v1[1]
        ang = math.degrees(math.atan2(cruz, punto))
        if abs(ang) <= UMBRAL_RECTO:
            return "straight", ang
        return ("left" if ang > 0 else "right"), ang

    def _siguiente_id(self, cp, extra=0):
        ids = [int(f["id"]) for f in cp.getFeatures()
               if f["id"] not in (None, NULL) and int(f["id"]) < 10 ** 7]
        return ((max(ids) + PASO_ID) if ids else PASO_ID) + extra * PASO_ID

    def _escribir_en(self, cp, feats):
        """Escribe respetando COMMIT; devuelve la capa realmente usada."""
        if not COMMIT:
            tmp, _ = capa_acumulada(cp)
            ok = tmp.dataProvider().addFeatures(feats)
            tmp.updateExtents()
            tmp.triggerRepaint()
            return (tmp if ok else None)
        estaba = cp.isEditable()
        if not estaba:
            cp.startEditing()
        if not cp.addFeatures(feats):
            cp.rollBack(False)
            return None
        if not cp.commitChanges(False):
            for err in cp.commitErrors()[:4]:
                log("  ERROR %s: %s" % (cp.name(), err))
            cp.rollBack(False)
            return None
        return cp

    def generar_giro_recto(self, pares):
        tl, ln = capa(TURNING_N), capa(LANELET_N)
        if tl is None or ln is None:
            barra("No estan cargadas '%s' y/o '%s'." % (TURNING_N, LANELET_N),
                  Qgis.MessageLevel.Warning, 6)
            return
        lados = {l: (pts, e, sn) for l, pts, _r, e, sn in pares}
        if "izq" not in lados or "der" not in lados:
            return

        giro, ang = self._giro_de(lados["izq"][0])

        def recta(a, b, cp):
            """Segmento de 2 vertices con Z=0: las capas son LineStringZ y una
            geometria 2D seria rechazada por el proveedor."""
            g = QgsGeometry.fromPolylineXY([QgsPointXY(*a), QgsPointXY(*b)])
            g.get().addZValue(0.0)
            g.transform(QgsCoordinateTransform(self.work, cp.crs(), prj))
            return g

        # --- las dos TURNING_LINE, en el sentido de circulacion
        campos_t = tl.fields()
        nom_t = [f.name() for f in campos_t]
        ids_t = {}
        feats_t = []
        for k, lado in enumerate(("izq", "der")):
            _pts, e, sn = lados[lado]
            ident = self._siguiente_id(tl, k)
            ids_t[lado] = ident
            f = QgsFeature(campos_t)
            f.setGeometry(recta(e["pt"], sn["pt"], tl))
            for nombre, valor in (("id", ident), ("turn_direction", giro),
                                  ("creator", GIRO_CREATOR)):
                if nombre in nom_t:
                    f[nombre] = valor
            feats_t.append(f)
        cap_t = self._escribir_en(tl, feats_t)
        if cap_t is None:
            barra("No se pudieron escribir las TURNING_LINE.",
                  Qgis.MessageLevel.Critical, 6)
            return

        # --- el LANELET: eje recto entre los puntos medios de entrada y salida
        _p_i, e_i, s_i = lados["izq"]
        _p_d, e_d, s_d = lados["der"]
        med_e = ((e_i["pt"][0] + e_d["pt"][0]) / 2.0,
                 (e_i["pt"][1] + e_d["pt"][1]) / 2.0)
        med_s = ((s_i["pt"][0] + s_d["pt"][0]) / 2.0,
                 (s_i["pt"][1] + s_d["pt"][1]) / 2.0)
        campos_l = ln.fields()
        nom_l = [f.name() for f in campos_l]
        id_ll = self._siguiente_id(ln)
        f = QgsFeature(campos_l)
        f.setGeometry(recta(med_e, med_s, ln))
        for nombre, valor in (("id", id_ll),
                              ("left_line_id", ids_t["izq"]),
                              ("right_line_id", ids_t["der"]),
                              ("left_line_type", "turning"),
                              ("right_line_type", "turning"),
                              ("participant", LL_PARTICIPANT),
                              ("surface", LL_SURFACE),
                              ("one_way", LL_ONE_WAY),
                              ("subtype", LL_SUBTYPE),
                              ("function", LL_FUNCTION),
                              ("speed_limit", LL_SPEED),
                              ("turn_direction", giro),
                              ("creator", GIRO_CREATOR)):
            if nombre in nom_l:
                f[nombre] = valor
        cap_l = self._escribir_en(ln, [f])
        if cap_l is None:
            barra("Se escribieron las TURNING_LINE pero fallo el LANELET.",
                  Qgis.MessageLevel.Critical, 8)
            return

        log("GIRO RECTO en '%s' / '%s':" % (cap_t.name(), cap_l.name()))
        log("   TURNING_LINE  left id=%d  |  right id=%d"
            % (ids_t["izq"], ids_t["der"]))
        log("   LANELET       id=%d  left_line_id=%d  right_line_id=%d"
            % (id_ll, ids_t["izq"], ids_t["der"]))
        log("   turn_direction=%s  (angulo %.1f grados, umbral recto %.1f)"
            % (giro, ang, UMBRAL_RECTO))
        if giro == "straight":
            log("   AVISO: angulo por debajo del umbral; revisa si el giro "
                "realmente es recto.")
        barra("Giro recto: TURNING_LINE %d/%d + LANELET %d  (%s, %.0f grados)"
              % (ids_t["izq"], ids_t["der"], id_ll, giro, ang),
              Qgis.MessageLevel.Success, 7)

    @staticmethod
    def sentido(pts):
        """Signo del giro acumulado: right / left."""
        if len(pts) < 3:
            return ""
        acum = 0.0
        for i in range(1, len(pts) - 1):
            ax, ay = pts[i][0] - pts[i - 1][0], pts[i][1] - pts[i - 1][1]
            bx, by = pts[i + 1][0] - pts[i][0], pts[i + 1][1] - pts[i][1]
            acum += ax * by - ay * bx
        return "left" if acum > 0 else "right"


# ------------------------------ activacion ----------------------------------
def _quitar_atajos():
    for a in ("_sg_f7", "_sg_f8", "_sg_f9"):
        s = getattr(_qu, a, None)
        if s is not None:
            try:
                s.setEnabled(False)
                s.deleteLater()
            except Exception:
                pass
            delattr(_qu, a)


if DESACTIVAR:
    _quitar_atajos()
    h = getattr(_qu, "_sg_tool", None)
    if h is not None:
        h.limpiar()
        from qgis.gui import QgsMapToolPan
        canvas.setMapTool(QgsMapToolPan(canvas))
        delattr(_qu, "_sg_tool")
    log("Herramienta de splines DESACTIVADA.")
else:
    if capa(DESTINO_N) is None:
        raise RuntimeError("No esta cargada la capa destino '%s'." % DESTINO_N)
    _quitar_atajos()
    herr = HerramientaGiro(canvas)
    _qu._sg_tool = herr

    def _modo(m):
        herr.modo = m
        if canvas.mapTool() is not herr:
            canvas.setMapTool(herr)
        canvas.setFocus()
        barra("Modo %s: arrastra un rectangulo sobre los 2 extremos." % m.upper())

    mw = IFACE.mainWindow()
    ocupadas = {}
    try:
        from qgis.gui import QgsGui
        for a in QgsGui.shortcutsManager().listActions():
            t = a.shortcut().toString()
            if t:
                ocupadas[t] = a.text().replace("&", "")
    except Exception:
        pass
    for tecla, uso in ((TECLA_ENT, "entrada"), (TECLA_SAL, "salida"),
                       (TECLA_GEN, "generar")):
        if tecla in ocupadas:
            log("  AVISO: %s ya esta asignada en QGIS a '%s'; puede haber "
                "conflicto." % (tecla, ocupadas[tecla]))

    s7 = QShortcut(QKeySequence(TECLA_ENT), mw)
    s7.activated.connect(lambda: _modo("entrada"))
    s8 = QShortcut(QKeySequence(TECLA_SAL), mw)
    s8.activated.connect(lambda: _modo("salida"))
    s9 = QShortcut(QKeySequence(TECLA_GEN), mw)
    s9.activated.connect(lambda: herr.generar())
    _qu._sg_f7, _qu._sg_f8, _qu._sg_f9 = s7, s8, s9

    canvas.setMapTool(herr)
    canvas.setFocus()
    log("Herramienta de splines ACTIVA")
    log("  destino  : %s" % DESTINO_N)
    log("  fuentes  : %s" % ", ".join(FUENTES))
    log("  espaciado: %.2f m  |  paso de id: %d" % (ESPACIADO, PASO_ID))
    log("  %s entrada | %s salida | %s generar | Esc cancelar | Backspace deshacer"
        % (TECLA_ENT, TECLA_SAL, TECLA_GEN))
    log("  (arrastra con el boton izquierdo para encuadrar los 2 extremos)")
    barra("%s para capturar la ENTRADA." % TECLA_ENT, Qgis.MessageLevel.Info, 8)
