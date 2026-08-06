# -*- coding: utf-8 -*-
"""street_view_captura — registra observaciones de Street View en un GeoPackage.

Flujo:
  1. Colocas la vista en el navegador sobre el elemento (semaforo o senal)
  2. Copias la URL con Ctrl+L, Ctrl+C
  3. Pulsas el atajo en QGIS: cuenta atras, vuelves al navegador y captura
  4. Se anaden dos entidades al GeoPackage: el punto de la CAMARA y el RAYO
     de vision en la direccion del heading

De la URL se extraen lat/lon de la camara, heading, pitch, fov y panoid. Ojo:
esas coordenadas son las del vehiculo de Street View, NO las del objeto. Por eso
se guarda ademas el rayo: la interseccion de dos rayos de dos capturas distintas
te da la posicion real del elemento.
"""
import math
import os
import re
import urllib.parse
from datetime import datetime

from qgis.core import (
    Qgis, QgsCoordinateReferenceSystem, QgsCoordinateTransform, QgsFeature,
    QgsFields, QgsField, QgsGeometry, QgsMessageLog, QgsPointXY, QgsProject,
    QgsSymbol, QgsVectorFileWriter, QgsVectorLayer, QgsWkbTypes,
    QgsCoordinateTransformContext,
)
from qgis.PyQt.QtCore import QMetaType, Qt, QTimer
from qgis.PyQt.QtGui import QColor, QGuiApplication, QKeySequence, QPixmap
from qgis.PyQt.QtWidgets import (
    QComboBox, QDialog, QDialogButtonBox, QFormLayout, QLabel, QLineEdit,
    QShortcut, QSpinBox, QVBoxLayout)
import qgis.utils as _qu

P = globals().get("PLUGIN_PARAMS", {}) or {}
IFACE = globals().get("iface", None) or _qu.iface


def _p(k, d=None):
    v = P.get(k, globals().get(k, d))
    return d if v is None or v == "" else v


SALIDA = str(_p("SALIDA", "temporal")).strip().lower()   # temporal | gpkg
GPKG = str(_p("GPKG", "") or "").strip()
ZOOM = bool(_p("ZOOM_AL_PUNTO", True))
NOMBRE_CAPA = str(_p("NOMBRE_CAPA", "sv_observaciones")).strip() or "sv_observaciones"
VENTANA = str(_p("VENTANA", "Google Maps") or "").strip()
DIALOGO = bool(_p("DIALOGO", True))
ANCHO_PREVIA = int(_p("ANCHO_PREVIA", 720))
CARPETA_IMG = str(_p("CARPETA_IMAGENES", "") or "").strip()
TIPO_LAYER = str(_p("TIPO_LAYER", "traffic_light"))
TIPO = str(_p("TYPE", "") or "")
CODE = str(_p("CODE", "") or "")
FOCOS = _p("FOCOS", None)
LARGO_RAYO = float(_p("LARGO_RAYO", 30.0))
ESPERA = int(_p("ESPERA", 3))
CAPTURAR = bool(_p("CAPTURAR_PANTALLA", True))
TECLA = str(_p("TECLA", "Ctrl+F2"))
DESACTIVAR = bool(_p("DESACTIVAR", False))
CARGAR = bool(_p("CARGAR", True))

prj = QgsProject.instance()
WGS = QgsCoordinateReferenceSystem("EPSG:4326")


def log(m=""):
    print(m)
    try:
        QgsMessageLog.logMessage(str(m), "Mi Plugin", level=Qgis.MessageLevel.Info)
    except Exception:
        pass


def barra(m, n=Qgis.MessageLevel.Info, s=5):
    IFACE.messageBar().pushMessage("Street View", m, level=n, duration=s)


# ------------------------------ parseo de URL -------------------------------
def parsear(url):
    """Extrae camara, orientacion y panoid de una URL de Street View."""
    if not url or "google" not in url.lower():
        return None
    u = urllib.parse.unquote(url)
    m = re.search(r"@(-?\d+\.\d+),(-?\d+\.\d+),([\d.]+)a,([\d.]+)y,"
                  r"([\d.]+)h,([\d.]+)t", u)
    if not m:
        return None
    lat, lon, _a, fov, heading, tilt = [float(x) for x in m.groups()]
    d = {"lat": lat, "lon": lon, "fov": fov, "heading": heading,
         "pitch": 90.0 - tilt, "panoid": None}
    pan = re.search(r"!1s([A-Za-z0-9_\-]{20,})", u)
    if pan:
        d["panoid"] = pan.group(1)
    # el bloque thumbnail trae yaw/pitch con mas decimales; manda si esta
    for clave, destino in (("yaw", "heading"), ("pitch", "pitch")):
        mm = re.search(r"[?&]%s=(-?\d+(?:\.\d+)?)" % clave, u)
        if mm:
            d[destino] = float(mm.group(1))
    return d


def destino_geodesico(lat, lon, rumbo, dist):
    """Punto a 'dist' metros siguiendo 'rumbo' desde lat/lon."""
    R = 6378137.0
    br = math.radians(rumbo)
    f1 = math.radians(lat)
    l1 = math.radians(lon)
    f2 = math.asin(math.sin(f1) * math.cos(dist / R) +
                   math.cos(f1) * math.sin(dist / R) * math.cos(br))
    l2 = l1 + math.atan2(math.sin(br) * math.sin(dist / R) * math.cos(f1),
                         math.cos(dist / R) - math.sin(f1) * math.sin(f2))
    return math.degrees(f2), math.degrees(l2)


# ------------------------------ GeoPackage ----------------------------------
def campos():
    f = QgsFields()
    for n, t in [("code", QMetaType.Type.QString),
                 ("type", QMetaType.Type.QString),
                 ("tipo_layer", QMetaType.Type.QString),
                 ("focos", QMetaType.Type.Int),
                 ("link", QMetaType.Type.QString),
                 ("imagen", QMetaType.Type.QString),
                 ("panoid", QMetaType.Type.QString),
                 ("lat", QMetaType.Type.Double),
                 ("lon", QMetaType.Type.Double),
                 ("heading", QMetaType.Type.Double),
                 ("pitch", QMetaType.Type.Double),
                 ("fov", QMetaType.Type.Double),
                 ("fecha", QMetaType.Type.QString),
                 ("rol", QMetaType.Type.QString)]:
        f.append(QgsField(n, t))
    return f


def _simbolo(capa, color, tam):
    sim = QgsSymbol.defaultSymbol(capa.geometryType())
    sim.setColor(QColor(*color))
    if capa.geometryType() == QgsWkbTypes.GeometryType.PointGeometry:
        sim.setSize(tam)
    else:
        sim.setWidth(tam)
    capa.renderer().setSymbol(sim)


def _widgets(capa):
    """Deja 'link' como hipervinculo y 'imagen' como recurso con vista previa.

    Sin esto los dos campos son texto plano y hay que copiar y pegar la ruta a
    mano para abrir la captura o volver a la vista de Street View.
    """
    try:
        from qgis.core import QgsEditorWidgetSetup
    except ImportError:
        return
    i_link = capa.fields().indexOf("link")
    if i_link >= 0:
        capa.setEditorWidgetSetup(i_link, QgsEditorWidgetSetup(
            "ExternalResource",
            {"UseLink": True, "FullUrl": True, "DocumentViewer": 0}))
    i_img = capa.fields().indexOf("imagen")
    if i_img >= 0:
        capa.setEditorWidgetSetup(i_img, QgsEditorWidgetSetup(
            "ExternalResource",
            {"UseLink": True, "FullUrl": True,
             "DocumentViewer": 1,          # 1 = imagen, con miniatura
             "DocumentViewerHeight": 260, "DocumentViewerWidth": 380,
             "RelativeStorage": 0}))


def capa_memoria(nombre, tipo_geom):
    """Capa temporal reutilizada entre capturas de la misma sesion."""
    exist = prj.mapLayersByName(nombre)
    if exist:
        return exist[0]
    l = QgsVectorLayer("%s?crs=EPSG:4326" % tipo_geom, nombre, "memory")
    l.dataProvider().addAttributes(list(campos()))
    l.updateFields()
    _simbolo(l, (255, 0, 0, 255) if tipo_geom == "Point" else (255, 140, 0, 255),
             4.0 if tipo_geom == "Point" else 0.8)
    _widgets(l)
    prj.addMapLayer(l)
    return l


def capa_gpkg(ruta_gpkg, nombre, tipo_geom):
    """Abre la tabla del GeoPackage; la crea si no existe."""
    uri = "%s|layername=%s" % (ruta_gpkg, nombre)
    l = QgsVectorLayer(uri, nombre, "ogr")
    if l.isValid():
        _widgets(l)
        return l
    tmp = QgsVectorLayer("%s?crs=EPSG:4326" % tipo_geom, nombre, "memory")
    tmp.dataProvider().addAttributes(list(campos()))
    tmp.updateFields()
    opt = QgsVectorFileWriter.SaveVectorOptions()
    opt.driverName = "GPKG"
    opt.layerName = nombre
    opt.fileEncoding = "UTF-8"
    if os.path.exists(ruta_gpkg):
        opt.actionOnExistingFile = \
            QgsVectorFileWriter.ActionOnExistingFile.CreateOrOverwriteLayer
    err = QgsVectorFileWriter.writeAsVectorFormatV3(
        tmp, ruta_gpkg, QgsCoordinateTransformContext(), opt)
    if err[0] != QgsVectorFileWriter.WriterError.NoError:
        raise RuntimeError("No se pudo crear '%s' en el GeoPackage: %s"
                           % (nombre, err[1]))
    l = QgsVectorLayer(uri, nombre, "ogr")
    if not l.isValid():
        raise RuntimeError("Creada pero no se pudo abrir: %s" % uri)
    _simbolo(l, (255, 0, 0, 255) if tipo_geom == "Point" else (255, 140, 0, 255),
             4.0 if tipo_geom == "Point" else 0.8)
    _widgets(l)
    return l


def siguiente_code(capa):
    n = 0
    for f in capa.getFeatures():
        v = f["code"]
        if v is None:
            continue
        m = re.search(r"(\d+)$", str(v))
        if m:
            n = max(n, int(m.group(1)))
    return n + 1


# ------------------------------ captura -------------------------------------
def _buscar_ventana(texto):
    """Devuelve (hwnd, titulo) de la primera ventana visible que contenga el texto."""
    try:
        import ctypes
        from ctypes import wintypes
    except Exception:
        return None, None
    u = ctypes.windll.user32
    hallada = []

    Proc = ctypes.WINFUNCTYPE(ctypes.c_bool, wintypes.HWND, wintypes.LPARAM)

    def cb(h, _l):
        if u.IsWindowVisible(h):
            n = u.GetWindowTextLengthW(h)
            if n:
                b = ctypes.create_unicode_buffer(n + 1)
                u.GetWindowTextW(h, b, n + 1)
                if texto.lower() in b.value.lower():
                    hallada.append((h, b.value))
                    return False
        return True

    u.EnumWindows(Proc(cb), 0)
    return hallada[0] if hallada else (None, None)


def capturar_pantalla(destino):
    """Captura la ventana del navegador; si no la encuentra, la pantalla entera.

    Apuntar a la ventana evita dos problemas: que la captura salga con QGIS
    delante, y que con varios monitores se recorte la pantalla equivocada.
    """
    os.makedirs(os.path.dirname(destino), exist_ok=True)
    pix = None
    titulo = None
    if VENTANA:
        try:
            import ctypes
            from ctypes import wintypes
            from qgis.PyQt.QtCore import QPoint

            hwnd, titulo = _buscar_ventana(VENTANA)
            if hwnd:
                u = ctypes.windll.user32
                u.SetForegroundWindow(hwnd)
                QGuiApplication.processEvents()
                import time as _t
                _t.sleep(0.45)          # deja que el navegador se pinte
                r = wintypes.RECT()
                u.GetWindowRect(hwnd, ctypes.byref(r))
                x, y = r.left, r.top
                an, al = r.right - r.left, r.bottom - r.top
                scr = QGuiApplication.screenAt(QPoint(x + 5, y + 5)) \
                    or QGuiApplication.primaryScreen()
                g = scr.geometry()
                pix = scr.grabWindow(0, x - g.x(), y - g.y(), an, al)
        except Exception as e:
            log("  aviso: no se pudo capturar la ventana '%s' (%s); "
                "se usa la pantalla completa" % (VENTANA, str(e)[:60]))
            pix = None
    if pix is None or pix.isNull():
        scr = QGuiApplication.primaryScreen()
        if scr is None:
            return None
        pix = scr.grabWindow(0)
        titulo = None
    if pix.isNull():
        return None
    ok = pix.save(destino, "PNG")
    if ok and titulo:
        log("  captura de la ventana: %s" % titulo[:70])
    # devolver el foco a QGIS para seguir trabajando
    try:
        IFACE.mainWindow().activateWindow()
        IFACE.mainWindow().raise_()
    except Exception:
        pass
    return destino if ok else None


class DialogoCaptura(QDialog):
    """Vista previa de la captura y campos del elemento.

    Rellenar aqui, con la imagen delante, evita tener que reabrir Street View
    despues para saber que tipo de senal era o cuantos focos tenia.
    """

    def __init__(self, ruta_img, datos, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Registrar observacion de Street View")
        v = QVBoxLayout(self)

        if ruta_img and os.path.exists(ruta_img):
            px = QPixmap(ruta_img)
            if not px.isNull():
                lab = QLabel()
                lab.setPixmap(px.scaledToWidth(
                    ANCHO_PREVIA, Qt.TransformationMode.SmoothTransformation))
                v.addWidget(lab)
        v.addWidget(QLabel(
            "camara %.7f, %.7f   |   heading %.2f   pitch %.2f   fov %.1f"
            % (datos["lat"], datos["lon"], datos["heading"],
               datos["pitch"], datos["fov"])))

        form = QFormLayout()
        self.code = QLineEdit(str(getattr(_qu, "_sv_code", "") or ""))
        self.code.setPlaceholderText("vacio = correlativo automatico")
        self.capa = QComboBox()
        self.capa.setEditable(True)
        self.capa.addItems(["traffic_light", "traffic_sign"])
        self.capa.setCurrentText(getattr(_qu, "_sv_tipo", TIPO_LAYER))
        self.tipo = QLineEdit(str(getattr(_qu, "_sv_type", "") or ""))
        self.focos = QSpinBox()
        self.focos.setRange(0, 12)
        self.focos.setValue(int(getattr(_qu, "_sv_focos", 0) or 0))
        form.addRow("code (mismo en dos vistas del mismo objeto):", self.code)
        form.addRow("tipo_layer:", self.capa)
        form.addRow("type:", self.tipo)
        form.addRow("focos (0 = sin dato):", self.focos)
        v.addLayout(form)

        bb = QDialogButtonBox()
        bb.addButton("Guardar", QDialogButtonBox.ButtonRole.AcceptRole)
        bb.addButton("Descartar", QDialogButtonBox.ButtonRole.RejectRole)
        bb.accepted.connect(self.accept)
        bb.rejected.connect(self.reject)
        v.addWidget(bb)
        self.code.setFocus()

    def valores(self):
        return {"code": self.code.text().strip(),
                "tipo_layer": self.capa.currentText().strip(),
                "type": self.tipo.text().strip(),
                "focos": self.focos.value()}


def registrar(datos, ruta_img, extra=None):
    extra = extra or {}
    n_pts = NOMBRE_CAPA
    n_ray = NOMBRE_CAPA + "_rayos"
    if SALIDA == "gpkg":
        pts = capa_gpkg(GPKG, n_pts, "Point")
        ray = capa_gpkg(GPKG, n_ray, "LineString")
    else:
        pts = capa_memoria(n_pts, "Point")
        ray = capa_memoria(n_ray, "LineString")
    tipo_layer = extra.get("tipo_layer") or TIPO_LAYER
    code = (extra.get("code") or CODE
            or "%s_%04d" % (tipo_layer.upper()[:2], siguiente_code(pts)))
    ahora = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    focos = extra.get("focos")
    if focos in (None, "", 0):
        try:
            focos = int(FOCOS) if FOCOS not in (None, "", 0) else None
        except (TypeError, ValueError):
            focos = None

    # por NOMBRE, no por posicion: el GeoPackage anade un campo 'fid' propio y
    # una lista posicional quedaria desplazada un puesto
    comunes = {"code": code, "type": extra.get("type") or TIPO,
               "tipo_layer": tipo_layer,
               "focos": focos, "link": datos["url"], "imagen": ruta_img or "",
               "panoid": datos.get("panoid") or "", "lat": datos["lat"],
               "lon": datos["lon"], "heading": datos["heading"],
               "pitch": datos["pitch"], "fov": datos["fov"], "fecha": ahora}

    def _alta(capa, geom, rol):
        f = QgsFeature(capa.fields())
        f.setGeometry(geom)
        nombres = [x.name() for x in capa.fields()]
        for k, v in list(comunes.items()) + [("rol", rol)]:
            if k in nombres:
                f[k] = v
        ok, _ = capa.dataProvider().addFeatures([f])
        if not ok:
            raise RuntimeError("No se pudo escribir en '%s': %s"
                               % (capa.name(), capa.dataProvider().lastError()))

    _alta(pts, QgsGeometry.fromPointXY(QgsPointXY(datos["lon"], datos["lat"])),
          "CAMARA")
    lat2, lon2 = destino_geodesico(datos["lat"], datos["lon"],
                                   datos["heading"], LARGO_RAYO)
    _alta(ray, QgsGeometry.fromPolylineXY(
        [QgsPointXY(datos["lon"], datos["lat"]), QgsPointXY(lon2, lat2)]), "RAYO")

    for c in (pts, ray):
        c.updateExtents()
        c.triggerRepaint()
    if CARGAR:
        for c in (pts, ray):
            if not prj.mapLayersByName(c.name()):
                prj.addMapLayer(c)
    # llevar el lienzo al punto recien registrado
    if ZOOM:
        try:
            lienzo = IFACE.mapCanvas()
            tr = QgsCoordinateTransform(WGS, lienzo.mapSettings().destinationCrs(), prj)
            p = tr.transform(QgsPointXY(datos["lon"], datos["lat"]))
            e = lienzo.extent()
            if not e.contains(p):
                lienzo.setCenter(p)
            lienzo.refresh()
        except Exception:
            pass
    return code, pts.featureCount()


def capturar():
    portapapeles = QGuiApplication.clipboard().text()
    datos = parsear(portapapeles)
    if datos is None:
        barra("El portapapeles no tiene una URL de Street View valida. "
              "Copia la URL con Ctrl+L, Ctrl+C.", Qgis.MessageLevel.Warning, 7)
        return
    datos["url"] = portapapeles.strip()
    if SALIDA == "gpkg" and not GPKG:
        barra("Indica el GeoPackage de salida.", Qgis.MessageLevel.Critical)
        return

    def _finalizar():
        img = None
        if CAPTURAR and CARPETA_IMG:
            nombre = "sv_%s.png" % datetime.now().strftime("%Y%m%d_%H%M%S")
            img = capturar_pantalla(os.path.join(CARPETA_IMG, nombre))
        extra = {}
        if DIALOGO:
            dlg = DialogoCaptura(img, datos, IFACE.mainWindow())
            if dlg.exec() != QDialog.DialogCode.Accepted:
                if img and os.path.exists(img):
                    try:
                        os.remove(img)
                    except OSError:
                        pass
                barra("Captura descartada.", Qgis.MessageLevel.Info, 3)
                return
            extra = dlg.valores()
            _qu._sv_code = extra["code"]
            _qu._sv_tipo = extra["tipo_layer"]
            _qu._sv_type = extra["type"]
            _qu._sv_focos = extra["focos"]
        try:
            code, total = registrar(datos, img, extra)
        except Exception as e:
            barra("Error al registrar: %s" % str(e)[:120],
                  Qgis.MessageLevel.Critical, 8)
            log("ERROR: %s" % e)
            return
        log("[%s] %s  lat=%.7f lon=%.7f  heading=%.2f  pitch=%.2f  fov=%.1f"
            % (code, TIPO_LAYER, datos["lat"], datos["lon"],
               datos["heading"], datos["pitch"], datos["fov"]))
        log("        panoid=%s  imagen=%s"
            % (datos.get("panoid"), os.path.basename(img) if img else "(sin captura)"))
        barra("Registrado %s  (%d observaciones)" % (code, total),
              Qgis.MessageLevel.Success, 5)

    if CAPTURAR and CARPETA_IMG and ESPERA > 0:
        barra("Vuelve al navegador: captura en %d s..." % ESPERA,
              Qgis.MessageLevel.Info, ESPERA)
        QTimer.singleShot(ESPERA * 1000, _finalizar)
    else:
        _finalizar()


# ------------------------------ activacion ----------------------------------
def _quitar():
    a = getattr(_qu, "_sv_k", None)
    if a is not None:
        try:
            a.setEnabled(False)
            a.deleteLater()
        except Exception:
            pass
        delattr(_qu, "_sv_k")


if DESACTIVAR:
    _quitar()
    log("Captura de Street View DESACTIVADA.")
else:
    if SALIDA == "gpkg" and not GPKG:
        raise RuntimeError("Con salida 'gpkg' debes indicar la ruta del archivo.")
    if CAPTURAR and not CARPETA_IMG:
        raise RuntimeError("Indica la carpeta de imagenes o desactiva la captura.")
    _quitar()
    try:
        from qgis.gui import QgsGui
        for a in QgsGui.shortcutsManager().listActions():
            if a.shortcut().toString() == TECLA:
                log("  AVISO: %s ya esta asignada en QGIS a '%s'."
                    % (TECLA, a.text().replace("&", "")))
    except Exception:
        pass
    k = QShortcut(QKeySequence(TECLA), IFACE.mainWindow())
    k.activated.connect(capturar)
    _qu._sv_k = k
    _qu._sv_capturar = capturar
    log("Captura de Street View ACTIVA")
    log("  capas      : %s / %s_rayos" % (NOMBRE_CAPA, NOMBRE_CAPA))
    log("  salida     : %s" % ("GeoPackage %s" % GPKG if SALIDA == "gpkg"
                                 else "capas TEMPORALES en memoria"))
    log("  imagenes   : %s" % (CARPETA_IMG or "(sin captura)"))
    log("  tipo_layer : %s  |  type: %s  |  focos: %s"
        % (TIPO_LAYER, TIPO or "-", FOCOS if FOCOS not in (None, "") else "-"))
    log("  ventana    : %s" % (VENTANA or "(pantalla completa)"))
    log("  rayo       : %.1f m  |  espera antes de capturar: %d s" % (LARGO_RAYO, ESPERA))
    log("  %s = copiar URL en el navegador y pulsar aqui" % TECLA)
    barra("Copia la URL de Street View y pulsa %s." % TECLA, Qgis.MessageLevel.Info, 8)
