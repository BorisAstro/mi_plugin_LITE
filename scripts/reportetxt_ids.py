# -*- coding: utf-8 -*-
"""reportetxt_ids — reporte de IDs por capa, y comparacion entre dos reportes.

MODO 'reporte': recorre las capas del origen y escribe por cada una el numero
de entidades, ids nulos, duplicados internos, el rango y (opcional) la lista
completa de ids.

MODO 'comparar': lee dos reportes ya generados y cruza sus ids para detectar
colisiones. El rango por si solo solo indica un solape POSIBLE; con la lista
completa la deteccion es exacta, por eso conviene generar los reportes con
'Incluir la lista de ids' activado.
"""
import os
import re

from qgis.core import QgsProject, QgsVectorLayer

P = globals().get("PLUGIN_PARAMS", {}) or {}


def _p(k, d=None):
    v = P.get(k, globals().get(k, d))
    return d if v is None or v == "" else v


MODO = str(_p("MODO", "reporte")).strip().lower()
ID_FIELD = str(_p("ID_FIELD", "id") or "id")
OUTPUT_TXT = str(_p("OUTPUT_TXT", "") or "").strip()
INCLUIR_IDS = bool(_p("INCLUIR_IDS", True))
REPORTE_A = str(_p("REPORTE_A", "") or "").strip()
REPORTE_B = str(_p("REPORTE_B", "") or "").strip()
GRUPO_A = str(_p("GRUPO_A", "") or "").strip()
GRUPO_B = str(_p("GRUPO_B", "") or "").strip()


def tipo_entidad(nombre):
    """CROSSWALK_1785293184.geojson -> CROSSWALK.

    Empareja capas entre grupos aunque uno lleve el sufijo de exportacion y el
    otro no; comparar por nombre exacto dejaba la tabla vacia.
    """
    n = re.sub(r"\.(geojson|shp|gpkg)$", "", str(nombre), flags=re.I)
    n = re.sub(r"(_\d{6,})+$", "", n)
    n = re.sub(r"_MERGED$", "", n, flags=re.I)
    return n.upper()


def reporte_de_capas(capas, campo, ruta_salida, titulo):
    """Escribe el reporte de una lista de capas ya cargadas."""
    L = ["REPORTE DE IDS — campo '%s' — %s" % (campo, titulo), "=" * 60]
    for lyr in capas:
        L.append("\n%s" % lyr.name())
        L.append("  ruta: %s" % lyr.source().split("|")[0])
        L.append("  entidades: %d" % lyr.featureCount())
        if lyr.fields().indexOf(campo) < 0:
            L.append("  sin campo '%s'" % campo)
            continue
        ids, nulos = [], 0
        for f in lyr.getFeatures():
            v = f[campo]
            if v is None or (isinstance(v, str) and not v.strip()):
                nulos += 1
            else:
                try:
                    ids.append(int(v))
                except (TypeError, ValueError):
                    pass
        L.append("  ids numéricos: %d | nulos: %d | duplicados: %d"
                 % (len(ids), nulos, len(ids) - len(set(ids))))
        if ids:
            L.append("  rango: %d .. %d" % (min(ids), max(ids)))
            L.append("  lista: " + ",".join(str(x) for x in sorted(set(ids))))
    d = os.path.dirname(ruta_salida)
    if d:
        os.makedirs(d, exist_ok=True)
    with open(ruta_salida, "w", encoding="utf-8") as fh:
        fh.write("\n".join(L))
    return ruta_salida


def capas_de_grupo(nombre):
    raiz = QgsProject.instance().layerTreeRoot()
    nodo = raiz.findGroup(nombre)
    if nodo is None:
        disponibles = [g.name() for g in raiz.findGroups()]
        raise ValueError("No existe el grupo '%s'. Grupos: %s"
                         % (nombre, ", ".join(disponibles) or "(ninguno)"))
    capas = [n.layer() for n in nodo.findLayers()
             if isinstance(n.layer(), QgsVectorLayer)]
    if not capas:
        raise ValueError("El grupo '%s' no tiene capas vectoriales." % nombre)
    return capas


def parse_reporte(ruta_txt):
    """Devuelve {capa: {'n':.., 'min':.., 'max':.., 'ids':set()}}."""
    if not os.path.isfile(ruta_txt):
        raise ValueError("No existe el reporte: %s" % ruta_txt)
    datos, actual = {}, None
    with open(ruta_txt, encoding="utf-8") as fh:
        for linea in fh:
            l = linea.rstrip("\n")
            if l and not l.startswith(" ") and not l.startswith("=") \
                    and not l.startswith("REPORTE") and not l.startswith("COMPARACION"):
                actual = l.strip()
                datos[actual] = {"n": None, "min": None, "max": None, "ids": set()}
                continue
            if actual is None:
                continue
            m = re.match(r"\s+entidades:\s*(\d+)", l)
            if m:
                datos[actual]["n"] = int(m.group(1))
            m = re.match(r"\s+rango:\s*(-?\d+)\s*\.\.\s*(-?\d+)", l)
            if m:
                datos[actual]["min"] = int(m.group(1))
                datos[actual]["max"] = int(m.group(2))
            m = re.match(r"\s+lista:\s*(.*)", l)
            if m and m.group(1).strip():
                for t in m.group(1).split(","):
                    t = t.strip()
                    if t.lstrip("-").isdigit():
                        datos[actual]["ids"].add(int(t))
    return {k: v for k, v in datos.items() if v["n"] is not None or v["ids"]}


# ============================== COMPARAR =====================================
if MODO.startswith("compar"):
    if GRUPO_A and GRUPO_B:
        carpeta = os.path.dirname(OUTPUT_TXT) or os.path.expanduser("~")
        REPORTE_A = reporte_de_capas(
            capas_de_grupo(GRUPO_A), ID_FIELD,
            os.path.join(carpeta, "reporte_%s.txt" % GRUPO_A),
            "grupo '%s'" % GRUPO_A)
        REPORTE_B = reporte_de_capas(
            capas_de_grupo(GRUPO_B), ID_FIELD,
            os.path.join(carpeta, "reporte_%s.txt" % GRUPO_B),
            "grupo '%s'" % GRUPO_B)
        print("Reportes generados desde los grupos:")
        print("   A: %s" % REPORTE_A)
        print("   B: %s" % REPORTE_B)
    if not (REPORTE_A and REPORTE_B):
        raise ValueError("Indica dos grupos del panel, o dos reportes ya "
                         "generados.")
    A = parse_reporte(REPORTE_A)
    B = parse_reporte(REPORTE_B)
    L = ["COMPARACION DE REPORTES DE IDS",
         "=" * 74,
         "A: %s   (%d capas)" % (REPORTE_A, len(A)),
         "B: %s   (%d capas)" % (REPORTE_B, len(B)),
         ""]

    con_lista = all(v["ids"] for v in list(A.values()) + list(B.values())) \
        if (A and B) else False
    if not con_lista:
        L.append("AVISO: alguno de los reportes no trae la lista de ids; la "
                 "deteccion sera por SOLAPE DE RANGO, que solo indica colision "
                 "POSIBLE. Regenera con 'Incluir la lista de ids' para un cruce "
                 "exacto.")
        L.append("")

    # emparejado por TIPO DE ENTIDAD, no por nombre de archivo
    ta, tb = {}, {}
    for k, v in A.items():
        ta.setdefault(tipo_entidad(k), []).append((k, v))
    for k, v in B.items():
        tb.setdefault(tipo_entidad(k), []).append((k, v))

    def _une(lista):
        ids = set()
        nombres = []
        mn = mx = None
        for k, v in lista:
            nombres.append(k)
            ids |= v["ids"]
            for campo_r, f in (("min", min), ("max", max)):
                if v[campo_r] is not None:
                    actual = mn if campo_r == "min" else mx
                    nuevo_v = v[campo_r] if actual is None else f(actual, v[campo_r])
                    if campo_r == "min":
                        mn = nuevo_v
                    else:
                        mx = nuevo_v
        return {"ids": ids, "min": mn, "max": mx, "nombres": nombres}

    ua = {t: _une(v) for t, v in ta.items()}
    ub = {t: _une(v) for t, v in tb.items()}
    comunes = sorted(set(ua) & set(ub))
    solo_a = sorted(set(ua) - set(ub))
    solo_b = sorted(set(ub) - set(ua))
    L.append("entidades en ambos: %d | solo en A: %d | solo en B: %d"
             % (len(comunes), len(solo_a), len(solo_b)))
    if solo_a:
        L.append("  solo en A: " + ", ".join(solo_a))
    if solo_b:
        L.append("  solo en B: " + ", ".join(solo_b))
    L.append("")
    L.append("%-22s %8s %8s %-20s %-20s %s"
             % ("ENTIDAD", "ids A", "ids B", "RANGO A", "RANGO B", "COLISION"))
    L.append("-" * 100)

    total_col = 0
    for t in comunes:
        a, b = ua[t], ub[t]
        ra = "%s..%s" % (a["min"], a["max"]) if a["min"] is not None else "-"
        rb = "%s..%s" % (b["min"], b["max"]) if b["min"] is not None else "-"
        if a["ids"] and b["ids"]:
            inter = a["ids"] & b["ids"]
            total_col += len(inter)
            est = ("%d ids repetidos" % len(inter)) if inter else "ninguna"
            L.append("%-22s %8d %8d %-20s %-20s %s"
                     % (t[:22], len(a["ids"]), len(b["ids"]), ra, rb, est))
            if inter:
                L.append("      ids repetidos: "
                         + ", ".join(str(x) for x in sorted(inter)))
        else:
            solapa = (a["min"] is not None and b["min"] is not None
                      and a["min"] <= b["max"] and b["min"] <= a["max"])
            L.append("%-22s %8s %8s %-20s %-20s %s"
                     % (t[:22], len(a["ids"]) or "-", len(b["ids"]) or "-", ra, rb,
                        "RANGOS SE SOLAPAN (posible)" if solapa else "rangos disjuntos"))

    # cruce global: los ids deberian ser unicos en todo el conjunto
    ids_a = set().union(*[v["ids"] for v in A.values()]) if A else set()
    ids_b = set().union(*[v["ids"] for v in B.values()]) if B else set()
    L.append("-" * 96)
    if ids_a and ids_b:
        glob = ids_a & ids_b
        L.append("CRUCE GLOBAL (todas las capas juntas): %d ids de A tambien "
                 "estan en B" % len(glob))
        if glob:
            L.append("  ids: " + ", ".join(str(x) for x in sorted(glob)))
            # decir en que capas aparece cada uno
            L.append("  reparto por capa:")
            for k in comunes:
                n = len(A[k]["ids"] & ids_b)
                if n:
                    L.append("     %-30s %d" % (k[:30], n))
        L.append("colisiones dentro de capas homonimas: %d" % total_col)
    else:
        L.append("Sin listas de ids: no se pudo hacer el cruce global.")

    # Un id deberia identificar a UNA sola entidad en todo el conjunto. Si el
    # mismo numero aparece en dos capas del mismo grupo, cualquier referencia
    # por id (traffic_light_box_id, lane_id...) se vuelve ambigua.
    L.append("")
    L.append("IDS REPETIDOS ENTRE CAPAS DEL MISMO GRUPO")
    L.append("-" * 100)
    for nom, D in (("A", A), ("B", B)):
        cont = {}
        for k, v in D.items():
            for i in v["ids"]:
                cont.setdefault(i, []).append(k)
        rep = {i: ks for i, ks in cont.items() if len(ks) > 1}
        if not rep:
            L.append("  grupo %s: ninguno" % nom)
            continue
        pares = {}
        for i, ks in rep.items():
            pares.setdefault(" + ".join(sorted(tipo_entidad(x) for x in ks)), []).append(i)
        L.append("  grupo %s: %d ids aparecen en 2 o mas capas" % (nom, len(rep)))
        for par, lista in sorted(pares.items(), key=lambda x: -len(x[1])):
            L.append("     %-46s %d ids" % (par, len(lista)))
            L.append("        " + ", ".join(str(x) for x in sorted(lista)[:40])
                     + (" ..." if len(lista) > 40 else ""))

    salida = OUTPUT_TXT or os.path.join(os.path.dirname(REPORTE_A),
                                        "comparacion_ids.txt")
    d = os.path.dirname(salida)
    if d:
        os.makedirs(d, exist_ok=True)
    with open(salida, "w", encoding="utf-8") as fh:
        fh.write("\n".join(L))
    print("\n".join(L))
    print("\nComparacion escrita: %s" % salida)

# ============================== REPORTE ======================================
else:
    if "ENTRADAS" not in globals() or not ENTRADAS:
        raise ValueError("Falta ENTRADAS (elige el origen en la interfaz).")
    if not OUTPUT_TXT:
        raise ValueError("Indica la ruta del TXT de salida.")

    lineas = ["REPORTE DE IDS — campo '%s' — %d archivo(s)" % (ID_FIELD, len(ENTRADAS)),
              "=" * 60]
    for ruta_c in ENTRADAS:
        lyr = QgsVectorLayer(ruta_c, os.path.basename(ruta_c), "ogr")
        if not lyr.isValid():
            lineas.append("\n[ERROR] no se pudo abrir: %s" % ruta_c)
            continue
        lineas.append("\n%s" % os.path.basename(ruta_c))
        lineas.append("  ruta: %s" % ruta_c)
        lineas.append("  entidades: %d" % lyr.featureCount())
        if lyr.fields().indexOf(ID_FIELD) < 0:
            lineas.append("  sin campo '%s'" % ID_FIELD)
            continue
        ids, nulos = [], 0
        for f in lyr.getFeatures():
            v = f[ID_FIELD]
            if v is None or (isinstance(v, str) and not v.strip()):
                nulos += 1
            else:
                try:
                    ids.append(int(v))
                except (TypeError, ValueError):
                    pass
        dups = len(ids) - len(set(ids))
        lineas.append("  ids numéricos: %d | nulos: %d | duplicados: %d"
                      % (len(ids), nulos, dups))
        if ids:
            lineas.append("  rango: %d .. %d" % (min(ids), max(ids)))
            if INCLUIR_IDS:
                lineas.append("  lista: " + ",".join(str(x) for x in sorted(set(ids))))

    d = os.path.dirname(OUTPUT_TXT)
    if d:
        os.makedirs(d, exist_ok=True)
    with open(OUTPUT_TXT, "w", encoding="utf-8") as fh:
        fh.write("\n".join(lineas))
    print("Reporte escrito: %s" % OUTPUT_TXT)
    if INCLUIR_IDS:
        print("Incluye la lista de ids: se puede comparar con otro reporte "
              "en modo 'comparar'.")
