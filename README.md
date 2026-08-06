# Mi Plugin — v0.5.0

Lanzador de scripts con parámetros configurables desde la interfaz de QGIS 4.0 (Qt6).

## Cómo funciona la inyección de parámetros

Al pulsar **Ejecutar**, el plugin corre tu script dentro del Python de QGIS e
inyecta como **variables globales** los valores elegidos en la interfaz, usando
los MISMOS nombres de variable que ya usa tu script (`DEM`, `input_path`,
`BASE`, `LAYER_NAME`, etc.). También inyecta `iface` y un dict `PLUGIN_PARAMS`.

**Adaptación requerida (una línea por variable):** para que el valor hardcodeado
de tu script no pise el valor inyectado, envuelve cada asignación de
configuración así:

    ANTES:
        DEM = r"E:\phoenix\...\DTM_SOUTH_RURAL_005m.tif"

    DESPUÉS:
        if "DEM" not in globals():
            DEM = r"E:\phoenix\...\DTM_SOUTH_RURAL_005m.tif"

Así el script sigue funcionando igual en PyCharm/consola (usa su default) y en
el plugin (usa lo elegido en la interfaz).

## Formatos en que llegan los valores

| Tipo en el registro | Valor inyectado |
|---|---|
| capa | objeto QgsMapLayer |
| capa_nombre | str — nombre de la capa |
| capa_ruta | str — ruta de origen de la capa |
| archivo / archivo_salida / carpeta | str — ruta |
| archivos | list[str] — lista de rutas |
| texto | str |
| lista_texto | list[str] |
| entero / numero | int / float |
| bool | True/False |
| crs | str — "EPSG:xxxx" |

Notas puntuales:
- `converttogs84.py`: `crs_src`/`crs_dst` llegan como texto "EPSG:xxxx".
  Adapta: `crs_src = QgsCoordinateReferenceSystem(crs_src) if isinstance(crs_src, str) else crs_src`
- `shp_to_geojson_with_reference.py`: se inyectan `shp_in`, `ref_geojson`,
  `out_geojson`. Al inicio del script arma:
  `if "shp_in" in globals(): PAIRS = [{"shp": shp_in, "ref": ref_geojson, "out": out_geojson}]`
- `cortefinal consolidado2.py`: `BASE` llega como str; conviértelo:
  `BASE = Path(BASE)`.
- `lanelet.ipynb`: los notebooks no se ejecutan desde el plugin. Conviértelo:
  `jupyter nbconvert --to script lanelet.ipynb`, y actualiza la ruta en el
  registro a `lanelet.py`.

## Librerías

Los scripts que requieren librerías externas (geopandas, rasterio, shapely,
pandas, sqlalchemy, geoalchemy2, psycopg2) muestran el botón
**Verificar librerías**: comprueba los imports e instala los faltantes con pip
en el Python de QGIS (`--user`). Si la instalación desde el plugin falla,
hazlo desde la **OSGeo4W Shell**:

    python -m pip install geopandas rasterio shapely sqlalchemy geoalchemy2 psycopg2-binary

## Editar el registro

Todo está en el bloque `REGISTRO` al inicio de `dialog.py`: cada script es un
dict con `grupo`, `nombre`, `ruta`, `desc`, `libs` y `params`. Agregar un
parámetro nuevo = añadir un dict a `params` con `var`, `tipo`, `etiqueta` y
opcionalmente `default`, `filtro`, `filtro_capa`, `opcional`.

Carpeta instalada del plugin:
`C:\Users\boris\AppData\Roaming\QGIS\QGIS4\profiles\default\python\plugins\mi_plugin\`

---

# Novedades v0.6.0

## Entrada flexible (tipo "origen")

fix_geojson, migrate_fields, reportetxt_ids, rutasgeojson, revisarids y
converttogs84 ahora tienen un selector de origen con 3 modos:

- **Todas las capas cargadas** — toma la ruta de archivo de cada capa del proyecto
- **Capas seleccionadas en el panel** — solo las capas marcadas en el panel de capas
- **Carpeta** — todos los archivos de la carpeta que cumplan el patrón

En los tres casos el script recibe lo mismo, así que basta UNA adaptación:

    ENTRADAS         list[str] — rutas de archivo resueltas
    ENTRADAS_MODO    "cargadas" | "seleccionadas" | "carpeta"
    ENTRADAS_CARPETA carpeta elegida o None

Adaptación típica en el script:

    if "ENTRADAS" in globals():
        archivos = ENTRADAS
    else:
        archivos = glob.glob(os.path.join(FOLDER_PATH, "*.geojson"))
    for ruta in archivos:
        ...

## Convención de nombres de capas (adoptar_nombre)

Para que procesos como aplicar_estilos.py reconozcan las capas base
(LANELET, VIRTUAL_LINE, LANE_MARKER, ...), la capa GENERADA por un proceso
debe quedar con el nombre base SIN sufijos, y la original renombrarse con el
nombre del proceso (así no hacen falta backups tipo capa_migrated).

El plugin inyecta el helper listo para usar:

    nueva = ...  # capa creada por tu script
    adoptar_nombre("LANELET", nueva, capa_original=orig, proceso="migrate")
    # → nueva se llama "LANELET"; orig se llama "LANELET_migrate"

## Script nuevo incluido en el plugin

`scripts/box_to_point_dem.py` viene DENTRO del plugin (ruta relativa en el
registro): convierte TRAFFIC_SIGN_BOX / TRAFFIC_LIGHT_BOX a puntos con Z
muestreada del DEM cargado. Crea TRAFFIC_SIGN_POINT / TRAFFIC_LIGHT_POINT en
memoria. Opción: un punto por polígono (centroide) o por vértice. Solo PyQGIS.
