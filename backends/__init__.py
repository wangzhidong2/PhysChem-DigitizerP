# -*- coding: utf-8 -*-
"""backends 包 — 传感器 Backend 基类与图表桥接

- BackendBase: 各传感器 Backend 的 QObject 基类，向 QML 暴露通用能力。
- ChartItem: pyqtgraph -> QQuickPaintedItem 桥接，供 QML 嵌入图表。
"""

from .backend_base import BackendBase
from .chart_item import ChartItem

__all__ = ["BackendBase", "ChartItem"]
