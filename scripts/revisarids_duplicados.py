# -*- coding: utf-8 -*-
"""revisarids_duplicados — duplicados por campo y por COMBINACIÓN (AND).

Sobre la capa elegida (archivo o temporal) y los campos marcados en el
desplegable (ej. LANELET: id, right_line_id, left_line_id):

  1. Duplicados POR CAMPO: cada campo por separado (como antes) + nulos.
  2. Duplicados por COMBINACIÓN (AND): features donde TODOS los campos
     seleccionados coinciden a la vez → segmentos realmente duplicados
     (misma identidad y mismas líneas derecha/izquierda), no simples
     coincidencias de un solo campo.
  3. Lista de IDs de los duplicados reales para corrección manual.

Genera un reporte TXT (similar a reportetxt_ids) y lo imprime en consola.
"""
import os
import tempfile
from datetime import datetime

if "capa" not in globals() or capa is None:
    raise ValueError("Selecciona la capa a revisar.")
if "CAMPOS" not in globals() or not CAMPOS:
    raise ValueError("Marca al menos un campo en el desplegable.")
if "ID_FIELD" not in globals() or not ID_FIELD:
    ID_FIELD = "id"
if "OUTPUT_TXT" not in globals():
    OUTPUT_TXT = None
if "MAX_LISTA" not in globals():
    MAX_LISTA = 20

faltan = [c for c in CAMPOS if capa.fields().indexOf(c) < 0]
if faltan:
    raise ValueError(f"La capa '{capa.name()}' no tiene los campos: {', '.join(faltan)}")

L = []


def out(s=""):
    print(s)
    L.append(str(s))


def es_nulo(v):
    return v is None or (isinstance(v, str) and not v.strip())


def fmt(v):
    return "NULL" if es_nulo(v) else str(v)


idx_id = capa.fields().indexOf(ID_FIELD)
total = capa.featureCount()

out("REPORTE DE DUPLICADOS — lógica por campo y por combinación (AND)")
out("=" * 64)
out(f"capa: {capa.name()}  |  entidades: {total}")
out(f"campos analizados: {', '.join(CAMPOS)}")
out(f"fecha: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")

# -------- pasada única: conteos por campo y por combinación ----------------
por_campo = {c: {} for c in CAMPOS}     # campo -> valor -> n
nulos = {c: 0 for c in CAMPOS}
combos = {}                             # tupla valores -> [ids de lanelet]

for f in capa.getFeatures():
    valores = []
    for c in CAMPOS:
        v = f[c]
        if es_nulo(v):
            nulos[c] += 1
            valores.append(None)
        else:
            por_campo[c][v] = por_campo[c].get(v, 0) + 1
            valores.append(v)
    ident = f[idx_id] if idx_id >= 0 else f.id()
    combos.setdefault(tuple(valores), []).append(ident)

# ------------------------- 1. por campo ------------------------------------
out()
out("--- 1. DUPLICADOS POR CAMPO (individual) ---")
for c in CAMPOS:
    dups = {v: n for v, n in por_campo[c].items() if n > 1}
    extra = sum(dups.values()) - len(dups)
    out(f"[{c}] valores duplicados: {len(dups)} | entidades de más: {extra} "
        f"| nulos: {nulos[c]}")
    for v, n in sorted(dups.items(), key=lambda x: -x[1])[:MAX_LISTA]:
        out(f"    {c}={v} aparece {n} veces")
    if len(dups) > MAX_LISTA:
        out(f"    … y {len(dups) - MAX_LISTA} valores más")

# --------------------- 2. combinación AND ----------------------------------
out()
out(f"--- 2. DUPLICADOS POR COMBINACIÓN ({' AND '.join(CAMPOS)}) ---")
combo_dups = {k: ids for k, ids in combos.items() if len(ids) > 1}
extra_combo = sum(len(i) for i in combo_dups.values()) - len(combo_dups)
if not combo_dups:
    out("Ninguna combinación repetida: los duplicados individuales NO son "
        "segmentos duplicados completos.")
else:
    out(f"combinaciones repetidas: {len(combo_dups)} | segmentos duplicados "
        f"de más (a eliminar): {extra_combo}")
    for k, ids in sorted(combo_dups.items(), key=lambda x: -len(x[1]))[:MAX_LISTA]:
        detalle = " | ".join(f"{c}={fmt(v)}" for c, v in zip(CAMPOS, k))
        out(f"    {len(ids)} veces → {detalle}")
    if len(combo_dups) > MAX_LISTA:
        out(f"    … y {len(combo_dups) - MAX_LISTA} combinaciones más")

    # ----------------- 3. IDs para corrección manual -----------------------
    out()
    out(f"--- 3. IDs ({ID_FIELD}) DE SEGMENTOS DUPLICADOS REALES "
        "(corregir manualmente) ---")
    ids_unicos = sorted({fmt(i) for ids in combo_dups.values() for i in ids})
    out(", ".join(ids_unicos))
    out(f"(total: {len(ids_unicos)} ids)")

# --------------------------- guardar TXT -----------------------------------
ruta_txt = (OUTPUT_TXT or "").strip() or None
if ruta_txt is None:
    src = capa.source().split("|")[0]
    carpeta = os.path.dirname(src) if os.path.isfile(src) else tempfile.gettempdir()
    ruta_txt = os.path.join(
        carpeta, f"duplicados_{capa.name()}_{datetime.now().strftime('%Y%m%d_%H%M%S')}.txt")
with open(ruta_txt, "w", encoding="utf-8") as fh:
    fh.write("\n".join(L))
print(f"\nReporte guardado: {ruta_txt}")
