# -*- coding: utf-8 -*-
"""asociar_stopline_lanelet — enlaza un STOP_LINE con sus LANELET por id.

Relacion 1:n — varios lanelet pueden compartir el mismo stop line. Los ids de
los lanelet elegidos se guardan separados por comas en el campo destino
(por defecto 'lane_id') del stop line.

Flujo con atajos:
  F2   confirma el STOP_LINE seleccionado y PRESELECCIONA los lanelet que lo
       tocan o intersectan dentro de la tolerancia; ajusta la seleccion a mano
  F4   escribe los ids de los lanelet seleccionados en el stop line
  Esc  cancela

Deshacer: la escritura se hace dentro de un comando de edicion sobre la capa
fisica, asi que Ctrl+Z de QGIS la revierte. Con 'Guardar directo' desmarcado
los cambios quedan en la sesion de edicion y los confirmas tu con Ctrl+S.
"""
import math
import re

from qgis.core import (
    Qgis, QgsCategorizedSymbolRenderer, QgsCoordinateReferenceSystem,
    QgsCoordinateTransform, QgsFeatureRequest, QgsField, QgsFields,
    QgsFeature, QgsRendererCategory, QgsSymbol, QgsWkbTypes,
    QgsGeometry, QgsMessageLog, QgsPointXY, QgsProject, QgsVectorLayer, NULL,
)
from qgis.PyQt.QtCore import QMetaType
from qgis.PyQt.QtGui import QColor, QKeySequence
from qgis.PyQt.QtWidgets import QShortcut
from qgis.core import QgsLayerTreeGroup
import qgis.utils as _qu

P = globals().get("PLUGIN_PARAMS", {}) or {}
IFACE = globals().get("iface", None) or _qu.iface


def _p(k, d=None):
    v = P.get(k, globals().get(k, d))
    return d if v is None or v == "" else v


N_STOP = _p("CAPA_STOPLINE", "")
N_LANE = _p("CAPA_LANELET", "LANELET")
CAMPO = str(_p("CAMPO_DESTINO", "lane_id"))
CAMPO_ID = str(_p("CAMPO_ID_LANELET", "id"))
TOL = float(_p("TOLERANCIA", 0.50))
AUTOSEL = bool(_p("AUTOSELECCION", True))
ANEXAR = bool(_p("ANEXAR", False))
ORDENAR = bool(_p("ORDENAR", True))
GUARDAR = bool(_p("GUARDAR_DIRECTO", False))
T_STOP = str(_p("TECLA_STOPLINE", "F2"))
T_ESCR = str(_p("TECLA_ESCRIBIR", "F4"))
DESACTIVAR = bool(_p("DESACTIVAR", False))
PROGRESO = bool(_p("MOSTRAR_PROGRESO", True))
GRUPO_PROG = str(_p("GRUPO_PROGRESO", "ASOCIACION"))
REFRESCAR_TODO = bool(_p("REFRESCAR_TODO", True))
INCLUIR_DESTINO = bool(_p("INCLUIR_DESTINO", True))
MAX_DESTINOS = int(_p("MAX_DESTINOS", 2000))
ESCRIBIR_INVERSO = bool(_p("ESCRIBIR_INVERSO", True))

prj = QgsProject.instance()

# --------------------------- reglas de asociacion ---------------------------
# from -> to, todas 1:n. El campo vive en la capa ORIGEN y guarda la lista de
# ids de la capa DESTINO separados por comas.
# (origen, destino, campo, cardinalidad)
#   "1:n" -> el campo guarda una LISTA de ids separada por comas
#   "n:1" -> el campo guarda UN SOLO id; se exige una unica seleccion
REGLAS = [
    # --- directas: el origen agrupa a varios destinos
    ("STOP_LINE",          "TRAFFIC_LIGHT_POLE", "traffic_light_pole_id", "1:n"),
    ("STOP_LINE",          "LANELET",            "lane_id",               "1:n"),
    ("TRAFFIC_LIGHT_POLE", "TRAFFIC_LIGHT_BOX",  "traffic_light_box_id",  "1:n"),
    ("TRAFFIC_SIGN_POLE",  "TRAFFIC_SIGN_BOX",   "traffic_sign_box_id",   "1:n"),
    ("TRAFFIC_LIGHT_BOX",  "TRAFFIC_LIGHT_BULB", "traffic_light_bulb_id", "1:n"),
    ("TRAFFIC_LIGHT_BOX",  "LANELET",            "lane_id",               "1:n"),
    # --- inversas: el origen apunta a UN solo destino
    ("TRAFFIC_LIGHT_POLE", "STOP_LINE",          "stop_line_id",          "n:1"),
    ("TRAFFIC_LIGHT_BOX",  "STOP_LINE",          "stop_line_id",          "n:1"),
    ("TRAFFIC_SIGN_BOX",   "STOP_LINE",          "stop_line_id",          "n:1"),
    ("TRAFFIC_LIGHT_BOX",  "TRAFFIC_LIGHT_POLE", "traffic_light_pole_id", "n:1"),
    ("TRAFFIC_SIGN_BOX",   "TRAFFIC_SIGN_POLE",  "traffic_sign_pole_id",  "n:1"),
]
TIPOS_ORIGEN = sorted({r[0] for r in REGLAS})
TIPOS_DESTINO = sorted({r[1] for r in REGLAS})


def tipo_de(nombre):
    """LANELET_1785680431 -> LANELET ; ignora sufijos numericos y _MERGED."""
    t = re.sub(r"(_\d{6,})+$", "", str(nombre)).upper()
    return re.sub(r"_MERGED$", "", t)


def regla_de(orig, dest):
    to, td = tipo_de(orig), tipo_de(dest)
    for a, b, campo, card in REGLAS:
        if a == to and b == td:
            return a, b, campo, card
    return None, None, None, None





def log(m):
    print(m)
    try:
        QgsMessageLog.logMessage(str(m), "Mi Plugin", level=Qgis.MessageLevel.Info)
    except Exception:
        pass


def barra(m, n=Qgis.MessageLevel.Info, s=5):
    IFACE.messageBar().pushMessage("Asociar", m, level=n, duration=s)


def capa(n):
    c = prj.mapLayersByName(n)
    return c[0] if c else None


def utm_auto(cp, alterna=None):
    """Zona UTM desde el centroide. Si la capa esta vacia usa la alternativa."""
    for capa_ref in (cp, alterna):
        if capa_ref is None:
            continue
        e = capa_ref.extent()
        if e.isNull() or e.isEmpty():
            continue
        cx = (e.xMinimum() + e.xMaximum()) / 2.0
        cy = (e.yMinimum() + e.yMaximum()) / 2.0
        if cx != cx or cy != cy:          # NaN
            continue
        c = QgsPointXY(cx, cy)
        if not capa_ref.crs().isGeographic():
            c = QgsCoordinateTransform(
                capa_ref.crs(), QgsCoordinateReferenceSystem("EPSG:4326"),
                prj).transform(c)
        z = int(math.floor((c.x() + 180.0) / 6.0) + 1)
        return (32600 if c.y() >= 0 else 32700) + z
    raise RuntimeError(
        "No se puede determinar la zona UTM: las capas '%s' y '%s' no tienen "
        "extension valida (¿estan vacias?)."
        % (cp.name(), alterna.name() if alterna is not None else "-"))


def nid(v):
    if v is None or v == NULL:
        return None
    s = str(v).strip()
    return None if s == "" or s.upper() in ("NULL", "NONE") else s


def _subgrupo(nombre):
    """Subgrupo propio para cada relacion: se enciende y apaga de una vez."""
    raiz = prj.layerTreeRoot()
    padre = raiz.findGroup(GRUPO_PROG) or raiz.insertGroup(0, GRUPO_PROG)
    hijo = padre.findGroup(nombre)
    if hijo is None:
        hijo = padre.addGroup(nombre)
    return hijo


def _limpiar_subgrupo(nombre):
    padre = prj.layerTreeRoot().findGroup(GRUPO_PROG)
    if padre is None:
        return
    hijo = padre.findGroup(nombre)
    if hijo is None:
        return
    for nodo in list(hijo.findLayers()):
        if nodo.layer() is not None:
            prj.removeMapLayer(nodo.layer().id())
    padre.removeChildNode(hijo)


def _estilo(capa, campo, colores, tam):
    """Categorias con tamano en mm, para que se vean a cualquier escala."""
    tipo = capa.geometryType()
    cats = []
    for valor, color, etiqueta in colores:
        sim = QgsSymbol.defaultSymbol(tipo)
        sim.setColor(QColor(*color))
        # cada tipo de simbolo expone un metodo distinto; el de relleno ninguno
        if tipo == QgsWkbTypes.GeometryType.LineGeometry:
            sim.setWidth(tam)
        elif tipo == QgsWkbTypes.GeometryType.PointGeometry:
            sim.setSize(tam)
        cats.append(QgsRendererCategory(valor, sim, etiqueta))
    capa.setRenderer(QgsCategorizedSymbolRenderer(campo, cats))


def refrescar_progreso(origen, destino, campo, campo_id, t_o, t_d,
                       reciproca=False):
    """Progreso visual de una relacion, en su propio subgrupo.

    Cada objeto se dibuja con SU geometria real. Si origen y destino comparten
    tipo (dos capas de linea, por ejemplo) van en una sola capa con cuatro
    categorias; si no, los destinos se representan por su centroide en una capa
    aparte. Los destinos YA asociados se dibujan siempre; los que faltan solo
    cuando la capa no es demasiado grande para que sirva de algo.
    """
    if not PROGRESO:
        return
    par = "%s %s %s" % (t_o, "<->" if reciproca else "->", t_d)
    _limpiar_subgrupo(par)

    crs = origen.crs().authid()
    tipo_o = QgsWkbTypes.geometryType(origen.wkbType())
    tipo_d = QgsWkbTypes.geometryType(destino.wkbType())
    mismo_tipo = tipo_o == tipo_d
    nombre_tipo = {QgsWkbTypes.GeometryType.PointGeometry: "Point",
                   QgsWkbTypes.GeometryType.LineGeometry: "LineString",
                   QgsWkbTypes.GeometryType.PolygonGeometry: "Polygon"}
    txt_o = nombre_tipo.get(tipo_o, "Point")

    tr_d = (None if destino.crs().authid() == origen.crs().authid()
            else QgsCoordinateTransform(destino.crs(), origen.crs(), prj))
    geo_dest, cen_dest = {}, {}
    for f in destino.getFeatures():
        v = nid(f[campo_id])
        g = f.geometry()
        if v is None or g is None or g.isEmpty():
            continue
        gg = QgsGeometry(g)
        if tr_d is not None:
            gg.transform(tr_d)
        geo_dest[str(v)] = gg
        cen_dest[str(v)] = gg.centroid()

    idx_c = origen.fields().indexOf(campo)
    citados = set()
    filas, vinculos = [], []
    for f in origen.getFeatures():
        g = f.geometry()
        if g is None or g.isEmpty():
            continue
        centro = g.centroid()
        crudo = f[idx_c] if idx_c >= 0 else None
        partes = [x.strip() for x in str(crudo).split(",")] if nid(crudo) else []
        partes = [x for x in partes if x]
        citados.update(partes)
        ident = (str(f[campo_id]) if campo_id in [z.name() for z in origen.fields()]
                 else str(f.id()))
        filas.append((QgsGeometry(g), ident,
                      "ORIGEN_ASOCIADO" if partes else "ORIGEN_PENDIENTE",
                      len(partes)))
        for pid in partes:
            gd = cen_dest.get(pid)
            if gd is not None:
                vinculos.append(QgsGeometry.fromPolylineXY(
                    [centro.asPoint(), gd.asPoint()]))

    asociados = [(p, g) for p, g in geo_dest.items() if p in citados]
    faltantes = [(p, g) for p, g in geo_dest.items() if p not in citados]
    mostrar_faltantes = INCLUIR_DESTINO and len(geo_dest) <= MAX_DESTINOS

    campos = QgsFields()
    campos.append(QgsField("id", QMetaType.Type.QString))
    campos.append(QgsField("rol", QMetaType.Type.QString))
    campos.append(QgsField("n", QMetaType.Type.Int))

    def _nueva(tipo_txt, nombre):
        c = QgsVectorLayer("%s?crs=%s" % (tipo_txt, crs), nombre, "memory")
        c.dataProvider().addAttributes(list(campos))
        c.updateFields()
        return c

    COLORES = [("ORIGEN_ASOCIADO", (0, 200, 0, 255), "%s asociado" % t_o),
               ("ORIGEN_PENDIENTE", (230, 0, 0, 255), "%s pendiente" % t_o),
               ("DESTINO_ASOCIADO", (0, 140, 255, 255), "%s asociado" % t_d),
               ("DESTINO_SIN_ASOCIAR", (255, 170, 0, 255), "%s sin asociar" % t_d)]
    grupo = _subgrupo(par)
    capas_creadas = []

    cap = _nueva(txt_o, "estado")
    fs = []
    for geo, ident, rol, n in filas:
        nf = QgsFeature(campos)
        nf.setGeometry(geo)
        nf.setAttributes([ident, rol, n])
        fs.append(nf)
    if mismo_tipo:
        for pid, g in asociados:
            nf = QgsFeature(campos)
            nf.setGeometry(g)
            nf.setAttributes([pid, "DESTINO_ASOCIADO", 0])
            fs.append(nf)
        if mostrar_faltantes:
            for pid, g in faltantes:
                nf = QgsFeature(campos)
                nf.setGeometry(g)
                nf.setAttributes([pid, "DESTINO_SIN_ASOCIAR", 0])
                fs.append(nf)
    cap.dataProvider().addFeatures(fs)
    cap.updateExtents()
    _estilo(cap, "rol", COLORES,
            1.2 if tipo_o == QgsWkbTypes.GeometryType.LineGeometry else 3.6)
    capas_creadas.append(cap)

    if not mismo_tipo:
        cd = _nueva("Point", t_d.lower())
        fd = []
        for pid, g in asociados:
            nf = QgsFeature(campos)
            nf.setGeometry(cen_dest[pid])
            nf.setAttributes([pid, "DESTINO_ASOCIADO", 0])
            fd.append(nf)
        if mostrar_faltantes:
            for pid, g in faltantes:
                nf = QgsFeature(campos)
                nf.setGeometry(cen_dest[pid])
                nf.setAttributes([pid, "DESTINO_SIN_ASOCIAR", 0])
                fd.append(nf)
        cd.dataProvider().addFeatures(fd)
        cd.updateExtents()
        _estilo(cd, "rol", COLORES, 3.0)
        capas_creadas.append(cd)

    if vinculos:
        cl = QgsVectorLayer("LineString?crs=%s" % crs, "vinculos", "memory")
        fl = []
        for gv in vinculos:
            nf = QgsFeature()
            nf.setGeometry(gv)
            fl.append(nf)
        cl.dataProvider().addFeatures(fl)
        cl.updateExtents()
        sim = QgsSymbol.defaultSymbol(cl.geometryType())
        sim.setColor(QColor(0, 200, 0))
        sim.setWidth(0.5)
        cl.renderer().setSymbol(sim)
        capas_creadas.append(cl)

    for c in capas_creadas:
        prj.addMapLayer(c, False)
        grupo.addLayer(c)

    n_ok = sum(1 for x in filas if x[2] == "ORIGEN_ASOCIADO")
    extra = "" if mostrar_faltantes else \
        "  (faltantes omitidos: %d %s > limite %d)" % (len(geo_dest), t_d, MAX_DESTINOS)
    log("  %-42s %4d/%-5d asociados | %4d vinculos | %4d %s asociados, %d sin asociar%s"
        % (par, n_ok, len(filas), len(vinculos), len(asociados), t_d,
           len(faltantes), extra))


def capas_de_tipo(t):
    salida = []
    for l in prj.mapLayers().values():
        if isinstance(l, QgsVectorLayer) and tipo_de(l.name()) == t:
            salida.append(l)
    return salida


def vaciar_grupo_progreso():
    """Deja el grupo limpio antes de reconstruir.

    Sin esto se acumulan capas de nombrados anteriores y acabas con un grupo
    lleno de restos que ya no corresponden a ninguna relacion.
    """
    raiz = prj.layerTreeRoot()
    g = raiz.findGroup(GRUPO_PROG)
    if g is None:
        return 0
    n = 0
    for nodo in list(g.findLayers()):
        if nodo.layer() is not None:
            prj.removeMapLayer(nodo.layer().id())
            n += 1
    for hijo in list(g.children()):
        if isinstance(hijo, QgsLayerTreeGroup):
            g.removeChildNode(hijo)
    return n


def refrescar_todo():
    """Reconstruye el progreso de TODAS las relaciones que existan cargadas.

    Pensado para el arranque de sesion: de un vistazo ves que asociaciones
    llevas hechas en cada relacion, no solo en la que vas a trabajar ahora.
    """
    if not PROGRESO:
        return
    log("")
    log("PROGRESO DE TODAS LAS RELACIONES")
    log("-" * 70)
    viejas = vaciar_grupo_progreso()
    if viejas:
        log("  (%d capas anteriores retiradas del grupo)" % viejas)
    hechas = 0
    ya = {}          # {t_o, t_d} -> direccion ya dibujada
    for t_o, t_d, campo, card in REGLAS:
        clave = frozenset((t_o, t_d))
        if clave in ya:
            log("  %s -> %s: reciproca de %s, ya representada"
                % (t_o, t_d, ya[clave]))
            continue
        ors = capas_de_tipo(t_o)
        des = capas_de_tipo(t_d)
        if not ors or not des:
            continue
        o = max(ors, key=lambda x: x.featureCount())
        d = max(des, key=lambda x: x.featureCount())
        if o.fields().indexOf(campo) < 0:
            log("  %s -> %s: la capa '%s' no tiene '%s', se omite"
                % (t_o, t_d, o.name(), campo))
            continue
        inv = regla_de(t_d, t_o)
        reciproca = bool(inv[0]) and d.fields().indexOf(inv[2]) >= 0
        if len(ors) > 1 or len(des) > 1:
            log("  aviso: hay varias capas de %s o %s; se usan '%s' y '%s'"
                % (t_o, t_d, o.name(), d.name()))
        try:
            refrescar_progreso(o, d, campo, CAMPO_ID, t_o, t_d, reciproca)
            ya[clave] = "%s -> %s" % (t_o, t_d)
            hechas += 1
        except Exception as e:
            log("  %s -> %s: error al construir el progreso (%s)"
                % (t_o, t_d, str(e)[:70]))
    if not hechas:
        log("  (ninguna relacion tiene sus dos capas cargadas)")
    log("-" * 70)


class Asociador(object):
    def __init__(self, stop_l, lane_l):
        self.stop_l = stop_l
        self.lane_l = lane_l
        self.t_o = tipo_de(stop_l.name())
        self.t_d = tipo_de(lane_l.name())
        self.stop_fid = None
        self.work = QgsCoordinateReferenceSystem(
            "EPSG:%d" % utm_auto(stop_l, lane_l))
        self.tr_s = (None if stop_l.crs().authid() == self.work.authid()
                     else QgsCoordinateTransform(stop_l.crs(), self.work, prj))
        self.tr_l = (None if lane_l.crs().authid() == self.work.authid()
                     else QgsCoordinateTransform(lane_l.crs(), self.work, prj))

    # ---------------------------------------------------------- paso 1
    def tomar_stopline(self):
        sel = self.stop_l.selectedFeatures()
        if len(sel) != 1:
            barra("ORIGEN: selecciona exactamente 1 %s en '%s' (tienes %d)."
                  % (self.t_o, self.stop_l.name(), len(sel)),
                  Qgis.MessageLevel.Warning, 7)
            return
        f = sel[0]
        self.stop_fid = f.id()
        actual = nid(f[CAMPO]) if CAMPO in [x.name() for x in self.stop_l.fields()] else None
        g = QgsGeometry(f.geometry())
        if self.tr_s is not None:
            g.transform(self.tr_s)
        log("")
        log("%s id=%s  fid=%d  |  %s actual: %s"
            % (self.t_o,
               f[CAMPO_ID] if CAMPO_ID in [x.name() for x in self.stop_l.fields()]
               else "?", f.id(), CAMPO, actual or "(vacio)"))

        # La preseleccion por buffer solo tiene sentido entre lineas: mide
        # contacto geometrico. Para puntos o poligonos (poste, caja, bombilla)
        # la cercania no implica asociacion, asi que se selecciona a mano.
        def _es_linea(cp):
            return (QgsWkbTypes.geometryType(cp.wkbType())
                    == QgsWkbTypes.GeometryType.LineGeometry)

        if not AUTOSEL:
            barra("%s tomado. Selecciona los %s y pulsa %s."
                  % (self.t_o, self.t_d, T_ESCR))
            return
        if not (_es_linea(self.stop_l) and _es_linea(self.lane_l)):
            log("  preseleccion omitida: solo se aplica entre capas de LINEA "
                "(%s es %s, %s es %s)."
                % (self.stop_l.name(),
                   QgsWkbTypes.geometryDisplayString(
                       QgsWkbTypes.geometryType(self.stop_l.wkbType())),
                   self.lane_l.name(),
                   QgsWkbTypes.geometryDisplayString(
                       QgsWkbTypes.geometryType(self.lane_l.wkbType()))))
            barra("Origen tomado. Preseleccion no aplica (no son lineas): "
                  "selecciona a mano y pulsa %s." % T_ESCR,
                  Qgis.MessageLevel.Info, 7)
            return
        zona = g.buffer(TOL, 8)
        # bbox en el CRS de la capa lanelet para filtrar rapido
        caja = zona.boundingBox()
        if self.tr_l is not None:
            caja = QgsCoordinateTransform(
                self.work, self.lane_l.crs(), prj).transformBoundingBox(caja)
        tocan = []
        for lf in self.lane_l.getFeatures(QgsFeatureRequest().setFilterRect(caja)):
            lg = QgsGeometry(lf.geometry())
            if lg is None or lg.isEmpty():
                continue
            if self.tr_l is not None:
                lg.transform(self.tr_l)
            if zona.intersects(lg):
                tocan.append(lf)
        self.lane_l.selectByIds([x.id() for x in tocan])
        log("  preseleccionados %d %s dentro de %.2f m"
            % (len(tocan), self.t_d, TOL))
        for x in tocan[:12]:
            log("     %s id=%s" % (self.t_d, x[CAMPO_ID]))
        barra("%s tomado. %d %s preseleccionados; ajusta y pulsa %s."
              % (self.t_o, len(tocan), self.t_d, T_ESCR),
              Qgis.MessageLevel.Info, 7)

    # ---------------------------------------------------------- paso 2
    def escribir(self):
        if self.stop_fid is None:
            barra("Primero confirma el %s de origen con %s." % (self.t_o, T_STOP),
                  Qgis.MessageLevel.Warning)
            return
        campos = [x.name() for x in self.stop_l.fields()]
        if CAMPO not in campos:
            barra("La capa '%s' no tiene el campo '%s'."
                  % (self.stop_l.name(), CAMPO), Qgis.MessageLevel.Critical, 7)
            return
        sel = self.lane_l.selectedFeatures()
        if not sel:
            barra("No hay %s seleccionados en el destino." % self.t_d,
                  Qgis.MessageLevel.Warning)
            return
        card = globals().get("CARD", "1:n")
        if card == "n:1" and len(sel) != 1:
            barra("Relacion n:1: selecciona exactamente 1 objeto en el destino "
                  "(tienes %d)." % len(sel), Qgis.MessageLevel.Warning, 7)
            return
        ids = []
        for f in sel:
            v = nid(f[CAMPO_ID])
            if v is not None and v not in ids:
                ids.append(v)
        if not ids:
            barra("Los %s seleccionados no tienen %s." % (self.t_d, CAMPO_ID),
                  Qgis.MessageLevel.Warning)
            return

        feat = self.stop_l.getFeature(self.stop_fid)
        previos = nid(feat[CAMPO])
        if card == "n:1":
            ids = ids[:1]
        elif ANEXAR and previos:
            base = [x.strip() for x in str(previos).split(",") if x.strip()]
            for x in ids:
                if x not in base:
                    base.append(x)
            ids = base
        if ORDENAR and card != "n:1":
            try:
                ids = sorted(ids, key=lambda x: int(x))
            except (TypeError, ValueError):
                ids = sorted(ids)
        valor = ",".join(ids)

        idx = self.stop_l.fields().indexOf(CAMPO)
        estaba = self.stop_l.isEditable()
        if not estaba:
            self.stop_l.startEditing()
        # comando de edicion: esto es lo que hace que Ctrl+Z lo revierta
        self.stop_l.beginEditCommand(
            "Asociar %d %s a %s" % (len(ids), self.t_d, self.t_o))
        ok = self.stop_l.changeAttributeValue(self.stop_fid, idx, valor)
        self.stop_l.endEditCommand()
        if not ok:
            barra("No se pudo escribir el atributo.", Qgis.MessageLevel.Critical)
            return
        if GUARDAR:
            if not self.stop_l.commitChanges(False):
                for e in self.stop_l.commitErrors()[:4]:
                    log("  ERROR: %s" % e)
                self.stop_l.rollBack(False)
                barra("Commit fallido, se revirtio.", Qgis.MessageLevel.Critical, 6)
                return

        # ---- lado inverso: mantiene las dos direcciones sincronizadas
        inv_txt = ""
        if ESCRIBIR_INVERSO:
            it_o, it_d, icampo, icard = regla_de(self.lane_l.name(),
                                                 self.stop_l.name())
            campos_d = [x.name() for x in self.lane_l.fields()]
            id_origen = None
            if CAMPO_ID in [x.name() for x in self.stop_l.fields()]:
                id_origen = nid(feat[CAMPO_ID])
            if it_o is None:
                inv_txt = "  (sin regla inversa definida)"
            elif icampo not in campos_d:
                inv_txt = "  (la capa destino no tiene '%s')" % icampo
            elif id_origen is None:
                inv_txt = "  (el origen no tiene %s)" % CAMPO_ID
            else:
                idx_i = self.lane_l.fields().indexOf(icampo)
                era = self.lane_l.isEditable()
                if not era:
                    self.lane_l.startEditing()
                self.lane_l.beginEditCommand(
                    "Asociar %s a %d %s (inverso)"
                    % (self.t_o, len(sel), self.t_d))
                n_inv = 0
                for df in sel:
                    if icard == "n:1":
                        nuevo_val = str(id_origen)
                    else:
                        prev = nid(df[icampo])
                        lista = ([x.strip() for x in str(prev).split(",") if x.strip()]
                                 if prev else [])
                        if str(id_origen) not in lista:
                            lista.append(str(id_origen))
                        nuevo_val = ",".join(lista)
                    if self.lane_l.changeAttributeValue(df.id(), idx_i, nuevo_val):
                        n_inv += 1
                self.lane_l.endEditCommand()
                if GUARDAR:
                    if not self.lane_l.commitChanges(False):
                        for e in self.lane_l.commitErrors()[:3]:
                            log("  ERROR inverso: %s" % e)
                        self.lane_l.rollBack(False)
                        inv_txt = "  (fallo el commit del inverso, revertido)"
                    else:
                        inv_txt = "  |  %s.%s <- %s en %d objetos" % (
                            self.t_d, icampo, id_origen, n_inv)
                else:
                    inv_txt = "  |  %s.%s <- %s en %d objetos (sin guardar)" % (
                        self.t_d, icampo, id_origen, n_inv)

        log("  %s <- %d ids: %s%s" % (CAMPO, len(ids), valor[:120], inv_txt))
        log("     %s" % ("guardado en disco" if GUARDAR
                         else "en la sesion de edicion (Ctrl+Z deshace, Ctrl+S guarda)"))
        barra("%d %s asociados%s. %s"
              % (len(ids), self.t_d, " (anexado)" if ANEXAR else "",
                 "Guardado." if GUARDAR else "Ctrl+Z deshace, Ctrl+S guarda."),
              Qgis.MessageLevel.Success, 6)
        self.stop_fid = None
        self.stop_l.removeSelection()
        self.lane_l.removeSelection()
        self.stop_l.triggerRepaint()
        _inv = regla_de(self.lane_l.name(), self.stop_l.name())
        _rec = bool(_inv[0]) and self.lane_l.fields().indexOf(_inv[2]) >= 0
        refrescar_progreso(self.stop_l, self.lane_l, CAMPO, CAMPO_ID,
                           self.t_o, self.t_d, _rec)

    def cancelar(self):
        self.stop_fid = None
        barra("Cancelado.")


# ------------------------------ activacion ----------------------------------
def _quitar():
    for a in ("_as_k1", "_as_k2", "_as_kesc"):
        s = getattr(_qu, a, None)
        if s is not None:
            try:
                s.setEnabled(False)
                s.deleteLater()
            except Exception:
                pass
            delattr(_qu, a)


if DESACTIVAR:
    _quitar()
    if hasattr(_qu, "_as_tool"):
        delattr(_qu, "_as_tool")
    log("Asociador DESACTIVADO.")
else:
    stop_l = capa(str(N_STOP)) if N_STOP else None
    lane_l = capa(str(N_LANE))
    if stop_l is None:
        raise RuntimeError("Elige la capa STOP_LINE (no se encontro '%s')." % N_STOP)
    if lane_l is None:
        raise RuntimeError("No se encontro la capa DESTINO '%s'." % N_LANE)
    t_o, t_d, campo_regla, CARD = regla_de(stop_l.name(), lane_l.name())
    if t_o is None:
        detalle = "\n".join("    %-20s -> %-20s  %-24s %s" % r for r in REGLAS)
        raise RuntimeError(
            "Par no permitido: '%s' (%s) -> '%s' (%s).\n"
            "Asociaciones validas (todas 1:n):\n%s"
            % (stop_l.name(), tipo_de(stop_l.name()),
               lane_l.name(), tipo_de(lane_l.name()), detalle))
    # el campo lo manda la regla salvo que se indique otro a mano
    if not str(_p("CAMPO_DESTINO", "")).strip():
        CAMPO = campo_regla
    if CAMPO not in [x.name() for x in stop_l.fields()]:
        raise RuntimeError(
            "CAMPO INEXISTENTE — la regla %s -> %s (%s) escribe en '%s', y la "
            "capa '%s' no tiene ese campo.\n"
            "  Campos disponibles: %s\n"
            "  Crea el campo en la capa antes de usar esta asociacion, o indica "
            "otro en 'Campo donde escribir'."
            % (t_o, t_d, CARD, CAMPO, stop_l.name(),
               ", ".join(x.name() for x in stop_l.fields())))

    if CAMPO_ID not in [x.name() for x in lane_l.fields()]:
        raise RuntimeError(
            "CAMPO INEXISTENTE — la capa destino '%s' no tiene el campo '%s', "
            "asi que no hay ids que copiar.\n  Campos disponibles: %s"
            % (lane_l.name(), CAMPO_ID,
               ", ".join(x.name() for x in lane_l.fields())))
    globals()["CARD"] = CARD
    _quitar()
    obj = Asociador(stop_l, lane_l)
    _qu._as_tool = obj

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
    for t in (T_STOP, T_ESCR):
        if t in ocupadas:
            log("  AVISO: %s ya esta asignada en QGIS a '%s'." % (t, ocupadas[t]))

    k1 = QShortcut(QKeySequence(T_STOP), mw)
    k1.activated.connect(obj.tomar_stopline)
    k2 = QShortcut(QKeySequence(T_ESCR), mw)
    k2.activated.connect(obj.escribir)
    _qu._as_k1, _qu._as_k2 = k1, k2

    tipo = stop_l.fields()[stop_l.fields().indexOf(CAMPO)].typeName()
    log("Asociador de relaciones 1:n ACTIVO")
    log("  regla     : %s -> %s   campo '%s'   cardinalidad %s"
        % (t_o, t_d, CAMPO, CARD))
    if CARD == "n:1":
        log("  n:1 -> debes seleccionar UN SOLO %s en el destino." % t_d)
    log("  origen    : %s (%d features)" % (stop_l.name(), stop_l.featureCount()))
    log("  destino   : %s (%d features)" % (lane_l.name(), lane_l.featureCount()))
    log("  campo     : %s (tipo %s)  |  id tomado de %s.%s"
        % (CAMPO, tipo, t_d, CAMPO_ID))
    log("  tolerancia: %.2f m  |  autoseleccion: %s  |  modo: %s"
        % (TOL, "si" if AUTOSEL else "no", "anexar" if ANEXAR else "reemplazar"))
    log("  %s tomar origen | %s escribir | Ctrl+Z deshace | Ctrl+S guarda"
        % (T_STOP, T_ESCR))
    if REFRESCAR_TODO:
        refrescar_todo()
    else:
        refrescar_progreso(stop_l, lane_l, CAMPO, CAMPO_ID, t_o, t_d)
    barra("Selecciona 1 %s y pulsa %s." % (t_o, T_STOP), Qgis.MessageLevel.Info, 8)
