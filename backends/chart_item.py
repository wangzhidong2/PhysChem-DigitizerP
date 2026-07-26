# -*- coding: utf-8 -*-
"""backends/chart_item.py — pyqtgraph 嵌入 QML 的桥接

通过 QQuickPaintedItem 把 pyqtgraph 的 PlotWidget 渲染到 QML 场景。
paint() 中调用 PlotWidget.render(painter) 完成绘制。

QML 用法：
    import Charts 1.0
    ChartItem {
        width: 600; height: 360
        Component.onCompleted: {
            setLabels("时间 (s)", "数值")
            setData([0,1,2,3], [1,2,3,4], "#0078d4", "曲线1")
        }
    }

需要在 main.py 中通过 qmlRegisterType 注册到 QML。
"""

from PySide6.QtCore import Slot, Qt
from PySide6.QtGui import QColor
from PySide6.QtQuick import QQuickPaintedItem

import pyqtgraph as pg


# 全局 pyqtgraph 配置（仅设置一次）
_pg_initialized = False


def _init_pyqtgraph():
    global _pg_initialized
    if _pg_initialized:
        return
    pg.setConfigOption('background', 'white')
    pg.setConfigOption('foreground', '#1a1a1a')
    pg.setConfigOption('antialias', True)
    _pg_initialized = True


class ChartItem(QQuickPaintedItem):
    """pyqtgraph 图表组件，可在 QML 中作为 Item 使用。"""

    def __init__(self, parent=None):
        super().__init__(parent)
        _init_pyqtgraph()
        self._plot_widget = pg.PlotWidget()
        self._plot_widget.setBackground('white')
        self._plot_widget.showGrid(x=True, y=True, alpha=0.2)
        self._curves = {}  # name -> PlotDataItem
        self._x_label = "时间 (s)"
        self._y_label = "数值"
        self._plot_widget.setLabel('left', self._y_label)
        self._plot_widget.setLabel('bottom', self._x_label)
        # 初始大小，避免 render 时尺寸为 0
        self._plot_widget.resize(400, 240)

    def geometryChange(self, new_geometry, old_geometry):
        super().geometryChange(new_geometry, old_geometry)
        if new_geometry.width() > 0 and new_geometry.height() > 0:
            self._plot_widget.resize(
                int(new_geometry.width()), int(new_geometry.height())
            )
            self.update()

    def paint(self, painter):
        painter.setRenderHint(painter.RenderHint.Antialiasing, True)
        # 用 QWidget.render(QPainter*) 把图表渲染到 QML 画布
        self._plot_widget.render(painter)

    # ---------------- QML Slot ----------------
    @Slot(list, list, str, str)
    def setData(self, x_list, y_list, color="#0078d4", curve_name="default"):
        if not x_list or not y_list:
            return
        pen = pg.mkPen(color, width=2)
        if curve_name in self._curves:
            self._curves[curve_name].setData(x=list(x_list), y=list(y_list), pen=pen)
        else:
            self._curves[curve_name] = self._plot_widget.plot(
                x=list(x_list), y=list(y_list), pen=pen, name=curve_name
            )
        self.update()

    @Slot()
    def clearAll(self):
        for c in self._curves.values():
            self._plot_widget.removeItem(c)
        self._curves.clear()
        self.update()

    @Slot(str, str)
    def setLabels(self, x_label, y_label):
        self._x_label = x_label
        self._y_label = y_label
        self._plot_widget.setLabel('bottom', x_label)
        self._plot_widget.setLabel('left', y_label)
        self.update()

    @Slot(str)
    def setTitle(self, title):
        self._plot_widget.setTitle(title)
        self.update()

    @Slot(float, float)
    def setXRange(self, x_min, x_max):
        self._plot_widget.setXRange(x_min, x_max, padding=0.02)
        self.update()

    @Slot(float, float)
    def setYRange(self, y_min, y_max):
        self._plot_widget.setYRange(y_min, y_max, padding=0.02)
        self.update()

    @Slot(bool)
    def setAutoScrollX(self, enabled):
        if enabled and self._curves:
            for c in self._curves.values():
                if c.getData() is not None:
                    xs = c.getData()[0]
                    if len(xs) > 0:
                        x_max = float(xs[-1])
                        self._plot_widget.setXRange(
                            max(0, x_max - 10), x_max + 0.5, padding=0
                        )
        self.update()
