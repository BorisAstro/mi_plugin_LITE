# -*- coding: utf-8 -*-
"""Punto de entrada del plugin. QGIS llama a classFactory al cargar."""


def classFactory(iface):
    from .plugin import MiPlugin
    return MiPlugin(iface)
