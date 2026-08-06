# -*- coding: utf-8 -*-
"""Optimiza rasteres a COG: tiled + overviews internos + mascara integrada.

Convierte GeoTIFF (u otros formatos GDAL) a Cloud Optimized GeoTIFF. Elige la
compresion segun el tipo de dato: JPEG/YCbCr para ortos RGB de 8 bits, DEFLATE
con predictor para DEM y demas. Resuelve dos cuellos de botella tipicos:
rasteres organizados en tiras (block = ancho completo) y ausencia de piramides.

Si se indica CRS_SALIDA, reproyecta antes de escribir el COG. La reproyeccion
usa gdal.Warp sobre un VRT intermedio en memoria y conserva la mascara de
validez (alfa temporal -> mascara interna), para que los bordes no salgan
negros. El archivo lleva sufijo con el codigo EPSG para no pisar el original.
"""
import os
import time

from osgeo import gdal, osr
from qgis.core import QgsProject, QgsRasterLayer, QgsRectangle

gdal.UseExceptions()

# --------------------------------------------------------------------------
# Valores por defecto (el plugin inyecta los de la interfaz con estos nombres)
# --------------------------------------------------------------------------
if "ENTRADA" not in globals():
    ENTRADA = []
if "SALIDA" not in globals():
    SALIDA = ""
if "CRS_SALIDA" not in globals():
    CRS_SALIDA = ""
if "REMUESTREO_WARP" not in globals():
    REMUESTREO_WARP = "auto"
if "COMPRESION" not in globals():
    COMPRESION = "auto"
if "CALIDAD" not in globals():
    CALIDAD = 90
if "BLOCKSIZE" not in globals():
    BLOCKSIZE = 512
if "REMUESTREO" not in globals():
    REMUESTREO = "AVERAGE"
if "SOBRESCRIBIR" not in globals():
    SOBRESCRIBIR = False
if "CARGAR" not in globals():
    CARGAR = True
if "GRUPO" not in globals():
    GRUPO = "Ortos COG"

SIDECARS = (".msk", ".ovr", ".aux.xml", ".xml")
EXT_RASTER = (".tif", ".tiff", ".img", ".jp2", ".vrt", ".ecw", ".sid")


def _es_raster(ruta):
    low = ruta.lower()
    if any(low.endswith(s) for s in SIDECARS):
        return False
    return low.endswith(EXT_RASTER)


entradas = [r for r in (ENTRADA or []) if r and _es_raster(r)]
if not entradas:
    raise ValueError(
        "No hay rasteres de entrada. Elige capas cargadas, capas seleccionadas "
        "o una carpeta con *.tif.")

gdal.SetConfigOption("GDAL_TIFF_INTERNAL_MASK", "YES")
gdal.SetConfigOption("GDAL_NUM_THREADS", "ALL_CPUS")

# --------------------------------------------------------------------------
# CRS de salida
# --------------------------------------------------------------------------
crs_destino = (CRS_SALIDA or "").strip()
srs_destino = None
sufijo = ""
if crs_destino:
    srs_destino = osr.SpatialReference()
    if srs_destino.SetFromUserInput(crs_destino) != 0:
        raise ValueError("CRS de salida no reconocido: %s" % crs_destino)
    codigo = srs_destino.GetAuthorityCode(None)
    sufijo = "_" + (codigo if codigo else "reproj")
    print("Reproyectando a %s%s" % (crs_destino,
          " (geografico: el pixel deja de ser cuadrado en metros)"
          if srs_destino.IsGeographic() else ""))


def mismo_crs(ds):
    """True si el raster ya esta en el CRS de destino."""
    if srs_destino is None:
        return True
    wkt = ds.GetProjection()
    if not wkt:
        return False
    origen = osr.SpatialReference()
    origen.ImportFromWkt(wkt)
    return bool(origen.IsSame(srs_destino))


def elegir_compresion(ds):
    """JPEG solo si es seguro: 1 o 3 bandas Byte. En el resto, DEFLATE."""
    if COMPRESION and COMPRESION.lower() != "auto":
        return COMPRESION.upper()
    banda = ds.GetRasterBand(1)
    es_byte = banda.DataType == gdal.GDT_Byte
    if es_byte and ds.RasterCount in (1, 3):
        return "JPEG"
    return "DEFLATE"


def elegir_remuestreo_warp(ds):
    """Como interpolar al reproyectar: depende de si el dato es continuo."""
    if REMUESTREO_WARP and REMUESTREO_WARP.lower() != "auto":
        return REMUESTREO_WARP.lower()
    tipo = ds.GetRasterBand(1).DataType
    if tipo == gdal.GDT_Byte and ds.RasterCount in (1, 3):
        return "cubic"          # imagen: suaviza
    if tipo in (gdal.GDT_Float32, gdal.GDT_Float64):
        return "bilinear"       # DEM: continuo pero sin sobreoscilacion
    return "near"               # enteros: posible dato categorico


def opciones(ds, compresion):
    op = ["BLOCKSIZE=%d" % int(BLOCKSIZE),
          "OVERVIEWS=IGNORE_EXISTING",
          "RESAMPLING=%s" % str(REMUESTREO).upper(),
          "NUM_THREADS=ALL_CPUS",
          "BIGTIFF=IF_SAFER",
          "COMPRESS=%s" % compresion]
    if compresion == "JPEG":
        op.append("QUALITY=%d" % int(CALIDAD))
    elif compresion in ("DEFLATE", "LZW", "ZSTD"):
        tipo = ds.GetRasterBand(1).DataType
        # predictor 3 para coma flotante (DEM), 2 para enteros
        if tipo in (gdal.GDT_Float32, gdal.GDT_Float64):
            op.append("PREDICTOR=3")
        elif tipo != gdal.GDT_Byte:
            op.append("PREDICTOR=2")
    return op


def ya_es_cog(ruta):
    try:
        ds = gdal.Open(ruta)
        est = ds.GetMetadata("IMAGE_STRUCTURE")
        ok = est.get("LAYOUT") == "COG"
        ds = None
        return ok
    except Exception:
        return False


def convertir(src, dst):
    """Escribe el COG. Devuelve (compresion, reproyectado)."""
    ds = gdal.Open(src)
    compresion = elegir_compresion(ds)
    creacion = opciones(ds, compresion)
    n_bandas = ds.RasterCount
    es_byte = ds.GetRasterBand(1).DataType == gdal.GDT_Byte
    nodata = ds.GetRasterBand(1).GetNoDataValue()
    reproyectar = srs_destino is not None and not mismo_crs(ds)
    remuestreo = elegir_remuestreo_warp(ds)
    ds = None

    if not reproyectar:
        gdal.Translate(dst, src, format="COG", creationOptions=creacion)
        return compresion, False

    # Imagen Byte -> alfa temporal para no perder los bordes validos.
    # Otros tipos -> se propaga el nodata, que el warper respeta.
    usar_alfa = es_byte and n_bandas in (1, 3)
    vrt = "/vsimem/optimizar_cog_%d.vrt" % abs(hash(src))
    try:
        gdal.Warp(vrt, src, format="VRT", dstSRS=crs_destino,
                  resampleAlg=remuestreo, multithread=True,
                  dstAlpha=usar_alfa,
                  srcNodata=nodata if not usar_alfa else None,
                  dstNodata=nodata if not usar_alfa else None)
        if usar_alfa:
            bandas = list(range(1, n_bandas + 1))
            gdal.Translate(dst, vrt, format="COG", bandList=bandas,
                           maskBand=n_bandas + 1, creationOptions=creacion)
        else:
            gdal.Translate(dst, vrt, format="COG", creationOptions=creacion)
    finally:
        gdal.Unlink(vrt)
    return compresion, True


hechos, saltados, fallidos = [], [], []
mb_antes = mb_despues = 0.0

for src in entradas:
    nombre = os.path.basename(src)
    if not os.path.exists(src):
        fallidos.append((nombre, "no existe"))
        continue

    carpeta_salida = SALIDA.strip() if SALIDA else os.path.join(
        os.path.dirname(src), "cog")
    os.makedirs(carpeta_salida, exist_ok=True)
    dst = os.path.join(carpeta_salida,
                       os.path.splitext(nombre)[0] + sufijo + ".tif")

    if os.path.abspath(dst) == os.path.abspath(src):
        fallidos.append((nombre, "la salida pisaria el original"))
        continue
    if os.path.exists(dst) and not SOBRESCRIBIR:
        saltados.append((nombre, "ya existe la salida"))
        continue
    if ya_es_cog(src) and not sufijo and not SOBRESCRIBIR:
        saltados.append((nombre, "el origen ya es COG"))
        continue

    try:
        t0 = time.time()
        compresion, reproyectado = convertir(src, dst)
        seg = time.time() - t0

        antes = os.path.getsize(src) / 1e6
        despues = os.path.getsize(dst) / 1e6
        mb_antes += antes
        mb_despues += despues

        rev = gdal.Open(dst)
        b = rev.GetRasterBand(1)
        n_ovr = b.GetOverviewCount()
        bloque = b.GetBlockSize()
        rev = None

        hechos.append(dst)
        print("OK   %-45s %-7s %s %5.1fs %6.1f->%6.1f MB ovr=%d block=%dx%d"
              % (nombre[:45], compresion, "reproy" if reproyectado else "  =   ",
                 seg, antes, despues, n_ovr, bloque[0], bloque[1]))
    except Exception as e:
        fallidos.append((nombre, str(e)))
        print("FALLA %-45s %s" % (nombre[:45], e))

# --------------------------------------------------------------------------
print("")
print("Convertidos: %d   Saltados: %d   Fallidos: %d"
      % (len(hechos), len(saltados), len(fallidos)))
if hechos:
    print("Tamano total: %.1f MB -> %.1f MB" % (mb_antes, mb_despues))
for nombre, causa in saltados:
    print("  saltado: %-45s (%s)" % (nombre[:45], causa))
for nombre, causa in fallidos:
    print("  fallido: %-45s (%s)" % (nombre[:45], causa))

# --------------------------------------------------------------------------
if CARGAR and hechos:
    proyecto = QgsProject.instance()
    raiz = proyecto.layerTreeRoot()
    grupo = raiz.findGroup(GRUPO) or raiz.insertGroup(0, GRUPO)

    extension = None
    cargadas = 0
    for ruta in hechos:
        capa = QgsRasterLayer(ruta, os.path.splitext(os.path.basename(ruta))[0],
                              "gdal")
        if not capa.isValid():
            print("  no se pudo cargar:", ruta)
            continue
        proyecto.addMapLayer(capa, False)
        grupo.addLayer(capa)
        ext = capa.extent()
        if extension is None:
            extension = QgsRectangle(ext)
        else:
            extension.combineExtentWith(ext)
        cargadas += 1

    print("Cargadas en el grupo '%s': %d capas" % (GRUPO, cargadas))
    if extension is not None and "iface" in globals() and iface is not None:
        lienzo = iface.mapCanvas()
        lienzo.setExtent(extension)
        lienzo.refresh()
