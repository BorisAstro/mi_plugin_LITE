# -*- coding: utf-8 -*-
r"""Mi Plugin — lanzador de scripts con parámetros configurables por interfaz.

===========================================================================
 INYECCIÓN DE PARÁMETROS
 El plugin ejecuta tu script e inyecta como variables globales los valores
 elegidos en la interfaz, con los MISMOS nombres de variable del script.
 Envuelve tu configuración así para no pisar lo inyectado:

     if "DEM" not in globals():
         DEM = r"E:\ruta\por\defecto.tif"

 Siempre se inyecta además:
   iface            → interfaz de QGIS
   PLUGIN_PARAMS    → dict con todos los valores
   adoptar_nombre   → helper de convención de nombres (ver README):
                      adoptar_nombre("LANELET", capa_nueva, capa_original,
                                     proceso="migrate")
                      La capa NUEVA queda con el nombre base (reconocible por
                      aplicar_estilos.py) y la ORIGINAL se renombra
                      "LANELET_migrate". Sin sufijos en la capa de trabajo.
===========================================================================

 REGISTRO — EDITA AQUÍ. Tipos de parámetro:
   capa / capa_nombre / capa_ruta → combo de capas (objeto / nombre / ruta)
   archivo / archivos / archivo_salida / carpeta → selectores de rutas
   texto / lista_texto / entero / numero / bool / crs
   origen  → ENTRADA FLEXIBLE: el usuario elige entre
             [Todas las capas cargadas | Capas seleccionadas en el panel |
              Carpeta]. Inyecta:
               VAR         → list[str] rutas de archivo resueltas
               VAR_MODO    → "cargadas" | "seleccionadas" | "carpeta"
               VAR_CARPETA → carpeta elegida o None
             Clave opcional "patron": "*.geojson" (str o lista de patrones).
 Claves: var, tipo, etiqueta, default, filtro, filtro_capa, opcional, patron.
 "ruta" relativa (p. ej. "scripts/x.py") se resuelve dentro de la carpeta
 del plugin — así se distribuyen scripts con el propio ZIP.
===========================================================================
"""

REGISTRO = [
# ------------------------- CONVERSIÓN / 3D -------------------------------
{
 "grupo": "Conversión / 3D",
 "nombre": "shp_to_geojson_with_reference",
 "ruta": "scripts/shp_to_geojson_with_reference.py",
 "desc": "Convierte SHP a GeoJSON mapeando campos contra un GeoJSON de referencia. Si dejas la referencia vacia, busca en template/ la plantilla cuyo nombre case con el del SHP (CURBSTONE_3d.shp -> CURBSTONE.geojson). Las plantillas son 2D, asi que por defecto descarta la Z. "
         "Si el .prj del SHP da el error \"CRS cannot be converted to WKT1_GDAL\", "
         "fuerza el CRS de origen; el CRS de salida reproyecta (vacíos = automático).",
 "libs": ["geopandas", "pandas"],
 "params": [
   {"var": "shp_in", "tipo": "archivo", "etiqueta": "SHP de entrada", "filtro": "Shapefile (*.shp)"},
   {"var": "ref_geojson", "tipo": "archivo", "opcional": True,
    "filtro": "GeoJSON (*.geojson)",
    "etiqueta": "GeoJSON de referencia (vacio = plantilla segun el nombre del SHP)"},
   {"var": "APLANAR_2D", "tipo": "bool",
    "etiqueta": "Aplanar a 2D (descartar la Z del SHP)", "default": True},
   {"var": "CARPETA_TEMPLATES", "tipo": "carpeta", "opcional": True,
    "etiqueta": "Carpeta de plantillas (vacio = template/ del plugin)"},
   {"var": "out_geojson", "tipo": "archivo_salida", "etiqueta": "GeoJSON de salida", "filtro": "GeoJSON (*.geojson)"},
   {"var": "CRS_ORIGEN", "tipo": "crs", "opcional": True,
    "etiqueta": "CRS de origen (vacío = usar el .prj del SHP)"},
   {"var": "CRS_SALIDA", "tipo": "crs", "opcional": True,
    "etiqueta": "CRS de salida (vacío = mantener el de origen)"},
 ],
},
{
 "grupo": "Conversión / 3D",
 "nombre": "3dlayerto2d for labeling",
 "ruta": "scripts/layer3d_a_2d.py",
 "desc": ("Crea una capa 2D desde una capa 3D para etiquetar bien. Acepta "
          "punto, linea y poligono: los poligonos como traffic_light_box o "
          "traffic_sign_box se reducen a un punto representativo."),
 "libs": [],
 "params": [
   {"var": "capa", "tipo": "capa",
    "etiqueta": "Capa 3D de entrada (punto, linea o poligono)",
    "filtro_capa": "vector"},
   {"var": "SALIDA", "tipo": "opciones",
    "etiqueta": "Geometria de salida",
    "valores": ["punto", "misma geometria en 2D"], "default": "punto"},
   {"var": "METODO", "tipo": "opciones",
    "etiqueta": "Como reducir lineas y poligonos a punto",
    "valores": ["punto interior", "centroide"], "default": "punto interior"},
   {"var": "SOLO_SI_ORIGEN", "tipo": "texto", "opcional": True,
    "etiqueta": "Aplicar estilo/filtro solo si el origen contiene (vacio = siempre)",
    "default": "TRAFFIC_SIGN_BOX"},
   {"var": "ESTILO_DE", "tipo": "capa_nombre", "opcional": True,
    "filtro_capa": "vector",
    "etiqueta": "Copiar simbologia y etiquetas de esta capa"},
   {"var": "COPIAR_FILTRO", "tipo": "bool",
    "etiqueta": "  copiar tambien su filtro de capa", "default": True},
   {"var": "ESTILO_QML", "tipo": "archivo", "opcional": True,
    "etiqueta": "  o cargar un .qml", "filtro": "Estilo QGIS (*.qml)"},
   {"var": "FILTRO", "tipo": "texto", "opcional": True,
    "etiqueta": "Filtro de capa (deja vacio para no filtrar)",
    "default": ""},
   {"var": "ETIQUETA", "tipo": "texto", "opcional": True,
    "etiqueta": "Expresion de etiqueta (vacio = sin etiquetas)",
    "default": ""},
   {"var": "nombre_salida", "tipo": "texto", "etiqueta": "Nombre de salida (vacío = <capa>_2D)", "opcional": True},
 ],
},
# ------------------------------ LANELET ----------------------------------
{
 "grupo": "Lanelet",
 "nombre": "topologia",
 "ruta": "scripts/topologia.py",
 "desc": "Busca errores topologicos (gaps, endpoints sin snap, colgantes, solapes) y clasifica cada solape con un veredicto binario: DUPLICADO cuando los dos lanelets citan las MISMAS dos lineas de borde y la MISMA maniobra, y NO_DUPLICADO en cuanto difiere algo, con el campo 'motivo' indicando que senal delata la diferencia (left_line_id, right_line_id, turn_direction o una combinacion). TURNING_DOBLE marca el artefacto de creacion en que un lanelet tiene turning en sus dos lados. Salidas: topology_errors_points_4326 y topology_errors_lines_4326, ya simbolizadas. Tolerancias en metros en el CRS de trabajo (usa el UTM de tu zona: 32612 Phoenix, 32615 zona 15).",
 "libs": [],
 "params": [
   {"var": "LAYER_NAMES", "tipo": "capas_multi", "filtro_capa": "linea",
    "etiqueta": "Capas a revisar (marca una o varias)",
    "default": "LANELET"},
   {"var": "CAMPOS_EXTRA", "tipo": "lista_texto",
    "etiqueta": "Campos a copiar en la capa de solapes (prefijos src_ y oth_)",
    "default": "left_line_id, right_line_id, turn_direction"},
   {"var": "EXCLUIR_DICTAMEN", "tipo": "opciones_multi",
    "valores": ["DUPLICADO", "NO_DUPLICADO", "TURNING_DOBLE",
                "SIN_REFERENCIAS"],
    "default": "NO_DUPLICADO, TURNING_DOBLE",
    "etiqueta": "Excluir de la salida estos dictamenes (solo aplica a LANELET)"},
   {"var": "AGRUPAR_DUPLICADOS", "tipo": "bool",
    "etiqueta": "Agrupar los duplicados en una fila por grupo", "default": True},
   {"var": "ABRIR_TABLAS", "tipo": "bool",
    "etiqueta": "Abrir las dos tablas de atributos lado a lado", "default": True},
   {"var": "GRUPO_SALIDA", "tipo": "texto",
    "etiqueta": "Grupo donde dejar todas las capas resultantes",
    "default": "TOPOLOGIA"},
   {"var": "ANEXO_QC", "tipo": "bool",
    "etiqueta": "Anexo QC: remapeo, duplicados sobrantes y solapes de capas base",
    "default": False},
   {"var": "ANEXO_LANELET", "tipo": "capa_nombre", "filtro_capa": "vector",
    "etiqueta": "  Anexo: capa LANELET", "patron_nombre": "LANELET"},
   {"var": "ANEXO_REFERENCIABLES", "tipo": "capas_multi", "filtro_capa": "linea",
    "etiqueta": "  Anexo: capas referenciables (las cita el lanelet)",
    "default": "LANE_MARKER,VIRTUAL_LINE,TURNING_LINE"},
   {"var": "ANEXO_GEOMETRICAS", "tipo": "capas_multi", "filtro_capa": "linea",
    "etiqueta": "  Anexo: capas geometricas (nunca citadas)",
    "default": "CURBSTONE,ROAD_EDGE"},
   {"var": "ANEXO_ID_FIELD", "tipo": "texto", "etiqueta": "  Anexo: campo ID",
    "default": "id"},
   {"var": "ANEXO_TOL_LANELET", "tipo": "numero",
    "etiqueta": "  Anexo: distancia maxima lanelet-linea (m)", "default": 3.5},
   {"var": "ANEXO_EPS", "tipo": "numero",
    "etiqueta": "  Anexo: tolerancia de gemelas desplazadas (m)", "default": 0.19},
   {"var": "ANEXO_RATIO_DUP", "tipo": "numero",
    "etiqueta": "  Anexo: proporcion minima para considerar duplicado", "default": 0.95},
   {"var": "ANEXO_MIN_SOLAPE", "tipo": "numero",
    "etiqueta": "  Anexo: solape minimo para reportar (m)", "default": 0.10},
   {"var": "ANEXO_GRUPO", "tipo": "texto",
    "etiqueta": "  Anexo: grupo donde dejar sus capas", "default": "QC_ANEXO"},
   {"var": "WORK_CRS", "tipo": "crs", "etiqueta": "CRS de trabajo (métrico)", "default": "EPSG:32612"},
   {"var": "OUTPUT_CRS", "tipo": "crs", "etiqueta": "CRS de salida", "default": "EPSG:4326"},
 ],
},
{
 "grupo": "Lanelet",
 "nombre": "lanelet_val (val + QC fusionados)",
 "ruta": "scripts/lanelet_val.py",
 "desc": "Validación/QC de LANELET: busca left/right_line_id en LANE_MARKER, "
         "VIRTUAL_LINE y TURNING_LINE, mide distancias y clasifica OK / LEFT_FAIL / "
         "RIGHT_FAIL / BOTH_FAIL. Salida: capa 'lanelet_validacion' con simbología "
         "por estado. Tolerancias en unidades del CRS de la capa LANELET.",
 "libs": [],
 "params": [
   {"var": "nombre_lanelet", "tipo": "capa_nombre", "etiqueta": "Capa LANELET", "filtro_capa": "vector"},
   {"var": "nombre_lane_marker", "tipo": "capa_nombre", "etiqueta": "Capa LANE_MARKER", "filtro_capa": "vector"},
   {"var": "nombre_virtual_line", "tipo": "capa_nombre", "etiqueta": "Capa VIRTUAL_LINE", "filtro_capa": "vector"},
   {"var": "nombre_turning_line", "tipo": "capa_nombre", "etiqueta": "Capa TURNING_LINE", "filtro_capa": "vector"},
   {"var": "BUFFER_DIST", "tipo": "numero", "etiqueta": "Buffer de verificación", "default": 2.0},
   {"var": "DIST_TOLERANCE", "tipo": "numero", "etiqueta": "Distancia máxima correcta", "default": 2.0},
   {"var": "GROSOR_MM", "tipo": "numero",
    "etiqueta": "Grosor de linea en mm", "default": 1.6},
   {"var": "SOLO_FALLAS", "tipo": "bool",
    "etiqueta": "Dejar en la capa solo las fallas (ocultar los OK)", "default": True},
   {"var": "OUTPUT_TXT", "tipo": "archivo_salida", "opcional": True,
    "etiqueta": "Reporte TXT (vacío = junto al archivo LANELET)", "filtro": "Texto (*.txt)"},
 ],
},
# -------------------------- UTILIDADES / IDS -----------------------------
{
 "grupo": "Lanelet",
 "nombre": "cortefinal consolidado2",
 "ruta": "scripts/cortefinal_consolidado2.py",
 "desc": "De la carpeta BASE toma VIRTUAL_LINE, LANE_MARKER, CURBSTONE y CUT_LINE "
         "(.geojson); corta, corrige y crea campos de longitud (astillas). Cada "
         "resultado CONSERVA el nombre original y el archivo previo se copia a "
         "<base>_corte.geojson. Nota: en el script usa BASE = Path(BASE).",
 "libs": ["geopandas", "shapely"],
 "params": [
   {"var": "BASE", "tipo": "carpeta", "etiqueta": "Carpeta BASE con los GeoJSON"},
   {"var": "UTM_EPSG", "tipo": "entero", "etiqueta": "EPSG métrico (UTM)", "default": 32612},
   {"var": "SNAP_TOL", "tipo": "numero", "etiqueta": "Tolerancia de snap (m)", "default": 0.005},
   {"var": "SMALL_LEN", "tipo": "numero", "etiqueta": "Longitud mínima astilla (m)", "default": 0.05},
   {"var": "EXTEND_LEN", "tipo": "numero", "etiqueta": "Extensión de líneas (m)", "default": 0.01},
   {"var": "MERGE_TOL", "tipo": "numero", "etiqueta": "Tolerancia de merge (m)", "default": 0.05},
 ],
},
{
 "grupo": "Utilidades / IDs",
 "nombre": "reportetxt_ids",
 "ruta": "scripts/reportetxt_ids.py",
 "desc": "Modo 'reporte': TXT con entidades, nulos, duplicados, rango y lista de ids por capa. Modo 'comparar': cruza dos reportes ya generados y detecta ids repetidos entre ellos, por capa homonima y en el conjunto global. En modo comparar puedes indicar dos GRUPOS del panel y los reportes se generan solos en la carpeta de salida. El TXT lista todos los ids repetidos, sin recortar.",
 "libs": [],
 "params": [
   {"var": "MODO", "tipo": "opciones", "valores": ["reporte", "comparar"],
    "default": "reporte", "etiqueta": "Modo"},
   {"var": "ENTRADAS", "tipo": "origen", "opcional": True,
    "etiqueta": "Origen de capas (modo reporte)", "patron": "*.geojson"},
   {"var": "ID_FIELD", "tipo": "texto", "etiqueta": "Campo ID", "default": "id"},
   {"var": "INCLUIR_IDS", "tipo": "bool",
    "etiqueta": "Incluir la lista de ids (necesaria para comparar de forma exacta)",
    "default": True},
   {"var": "GRUPO_A", "tipo": "texto", "opcional": True, "default": "",
    "etiqueta": "Comparar: grupo A del panel (genera su reporte solo)"},
   {"var": "GRUPO_B", "tipo": "texto", "opcional": True, "default": "",
    "etiqueta": "Comparar: grupo B del panel"},
   {"var": "REPORTE_A", "tipo": "archivo", "opcional": True,
    "filtro": "Texto (*.txt)",
    "etiqueta": "…o reporte A ya generado"},
   {"var": "REPORTE_B", "tipo": "archivo", "opcional": True,
    "filtro": "Texto (*.txt)", "etiqueta": "…o reporte B ya generado"},
   {"var": "OUTPUT_TXT", "tipo": "archivo_salida",
    "etiqueta": "Salida TXT", "filtro": "Texto (*.txt)"},
 ],
},
{
 "grupo": "Utilidades / IDs",
 "nombre": "removepath",
 "ruta": "scripts/removepath.py",
 "desc": "Quita del lienzo todas las capas cuyo origen esté dentro de la carpeta indicada.",
 "libs": [],
 "params": [
   {"var": "root_folder", "tipo": "carpeta", "etiqueta": "Carpeta raíz"},
 ],
},
{
 "grupo": "Utilidades / IDs",
 "nombre": "rutasgeojson",
 "ruta": "scripts/rutasgeojson.py",
 "desc": "Imprime en la consola de QGIS las rutas de los GeoJSON del origen elegido.",
 "libs": [],
 "params": [
   {"var": "ENTRADAS", "tipo": "origen", "etiqueta": "Origen de capas", "patron": "*.geojson"},
 ],
},
{
 "grupo": "Lanelet",
 "nombre": "revisarids duplicados (por campo + AND)",
 "ruta": "scripts/revisarids_duplicados.py",
 "desc": "Duplicados y nulos en la capa elegida (archivo o temporal): por cada "
         "campo marcado en el desplegable Y por combinación (AND) de todos — "
         "solo la combinación repetida (ej. id AND right_line_id AND "
         "left_line_id) delata segmentos realmente duplicados. Lista los IDs "
         "para corrección manual y guarda reporte TXT.",
 "libs": [],
 "params": [
   {"var": "capa", "tipo": "capa", "etiqueta": "Capa a revisar", "filtro_capa": "vector"},
   {"var": "CAMPOS", "tipo": "campos", "de_capa": "capa",
    "etiqueta": "Campos de interés (AND)",
    "default": ["id", "right_line_id", "left_line_id"]},
   {"var": "ID_FIELD", "tipo": "texto", "etiqueta": "Campo ID a listar para corrección",
    "default": "id"},
   {"var": "MAX_LISTA", "tipo": "entero", "etiqueta": "Máx. filas por sección", "default": 20},
   {"var": "OUTPUT_TXT", "tipo": "archivo_salida", "opcional": True,
    "etiqueta": "Reporte TXT (vacío = junto al archivo de la capa)",
    "filtro": "Texto (*.txt)"},
 ],
},
{
 "grupo": "Utilidades / IDs",
 "nombre": "rellenoID_2",
 "ruta": "scripts/rellenoid.py",
 "desc": "Rellena IDs nulos de una capa O de todo un grupo. Si la capa ya tiene "
         "IDs, continúa desde el último; si están TODOS vacíos, arranca desde la "
         "tabla template/idslayers.csv según el nombre base de la capa.",
 "libs": [],
 "params": [
   {"var": "capa", "tipo": "capa", "etiqueta": "Capa a actualizar (o usa un grupo)",
    "filtro_capa": "vector", "opcional": True},
   {"var": "GRUPO", "tipo": "texto", "opcional": True,
    "etiqueta": "Grupo del panel (procesa todas sus capas; deja capa vacía)"},
   {"var": "ID_FIELD", "tipo": "texto", "etiqueta": "Campo ID", "default": "id"},
   {"var": "INCREMENT", "tipo": "entero", "etiqueta": "Incremento", "default": 1},
   {"var": "CSV_PATH", "tipo": "archivo", "opcional": True,
    "etiqueta": "Tabla de IDs (vacío = template/idslayers.csv del plugin)",
    "filtro": "CSV (*.csv)"},
 ],
},
{
 "grupo": "Utilidades / IDs",
 "nombre": "streetview2",
 "ruta": "scripts/streetview2.py",
 "desc": "Clic en el lienzo → abre Street View del punto en el navegador.",
 "libs": [],
 "params": [],
},
{
 "grupo": "Utilidades / IDs",
 "nombre": "converttogs84",
 "ruta": "scripts/convertir_crs.py",
 "desc": "Convierte masivamente de UTM a WGS84 los archivos del origen elegido "
         "(salida en subcarpeta CRS4326). CRS llegan como texto EPSG.",
 "libs": [],
 "params": [
   {"var": "ENTRADAS", "tipo": "origen", "etiqueta": "Origen de archivos",
    "patron": ["*.geojson", "*.shp", "*.gpkg"]},
   {"var": "crs_src", "tipo": "crs", "etiqueta": "CRS de origen", "default": "EPSG:32614"},
   {"var": "crs_dst", "tipo": "crs", "etiqueta": "CRS de destino", "default": "EPSG:4326"},
 ],
},
{
 "grupo": "Utilidades / IDs",
 "nombre": "offset2",
 "ruta": "scripts/offset2.py",
 "desc": "Offsets de los segmentos SELECCIONADOS de la CAPA ACTIVA usando CRS "
         "proyectado (metros). Los resultados se ACUMULAN en un GeoPackage fijo "
         "en la carpeta temporal (offsets_acumulados.gpkg) entre ejecuciones.",
 "libs": [],
 "params": [
   {"var": "distancia", "tipo": "numero", "etiqueta": "Distancia de offset (m)", "default": 0.5},
   {"var": "UTM_EPSG", "tipo": "entero", "etiqueta": "EPSG métrico", "default": 32612},
 ],
},
{
 "grupo": "Utilidades / IDs",
 "nombre": "DISTANCIAS",
 "ruta": "scripts/distancias.py",
 "desc": "Capa con campos id/meters/miles calculados en coordenadas planas, salida "
         "EPSG:4326 GUARDADA en .geojson. Convención de nombres: la capa nueva "
         "adopta el nombre base y la original se renombra <base>_distancias "
         "(si el archivo chocara, el original se rota y el lienzo se actualiza).",
 "libs": [],
 "params": [
   {"var": "LAYER_NAME", "tipo": "capa_nombre", "etiqueta": "Capa de entrada", "filtro_capa": "vector"},
   {"var": "FIELD_ID", "tipo": "texto", "etiqueta": "Campo ID", "default": "id"},
   {"var": "UTM_EPSG", "tipo": "entero", "etiqueta": "EPSG métrico para el cálculo", "default": 32612},
   {"var": "CARPETA_SALIDA", "tipo": "carpeta", "opcional": True,
    "etiqueta": "Carpeta de salida (vacío = la del archivo original; obligatoria para capas temporales)"},
 ],
},
{
 "grupo": "Utilidades / IDs",
 "nombre": "aplicar_estilos",
 "ruta": "scripts/aplicar_estilos.py",
 "desc": "Aplica estilos QML/SLD a las capas del lienzo por nombre base "
         "(ignora sufijo _numeros, mayúsculas y prefijo 'estilo_').",
 "libs": [],
 "params": [
   {"var": "carpeta_estilos", "tipo": "carpeta",
    "etiqueta": "Carpeta de estilos", "default": r"E:\phoenix", "opcional": True},
   {"var": "GRUPO", "tipo": "texto", "opcional": True,
    "etiqueta": "Aplicar solo a este grupo (vacio = todo el proyecto)"},
   {"var": "SOLO_SELECCIONADAS", "tipo": "bool",
    "etiqueta": "Aplicar solo a las capas resaltadas en el panel",
    "default": False},
 ],
},
{
 "grupo": "Ráster / COG",
 "nombre": "optimizar_cog",
 "ruta": "scripts/optimizar_cog.py",
 "desc": "Convierte rásteres a Cloud Optimized GeoTIFF: teselado 512, pirámides internas "
         "y máscara integrada. Arregla los rásteres organizados en tiras (block = ancho "
         "completo) que van lentos al hacer zoom. Compresión automática: JPEG/YCbCr para "
         "ortos RGB de 8 bits, DEFLATE con predictor para DEM. Opcionalmente reproyecta (conserva la máscara de validez, sin bordes negros) y añade el código EPSG al nombre. No toca los originales.",
 "libs": [],
 "params": [
   {"var": "ENTRADA", "tipo": "origen", "etiqueta": "Rásteres a optimizar",
    "patron": ["*.tif", "*.tiff"]},
   {"var": "SALIDA", "tipo": "carpeta", "opcional": True,
    "etiqueta": "Carpeta de salida (vacío = subcarpeta 'cog' junto a cada archivo)"},
   {"var": "CRS_SALIDA", "tipo": "crs", "opcional": True,
    "etiqueta": "Reproyectar a (vacío = mantener el CRS original)"},
   {"var": "REMUESTREO_WARP", "tipo": "texto",
    "etiqueta": "Remuestreo al reproyectar (auto | cubic | bilinear | near | lanczos)",
    "default": "auto"},
   {"var": "COMPRESION", "tipo": "texto", "etiqueta": "Compresión (auto | JPEG | DEFLATE | LZW | ZSTD)",
    "default": "auto"},
   {"var": "CALIDAD", "tipo": "entero", "etiqueta": "Calidad JPEG (1-100)", "default": 90},
   {"var": "BLOCKSIZE", "tipo": "entero", "etiqueta": "Tamaño de tesela", "default": 512},
   {"var": "REMUESTREO", "tipo": "texto",
    "etiqueta": "Remuestreo de pirámides (AVERAGE | NEAREST | CUBIC | MODE)",
    "default": "AVERAGE"},
   {"var": "SOBRESCRIBIR", "tipo": "bool",
    "etiqueta": "Rehacer aunque ya exista la salida", "default": False},
   {"var": "CARGAR", "tipo": "bool", "etiqueta": "Cargar el resultado en el proyecto",
    "default": True},
   {"var": "GRUPO", "tipo": "texto", "etiqueta": "Grupo de capas donde cargar",
    "default": "Ortos COG"},
 ],
},
{
 "grupo": "Lanelet",
 "nombre": "driveway (virtual line + lanelet, 3 clics)",
 "ruta": "scripts/driveway_virtual.py",
 "desc": ("Crea las VIRTUAL_LINE de un driveway y sus LANELET a partir de 3 clics: "
          "inicio y fin del borde DERECHO de entrada, mas el borde opuesto. Si el "
          "ancho total supera el umbral genera 3 virtual lines y 2 lanelets "
          "(one_way=yes); si no, 2 virtual lines y 1 lanelet (one_way=no). Cada "
          "linea se digitaliza en el sentido del lanelet para el que es la derecha."),
 "libs": [],
 "params": [
   {"var": "CAPA_VIRTUAL", "tipo": "capa_nombre", "filtro_capa": "linea",
    "etiqueta": "Capa VIRTUAL_LINE", "patron_nombre": "VIRTUAL"},
   {"var": "CAPA_LANELET", "tipo": "capa_nombre", "filtro_capa": "linea",
    "etiqueta": "Capa LANELET", "patron_nombre": "LANELET"},
   {"var": "UMBRAL_ANCHO", "tipo": "numero",
    "etiqueta": "Ancho total a partir del cual son dos carriles (m)", "default": 6.0},
   {"var": "REFERENCIA", "tipo": "opciones",
    "etiqueta": "Que marcan los dos primeros clics",
    "valores": ["borde derecho", "eje central del driveway"],
    "default": "borde derecho"},
   {"var": "SENTIDO_CENTRAL", "tipo": "opciones",
    "etiqueta": "Sentido de la virtual line central",
    "valores": ["entrada", "salida"], "default": "entrada"},
   {"var": "PASO_ID", "tipo": "entero", "etiqueta": "Paso entre ids", "default": 2},
   {"var": "DW_SPEED", "tipo": "texto",
    "etiqueta": "lanelet: speed_limit", "default": "15mph"},
   {"var": "DW_PARTICIPANT", "tipo": "texto",
    "etiqueta": "lanelet: participant", "default": "all-vehicles"},
   {"var": "DW_SURFACE", "tipo": "texto",
    "etiqueta": "lanelet: surface", "default": "asphalt"},
   {"var": "DW_SUBTYPE", "tipo": "texto",
    "etiqueta": "lanelet: subtype", "default": "road"},
   {"var": "DW_TURN", "tipo": "texto",
    "etiqueta": "lanelet: turn_direction", "default": "straight"},
   {"var": "DW_FUNCTION", "tipo": "texto", "opcional": True,
    "etiqueta": "lanelet: function (vacio = NULL, como tus driveways)", "default": ""},
   {"var": "DW_CREATOR", "tipo": "texto", "etiqueta": "creator", "default": "BO_46"},
   {"var": "AVISO_DESDE", "tipo": "numero",
    "etiqueta": "Avisar si el ancho esta entre (m)", "default": 6.0},
   {"var": "AVISO_HASTA", "tipo": "numero", "etiqueta": "  y (m)", "default": 7.0},
   {"var": "TECLA_GENERAR", "tipo": "texto",
    "etiqueta": "Tecla para escribir el driveway completo",
    "default": "Shift+F11"},
   {"var": "TECLA_UNA_VIA", "tipo": "texto",
    "etiqueta": "Tecla para escribir SOLO la entrada (un carril)",
    "default": "Shift+F12"},
   {"var": "COMMIT", "tipo": "bool",
    "etiqueta": "Guardar en disco al escribir", "default": True},
   {"var": "DESACTIVAR", "tipo": "bool",
    "etiqueta": "Desactivar y liberar el atajo", "default": False},
 ],
},
{
 "grupo": "Lanelet",
 "nombre": "spline_giros (atajos F7/F8/Enter)",
 "ruta": "scripts/spline_giros.py",
 "desc": "Dibuja lineas de giro en VIRTUAL_LINE con atajos de teclado. F8 captura los extremos de ENTRADA arrastrando un rectangulo en el lienzo, F9 los de SALIDA, F10 genera. Las teclas son configurables y avisa si chocan con un atajo de QGIS. Los extremos coincidentes (donde una linea termina y empieza la siguiente) se agrupan en un solo nodo, y si sobran se toman los dos mas separados: los bordes del carril. Une izquierda con izquierda y derecha con derecha mediante un BIARCO (dos arcos circulares con tangente comun), tomando la tangente de la linea a la que pertenece cada vertice para que empalme sin quiebre. Solo asigna el id, correlativo continuando el bloque bajo; no toca ningun otro campo.",
 "libs": [],
 "params": [
   {"var": "CAPA_DESTINO", "tipo": "capa_nombre", "filtro_capa": "linea",
    "etiqueta": "Capa destino donde crear las lineas"},
   {"var": "CAPAS_FUENTE", "tipo": "lista_texto",
    "etiqueta": "Capas de las que capturar extremos",
    "default": "LANE_MARKER,VIRTUAL_LINE"},
   {"var": "ESPACIADO", "tipo": "numero",
    "etiqueta": "Espaciado entre vertices (m)", "default": 0.89},
   {"var": "PASO_ID", "tipo": "entero",
    "etiqueta": "Incremento de id (continua el bloque bajo)", "default": 2},
   {"var": "TOL_NODO", "tipo": "numero",
    "etiqueta": "Tolerancia para unir extremos coincidentes en un nodo (m)",
    "default": 0.10},
   {"var": "RADIO_MIN", "tipo": "numero",
    "etiqueta": "Radio minimo de giro a avisar (m, 0 = sin aviso)",
    "default": 0.0},
   {"var": "TECLA_ENTRADA", "tipo": "texto",
    "etiqueta": "Tecla: capturar ENTRADA", "default": "F8"},
   {"var": "TECLA_SALIDA", "tipo": "texto",
    "etiqueta": "Tecla: capturar SALIDA", "default": "F9"},
   {"var": "TECLA_GENERAR", "tipo": "texto",
    "etiqueta": "Tecla: generar las lineas", "default": "F10"},
   {"var": "COMMIT", "tipo": "bool",
    "etiqueta": "Guardar en disco al generar (si no, acumula en capa temporal)",
    "default": True},
   {"var": "CREAR_GIRO", "tipo": "bool",
    "etiqueta": "Crear tambien TURNING_LINE recta + su LANELET", "default": False},
   {"var": "CAPA_TURNING", "tipo": "capa_nombre", "filtro_capa": "linea",
    "etiqueta": "  Capa TURNING_LINE", "patron_nombre": "TURNING"},
   {"var": "CAPA_LANELET", "tipo": "capa_nombre", "filtro_capa": "linea",
    "etiqueta": "  Capa LANELET", "patron_nombre": "LANELET"},
   {"var": "UMBRAL_RECTO", "tipo": "numero",
    "etiqueta": "  Angulo minimo para no llamarlo 'straight' (grados)",
    "default": 20.0},
   {"var": "LL_PARTICIPANT", "tipo": "texto",
    "etiqueta": "  lanelet: participant", "default": "all-vehicles"},
   {"var": "LL_SURFACE", "tipo": "texto",
    "etiqueta": "  lanelet: surface", "default": "asphalt"},
   {"var": "LL_ONE_WAY", "tipo": "texto",
    "etiqueta": "  lanelet: one_way", "default": "yes"},
   {"var": "LL_SUBTYPE", "tipo": "texto",
    "etiqueta": "  lanelet: subtype", "default": "road"},
   {"var": "LL_FUNCTION", "tipo": "texto",
    "etiqueta": "  lanelet: function", "default": "turn"},
   {"var": "LL_SPEED", "tipo": "texto",
    "etiqueta": "  lanelet: speed_limit", "default": "10mph"},
   {"var": "GIRO_CREATOR", "tipo": "texto",
    "etiqueta": "  creator para turning y lanelet", "default": "BO_46"},
   {"var": "DESACTIVAR", "tipo": "bool",
    "etiqueta": "Desactivar la herramienta y liberar los atajos",
    "default": False},
 ],
},
{
 "grupo": "Lanelet",
 "nombre": "asociar relaciones 1:n / n:1 (F2/F4)",
 "ruta": "scripts/asociar_stopline_lanelet.py",
 "desc": "Enlaza dos capas segun la tabla de asociaciones 1:n (stop_line->traffic_light_pole, stop_line->lanelet, traffic_light_pole->traffic_light_box, traffic_sign_pole->traffic_sign_box, traffic_light_box->traffic_light_bulb, traffic_light_box->lanelet), mas las inversas n:1 hacia stop_line y hacia los postes. La cardinalidad la dicta la regla: 1:n escribe lista separada por comas, n:1 exige una unica seleccion. escribiendo los ids separados por comas en el campo lane_id. F2 confirma el stop line seleccionado y preselecciona los lanelet que lo tocan dentro de la tolerancia; ajustas la seleccion a mano y F4 escribe. Trabaja sobre la capa fisica dentro de un comando de edicion, asi que Ctrl+Z lo deshace y Ctrl+S lo guarda.",
 "libs": [],
 "params": [
   {"var": "CAPA_STOPLINE", "tipo": "capa_nombre",
    "patron_nombre": r"(?i)^(STOP_LINE|TRAFFIC_LIGHT_POLE|TRAFFIC_SIGN_POLE|TRAFFIC_LIGHT_BOX|TRAFFIC_SIGN_BOX)",
    "etiqueta": "Capa ORIGEN (donde se escribe el campo)"},
   {"var": "CAPA_LANELET", "tipo": "capa_nombre",
    "patron_nombre": r"(?i)^(STOP_LINE|TRAFFIC_LIGHT_POLE|TRAFFIC_SIGN_POLE|LANELET|TRAFFIC_LIGHT_BOX|TRAFFIC_SIGN_BOX|TRAFFIC_LIGHT_BULB)",
    "etiqueta": "Capa DESTINO (aporta los ids)"},
   {"var": "CAMPO_DESTINO", "tipo": "texto", "opcional": True, "default": "",
    "etiqueta": "Campo donde escribir (vacio = el que dicta la regla)"},
   {"var": "CAMPO_ID_LANELET", "tipo": "texto",
    "etiqueta": "Campo id en la capa DESTINO", "default": "id"},
   {"var": "TOLERANCIA", "tipo": "numero",
    "etiqueta": "Tolerancia de contacto para preseleccionar (m, solo lineas)", "default": 0.50},
   {"var": "AUTOSELECCION", "tipo": "bool",
    "etiqueta": "Preseleccionar por contacto (solo entre capas de linea)",
    "default": True},
   {"var": "ANEXAR", "tipo": "bool",
    "etiqueta": "Anexar a los ids existentes (si no, reemplaza)",
    "default": False},
   {"var": "ORDENAR", "tipo": "bool",
    "etiqueta": "Ordenar los ids numericamente", "default": True},
   {"var": "GUARDAR_DIRECTO", "tipo": "bool",
    "etiqueta": "Guardar en disco al escribir (desactivado: Ctrl+Z disponible)",
    "default": False},
   {"var": "TECLA_STOPLINE", "tipo": "texto",
    "etiqueta": "Tecla: confirmar el objeto ORIGEN", "default": "F2"},
   {"var": "TECLA_ESCRIBIR", "tipo": "texto",
    "etiqueta": "Tecla: escribir los ids", "default": "F4"},
   {"var": "ESCRIBIR_INVERSO", "tipo": "bool",
    "etiqueta": "Escribir tambien el lado inverso (mantiene ambos sincronizados)",
    "default": True},
   {"var": "MOSTRAR_PROGRESO", "tipo": "bool",
    "etiqueta": "Capas temporales de progreso (asociado / pendiente)",
    "default": True},
   {"var": "GRUPO_PROGRESO", "tipo": "texto",
    "etiqueta": "Grupo donde dejarlas", "default": "ASOCIACION"},
   {"var": "REFRESCAR_TODO", "tipo": "bool",
    "etiqueta": "Al activar, refrescar TODAS las relaciones (no solo la elegida)",
    "default": True},
   {"var": "INCLUIR_DESTINO", "tipo": "bool",
    "etiqueta": "Incluir capa de destinos sin asociar", "default": True},
   {"var": "CAMBIAR_CAPA_ACTIVA", "tipo": "bool",
    "etiqueta": "Cambiar sola la capa activa: origen antes de F2, destino antes de F4",
    "default": True},
   {"var": "ACTIVAR_HERRAMIENTA_SEL", "tipo": "bool",
    "etiqueta": "  y activar la herramienta de seleccion", "default": True},
   {"var": "SIMBOLO_HUECO", "tipo": "bool",
    "etiqueta": "Simbolos huecos en puntos y poligonos (no tapan la entidad)",
    "default": True},
   {"var": "GROSOR_CONTORNO", "tipo": "numero",
    "etiqueta": "Grosor del contorno en mm", "default": 0.6},
   {"var": "MAX_DESTINOS", "tipo": "entero",
    "etiqueta": "Limite de destinos para dibujar los faltantes", "default": 2000},
   {"var": "DESACTIVAR", "tipo": "bool",
    "etiqueta": "Desactivar y liberar los atajos", "default": False},
 ],
},
{
 "grupo": "Utilidades / IDs",
 "nombre": "street_view_captura (F11)",
 "ruta": "scripts/street_view_captura.py",
 "desc": "Registra observaciones de Street View en un GeoPackage. Copias la URL en el navegador (Ctrl+L, Ctrl+C), pulsas el atajo en QGIS, y tras una cuenta atras captura la pantalla y anade dos entidades: el punto de la CAMARA y el RAYO de vision en la direccion del heading. De la URL saca lat/lon, heading, pitch, fov y panoid. Tras capturar muestra la imagen y pide code, tipo_layer, type y focos, de modo que rellenas con la foto delante y sin volver a Street View. Las coordenadas son las del vehiculo de Street View, no las del objeto: cruzando dos rayos de dos capturas distintas obtienes la posicion real del elemento.",
 "libs": [],
 "params": [
   {"var": "SALIDA", "tipo": "texto",
    "etiqueta": "Salida: 'temporal' (capa en memoria) o 'gpkg'",
    "default": "temporal"},
   {"var": "GPKG", "tipo": "archivo_salida", "opcional": True,
    "filtro": "GeoPackage (*.gpkg)",
    "etiqueta": "GeoPackage (solo si salida = gpkg; se crea si no existe)"},
   {"var": "NOMBRE_CAPA", "tipo": "texto",
    "etiqueta": "Nombre de la capa (los rayos van a <nombre>_rayos)",
    "default": "sv_observaciones"},
   {"var": "CARPETA_IMAGENES", "tipo": "carpeta",
    "etiqueta": "Carpeta para las capturas de pantalla"},
   {"var": "TIPO_LAYER", "tipo": "texto",
    "etiqueta": "tipo_layer (traffic_light / traffic_sign)",
    "default": "traffic_light"},
   {"var": "DIALOGO", "tipo": "bool",
    "etiqueta": "Pedir code / type / focos con vista previa tras capturar",
    "default": True},
   {"var": "ANCHO_PREVIA", "tipo": "entero",
    "etiqueta": "Ancho de la vista previa (px)", "default": 720},
   {"var": "LARGO_RAYO", "tipo": "numero",
    "etiqueta": "Largo del rayo de vision (m)", "default": 30.0},
   {"var": "CAPTURAR_PANTALLA", "tipo": "bool",
    "etiqueta": "Capturar la pantalla", "default": True},
   {"var": "VENTANA", "tipo": "texto",
    "etiqueta": "Titulo de la ventana a capturar (vacio = pantalla completa)",
    "default": "Google Maps"},
   {"var": "ESPERA", "tipo": "entero",
    "etiqueta": "Segundos de espera (0 si se captura por titulo de ventana)", "default": 0},
   {"var": "TECLA", "tipo": "texto", "etiqueta": "Tecla de captura",
    "default": "Ctrl+F2"},
   {"var": "ZOOM_AL_PUNTO", "tipo": "bool",
    "etiqueta": "Centrar el lienzo en el punto si queda fuera de vista",
    "default": True},
   {"var": "CARGAR", "tipo": "bool",
    "etiqueta": "Cargar las capas del GeoPackage en el proyecto", "default": True},
   {"var": "DESACTIVAR", "tipo": "bool",
    "etiqueta": "Desactivar y liberar el atajo", "default": False},
 ],
},
]

# pip: nombre de import → paquete pip
PIP_NOMBRES = {"psycopg2": "psycopg2-binary"}

# ===========================================================================

import fnmatch
import glob
import importlib
import os
import runpy
import shutil
import subprocess
import sys
import traceback

from qgis.PyQt.QtCore import Qt
from qgis.PyQt.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QFormLayout, QTabWidget, QWidget,
    QPushButton, QLabel, QListWidget, QListWidgetItem, QLineEdit,
    QSpinBox, QDoubleSpinBox, QCheckBox, QComboBox, QSplitter, QScrollArea,
    QFileDialog,
)
from qgis.core import (
    Qgis, QgsMessageLog, QgsCoordinateReferenceSystem, QgsProject,
    QgsVectorLayer,
)
from qgis.gui import (QgsMapLayerComboBox, QgsFileWidget,
                      QgsProjectionSelectionWidget, QgsCheckableComboBox)

DIR_PLUGIN = os.path.dirname(__file__)

FILTROS_CAPA = {
    "vector": Qgis.LayerFilter.VectorLayer,
    "raster": Qgis.LayerFilter.RasterLayer,
    "punto": Qgis.LayerFilter.PointLayer,
    "linea": Qgis.LayerFilter.LineLayer,
    "poligono": Qgis.LayerFilter.PolygonLayer,
}

MODOS_ORIGEN = ["Todas las capas cargadas", "Capas seleccionadas en el panel", "Carpeta"]
CLAVES_MODO = ["cargadas", "seleccionadas", "carpeta"]


def resolver_ruta(ruta):
    """Rutas relativas se resuelven dentro de la carpeta del plugin."""
    return ruta if os.path.isabs(ruta) else os.path.join(DIR_PLUGIN, ruta)


def adoptar_nombre(nombre_base, capa_nueva, capa_original=None, proceso="original"):
    """Convención de nombres: la capa GENERADA adopta el nombre base (LANELET,
    VIRTUAL_LINE, ...) para que otros procesos la reconozcan; la ORIGINAL se
    renombra '<base>_<proceso>'. Evita sufijos y backups."""
    if capa_original is not None:
        capa_original.setName(f"{nombre_base}_{proceso}")
    capa_nueva.setName(nombre_base)
    return capa_nueva


def crear_widget(spec):
    """Crea el widget para un parámetro. Devuelve (widget, funcion_valor)."""
    tipo = spec["tipo"]
    default = spec.get("default")

    if tipo in ("capa", "capa_nombre", "capa_ruta"):
        w = QgsMapLayerComboBox()
        f = spec.get("filtro_capa")
        if f in FILTROS_CAPA:
            w.setFilters(FILTROS_CAPA[f])
        # "patron_nombre": expresion regular; solo se ofrecen las capas cuyo
        # nombre encaje. Sirve para que un desplegable no liste capas que el
        # script no sabe tratar.
        pat = spec.get("patron_nombre")
        if pat:
            import re as _re
            try:
                _rx = _re.compile(pat, _re.IGNORECASE)
                _fuera = [l for l in QgsProject.instance().mapLayers().values()
                          if not _rx.search(l.name())]
                w.setExceptedLayerList(_fuera)
            except _re.error:
                pass
        if spec.get("opcional"):
            w.setAllowEmptyLayer(True)
            w.setCurrentIndex(0)
        if tipo == "capa":
            return w, lambda: w.currentLayer()
        if tipo == "capa_nombre":
            return w, lambda: w.currentLayer().name() if w.currentLayer() else None
        return w, lambda: w.currentLayer().source().split("|")[0] if w.currentLayer() else None

    if tipo in ("archivo", "archivo_salida", "carpeta", "archivos"):
        w = QgsFileWidget()
        modos = {
            "archivo": QgsFileWidget.StorageMode.GetFile,
            "archivo_salida": QgsFileWidget.StorageMode.SaveFile,
            "carpeta": QgsFileWidget.StorageMode.GetDirectory,
            "archivos": QgsFileWidget.StorageMode.GetMultipleFiles,
        }
        w.setStorageMode(modos[tipo])
        if spec.get("filtro"):
            w.setFilter(spec["filtro"])
        if default:
            if tipo == "archivos" and isinstance(default, list):
                w.setFilePath(" ".join('"%s"' % p for p in default))
            else:
                w.setFilePath(str(default))
        if tipo == "archivos":
            return w, lambda: [p for p in QgsFileWidget.splitFilePaths(w.filePath()) if p]
        return w, lambda: w.filePath().strip() or None

    if tipo == "origen":
        cont = QWidget()
        v = QVBoxLayout(cont)
        v.setContentsMargins(0, 0, 0, 0)
        combo = QComboBox()
        combo.addItems(MODOS_ORIGEN)
        fw = QgsFileWidget()
        fw.setStorageMode(QgsFileWidget.StorageMode.GetDirectory)
        fw.setEnabled(False)
        combo.currentIndexChanged.connect(lambda i: fw.setEnabled(i == 2))
        v.addWidget(combo)
        v.addWidget(fw)
        cont._combo, cont._fw = combo, fw  # refs vivas
        return cont, lambda: {"modo": CLAVES_MODO[combo.currentIndex()],
                              "carpeta": fw.filePath().strip() or None}

    if tipo in ("opciones_multi", "capas_multi"):
        # lista con casillas: varias opciones marcables sin escribir a mano
        w = QgsCheckableComboBox()
        if tipo == "capas_multi":
            filtro = spec.get("filtro_capa")
            vals = []
            for l in QgsProject.instance().mapLayers().values():
                if not isinstance(l, QgsVectorLayer):
                    continue
                if filtro == "linea" and l.geometryType() != 1:
                    continue
                if filtro == "punto" and l.geometryType() != 0:
                    continue
                if filtro == "poligono" and l.geometryType() != 2:
                    continue
                vals.append(l.name())
            vals = sorted(set(vals))
        else:
            vals = [str(x) for x in (spec.get("valores") or [])]
        w.addItems(vals)
        d = spec.get("default")
        if d:
            if isinstance(d, str):
                d = [x.strip() for x in d.split(",") if x.strip()]
            w.setCheckedItems([x for x in d if x in vals])
        return w, lambda: w.checkedItems()

    if tipo == "opciones":
        # desplegable con valores fijos; evita tener que escribir a mano
        w = QComboBox()
        vals = [str(x) for x in (spec.get("valores") or [])]
        w.addItems(vals)
        if spec.get("editable"):
            w.setEditable(True)
        d = spec.get("default")
        if d is not None and str(d) in vals:
            w.setCurrentIndex(vals.index(str(d)))
        return w, lambda: w.currentText()

    if tipo == "texto":
        w = QLineEdit(str(default) if default is not None else "")
        return w, lambda: w.text().strip() or None

    if tipo == "lista_texto":
        w = QLineEdit(str(default) if default is not None else "")
        return w, lambda: [s.strip() for s in w.text().split(",") if s.strip()]

    if tipo == "entero":
        w = QSpinBox()
        w.setRange(-2_000_000_000, 2_000_000_000)
        w.setValue(int(default or 0))
        return w, lambda: w.value()

    if tipo == "numero":
        w = QDoubleSpinBox()
        w.setDecimals(6)
        w.setRange(-1e12, 1e12)
        w.setValue(float(default or 0))
        return w, lambda: w.value()

    if tipo == "bool":
        w = QCheckBox()
        w.setChecked(bool(default))
        return w, lambda: w.isChecked()

    if tipo == "crs":
        w = QgsProjectionSelectionWidget()
        if default:
            w.setCrs(QgsCoordinateReferenceSystem(str(default)))
        return w, lambda: w.crs().authid() if w.crs().isValid() else None

    if tipo == "campos":
        # Desplegable múltiple con los campos de la capa elegida en otro
        # parámetro (clave "de_capa"). Se puebla/reacciona en cargar_script.
        w = QgsCheckableComboBox()
        w._defaults = default if isinstance(default, list) else \
            [s.strip() for s in str(default or "").split(",") if s.strip()]
        return w, lambda: w.checkedItems()

    raise ValueError(f"Tipo de parámetro desconocido: {tipo}")


class PanelScript(QWidget):
    """Panel derecho: descripción, formulario de parámetros y botones."""

    def __init__(self, iface, parent=None):
        super().__init__(parent)
        self.iface = iface
        self.script = None
        self.getters = {}

        layout = QVBoxLayout(self)

        self.lbl_desc = QLabel("Selecciona un script de la lista.")
        self.lbl_desc.setWordWrap(True)
        self.lbl_desc.setStyleSheet("font-weight: bold;")
        layout.addWidget(self.lbl_desc)

        self.lbl_ruta = QLabel("")
        self.lbl_ruta.setWordWrap(True)
        layout.addWidget(self.lbl_ruta)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        self.form_widget = QWidget()
        self.form = QFormLayout(self.form_widget)
        scroll.setWidget(self.form_widget)
        layout.addWidget(scroll, stretch=1)

        botones = QHBoxLayout()
        self.btn_importar = QPushButton("Importar script…")
        self.btn_importar.setToolTip("Copia tu archivo .py original dentro del "
                                     "plugin, en el slot de este script.")
        self.btn_importar.clicked.connect(self.importar_script)
        self.btn_libs = QPushButton("Verificar librerías")
        self.btn_libs.clicked.connect(self.verificar_libs)
        self.btn_ejecutar = QPushButton("Ejecutar")
        self.btn_ejecutar.clicked.connect(self.ejecutar)
        botones.addStretch()
        botones.addWidget(self.btn_importar)
        botones.addWidget(self.btn_libs)
        botones.addWidget(self.btn_ejecutar)
        layout.addLayout(botones)

        self.estado = QLabel("")
        self.estado.setWordWrap(True)
        layout.addWidget(self.estado)

    # ------------------------------------------------------------------
    def cargar_script(self, script):
        self.script = script
        self.getters = {}
        while self.form.rowCount():
            self.form.removeRow(0)

        if script is None:
            self.lbl_desc.setText("Selecciona un script de la lista.")
            self.lbl_ruta.setText("")
            return

        self.lbl_desc.setText(script["desc"])
        ruta = resolver_ruta(script["ruta"])
        existe = os.path.exists(ruta)
        self.lbl_ruta.setText(ruta + ("" if existe else "   [NO ENCONTRADO]"))

        widgets = {}
        for spec in script["params"]:
            w, getter = crear_widget(spec)
            self.getters[spec["var"]] = (spec, getter)
            widgets[spec["var"]] = (spec, w)
            self.form.addRow(spec["etiqueta"] + ":", w)

        # cablear parámetros "campos" a su combo de capa ("de_capa")
        for var, (spec, w) in widgets.items():
            if spec["tipo"] != "campos":
                continue
            fuente = widgets.get(spec.get("de_capa"), (None, None))[1]
            if not isinstance(fuente, QgsMapLayerComboBox):
                continue

            def poblar(layer, w=w):
                marcados = w.checkedItems() or w._defaults
                w.clear()
                if layer is not None:
                    nombres = [f.name() for f in layer.fields()]
                    w.addItems(nombres)
                    w.setCheckedItems([n for n in marcados if n in nombres])

            fuente.layerChanged.connect(poblar)
            poblar(fuente.currentLayer())

        if not script["params"]:
            self.form.addRow(QLabel("Este script no requiere parámetros "
                                    "(usa la capa activa / selección / clic en el lienzo)."))

        libs = script.get("libs") or []
        self.btn_libs.setVisible(bool(libs))
        self.estado.setText("Librerías requeridas: " + ", ".join(libs) if libs else "")

    # ------------------------------------------------------------------
    def _resolver_origen(self, spec, valor):
        """Convierte el modo elegido en (rutas de archivo, capas sin archivo).

        Las capas temporales/en memoria no tienen archivo: se devuelven aparte
        y solo las usan los scripts registrados con "acepta_capas": True
        (se inyectan como VAR_CAPAS)."""
        patrones = spec.get("patron", "*.geojson")
        if isinstance(patrones, str):
            patrones = [patrones]
        modo, carpeta = valor["modo"], valor["carpeta"]

        if modo == "carpeta":
            if not carpeta:
                raise ValueError(f"{spec['etiqueta']}: elige la carpeta.")
            rutas = []
            for p in patrones:
                rutas.extend(glob.glob(os.path.join(carpeta, p)))
            return modo, carpeta, sorted(set(rutas)), []

        if modo == "seleccionadas":
            capas = self.iface.layerTreeView().selectedLayers()
        else:
            capas = list(QgsProject.instance().mapLayers().values())

        rutas, capas_mem = [], []
        for c in capas:
            try:
                src = c.source().split("|")[0]
            except AttributeError:
                continue
            if os.path.isfile(src) and any(
                    fnmatch.fnmatch(os.path.basename(src).lower(), p.lower())
                    for p in patrones):
                rutas.append(src)
            elif not os.path.isfile(src) and isinstance(c, QgsVectorLayer):
                capas_mem.append(c)   # temporal / memoria / scratch
        return modo, carpeta, sorted(set(rutas)), capas_mem

    def _recolectar(self):
        valores, extras = {}, {}
        for var, (spec, getter) in self.getters.items():
            v = getter()
            if spec["tipo"] == "origen":
                modo, carpeta, rutas, capas_mem = self._resolver_origen(spec, v)
                acepta_capas = bool(spec.get("acepta_capas"))
                if not rutas and not (acepta_capas and capas_mem) \
                        and not spec.get("opcional"):
                    extra = (" (hay capas temporales seleccionadas, pero este "
                             "script solo trabaja con archivos)"
                             if capas_mem and not acepta_capas else "")
                    raise ValueError(
                        f"{spec['etiqueta']}: no se encontraron archivos "
                        f"(modo: {modo}). Revisa capas/selección/carpeta." + extra)
                valores[var] = rutas
                extras[var + "_MODO"] = modo
                extras[var + "_CARPETA"] = carpeta
                extras[var + "_CAPAS"] = capas_mem if acepta_capas else []
                continue
            vacio = v is None or v == "" or v == []
            if vacio and not spec.get("opcional"):
                raise ValueError(f"Falta el parámetro obligatorio: {spec['etiqueta']}")
            valores[var] = None if vacio else v
        return valores, extras

    def importar_script(self):
        if self.script is None:
            return
        destino = resolver_ruta(self.script["ruta"])
        origen, _f = QFileDialog.getOpenFileName(
            self, "Selecciona tu script original", "", "Python (*.py)")
        if not origen:
            return
        try:
            os.makedirs(os.path.dirname(destino), exist_ok=True)
            shutil.copy2(origen, destino)
            self._aviso(f"Importado a {destino}", Qgis.MessageLevel.Success)
            self.cargar_script(self.script)
        except Exception as e:
            self._aviso(f"No se pudo importar: {e}", Qgis.MessageLevel.Critical)

    def verificar_libs(self):
        libs = self.script.get("libs") or []
        faltantes = []
        for lib in libs:
            try:
                importlib.import_module(lib)
            except ImportError:
                faltantes.append(lib)
        if not faltantes:
            self.estado.setText("Todas las librerías están instaladas: " + ", ".join(libs))
            return
        paquetes = [PIP_NOMBRES.get(l, l) for l in faltantes]
        cmd = [sys.executable, "-m", "pip", "install", "--user"] + paquetes
        self.estado.setText("Faltan: " + ", ".join(faltantes) + ". Instalando…")
        try:
            r = subprocess.run(cmd, capture_output=True, text=True, timeout=600)
            QgsMessageLog.logMessage(r.stdout + "\n" + r.stderr, "Mi Plugin",
                                     level=Qgis.MessageLevel.Info)
            if r.returncode == 0:
                self.estado.setText("Instaladas: " + ", ".join(paquetes) +
                                    ". Reinicia QGIS si el import sigue fallando.")
            else:
                self.estado.setText("Error instalando (ver Registro de mensajes). "
                                    "Alternativa: OSGeo4W Shell → python -m pip install "
                                    + " ".join(paquetes))
        except Exception as e:
            self.estado.setText(f"No se pudo instalar: {e}. "
                                "Usa OSGeo4W Shell → python -m pip install " + " ".join(paquetes))

    # ------------------------------------------------------------------
    def ejecutar(self):
        if self.script is None:
            return
        ruta = resolver_ruta(self.script["ruta"])
        nombre = self.script["nombre"]

        if not os.path.exists(ruta):
            self._aviso(f"No existe: {ruta}", Qgis.MessageLevel.Critical)
            return
        if ruta.lower().endswith(".ipynb"):
            self._aviso("Los notebooks no se ejecutan aquí. Conviértelo con: "
                        "jupyter nbconvert --to script", Qgis.MessageLevel.Warning)
            return

        try:
            valores, extras = self._recolectar()
        except ValueError as e:
            self._aviso(str(e), Qgis.MessageLevel.Warning)
            return

        inyectar = dict(valores)
        inyectar.update(extras)
        inyectar["iface"] = self.iface
        inyectar["PLUGIN_PARAMS"] = {**valores, **extras}
        inyectar["adoptar_nombre"] = adoptar_nombre

        self.btn_ejecutar.setEnabled(False)
        self.estado.setText(f"Ejecutando {nombre}…")
        try:
            runpy.run_path(ruta, init_globals=inyectar, run_name="__main__")
            self.estado.setText(f"'{nombre}' terminó sin errores.")
            self._aviso(f"'{nombre}' terminó sin errores.", Qgis.MessageLevel.Success)
        except Exception as e:
            self.estado.setText(f"Error en '{nombre}': {e}")
            self._aviso(f"Error en '{nombre}': {e}", Qgis.MessageLevel.Critical)
            QgsMessageLog.logMessage(traceback.format_exc(), "Mi Plugin",
                                     level=Qgis.MessageLevel.Critical)
        finally:
            self.btn_ejecutar.setEnabled(True)

    def _aviso(self, texto, nivel):
        self.iface.messageBar().pushMessage("Mi Plugin", texto, level=nivel, duration=7)


class SeccionGrupo(QWidget):
    """Pestaña de un grupo: lista de scripts a la izquierda, panel a la derecha."""

    def __init__(self, iface, scripts, parent=None):
        super().__init__(parent)
        layout = QVBoxLayout(self)
        splitter = QSplitter(Qt.Orientation.Horizontal)

        self.lista = QListWidget()
        for s in scripts:
            item = QListWidgetItem(s["nombre"])
            item.setData(Qt.ItemDataRole.UserRole, s)
            ruta = resolver_ruta(s["ruta"])
            item.setToolTip(ruta)
            if not os.path.exists(ruta):
                item.setText(s["nombre"] + "  [no encontrado]")
            self.lista.addItem(item)
        splitter.addWidget(self.lista)

        self.panel = PanelScript(iface)
        splitter.addWidget(self.panel)
        splitter.setSizes([240, 520])

        self.lista.currentItemChanged.connect(
            lambda item, _ant: self.panel.cargar_script(
                item.data(Qt.ItemDataRole.UserRole) if item else None))

        layout.addWidget(splitter)


class MiPluginDialog(QDialog):
    def __init__(self, iface, parent=None):
        super().__init__(parent)
        self.iface = iface
        self.setWindowTitle("Mi Plugin")
        self.resize(900, 580)

        layout = QVBoxLayout(self)
        tabs = QTabWidget()
        layout.addWidget(tabs)

        grupos = {}
        for s in REGISTRO:
            grupos.setdefault(s["grupo"], []).append(s)
        for nombre_grupo, scripts in grupos.items():
            tabs.addTab(SeccionGrupo(iface, scripts), nombre_grupo)

        cerrar = QPushButton("Cerrar")
        cerrar.clicked.connect(self.reject)
        h = QHBoxLayout()
        h.addStretch()
        h.addWidget(cerrar)
        layout.addLayout(h)
