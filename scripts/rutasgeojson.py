# -*- coding: utf-8 -*-
"""Imprime en la consola las rutas de los GeoJSON del origen elegido.
Cableado a la UI: usa ENTRADAS inyectado."""
if "ENTRADAS" not in globals():
    raise ValueError("Falta ENTRADAS (elige el origen en la interfaz).")

print(f"--- {len(ENTRADAS)} archivo(s) [{globals().get('ENTRADAS_MODO','?')}] ---")
for r in ENTRADAS:
    print(r)
