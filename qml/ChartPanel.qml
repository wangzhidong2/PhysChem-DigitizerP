// ChartPanel.qml — 图表面板（图表 + 当前值 + 统计 + 日志）
import QtQuick
import QtQuick.Controls
import QtQuick.Layouts
import FluentTheme 1.0
import Charts 1.0

RowLayout {
    id: root
    property var backend: null
    property string xLabel: "时间 (s)"
    property string yLabel: "数值"
    property string currentValueText: ""
    property string statsText: ""
    spacing: Fluent.spacingM

    Component.onCompleted: {
        if (backend) {
            backend.currentValueUpdated.connect(function(v){
                root.currentValueText = v
            })
            backend.statsUpdated.connect(function(s){
                root.statsText = s
            })
            backend.chartUpdated.connect(root.refreshChart)
            root.currentValueText = backend.currentValue
            root.statsText = backend.statsText
        }
    }

    // 左侧：当前值 + 统计 + 日志
    ColumnLayout {
        Layout.preferredWidth: 280
        Layout.fillHeight: true
        spacing: Fluent.spacingS

        Frame {
            Layout.fillWidth: true
            ColumnLayout {
                width: parent.width
                spacing: 4
                Label {
                    text: "当前数据"
                    font.pixelSize: Fluent.fontCaptionSize
                    color: Fluent.textSecondary
                }
                Label {
                    text: root.currentValueText
                    font.pixelSize: Fluent.fontBodyLargeSize; font.bold: true
                    color: Fluent.textPrimary
                    wrapMode: Text.Wrap
                    Layout.fillWidth: true
                }
            }
        }

        Frame {
            Layout.fillWidth: true
            ColumnLayout {
                width: parent.width
                spacing: 4
                Label {
                    text: "统计"
                    font.pixelSize: Fluent.fontCaptionSize
                    color: Fluent.textSecondary
                }
                Label {
                    text: root.statsText
                    font.pixelSize: Fluent.fontCaptionSize
                    color: Fluent.textPrimary
                    wrapMode: Text.Wrap
                    Layout.fillWidth: true
                }
            }
        }

        Frame {
            Layout.fillWidth: true; Layout.fillHeight: true
            ColumnLayout {
                width: parent.width; anchors.fill: parent
                spacing: 4
                Label {
                    text: "日志"
                    font.pixelSize: Fluent.fontCaptionSize
                    color: Fluent.textSecondary
                }
                ScrollView {
                    Layout.fillWidth: true; Layout.fillHeight: true
                    TextArea {
                        readOnly: true
                        text: backend ? backend.logText : ""
                        font.family: "Consolas"
                        font.pixelSize: 10
                        wrapMode: Text.Wrap
                        background: Rectangle { color: "transparent" }
                    }
                }
            }
        }
    }

    // 右侧：图表
    Frame {
        Layout.fillWidth: true; Layout.fillHeight: true
        ChartItem {
            id: chart
            anchors.fill: parent
            anchors.margins: 8
            Component.onCompleted: {
                chart.setLabels(root.xLabel, root.yLabel)
            }
        }
    }

    function refreshChart() {
        if (!backend) return
        var xs = backend.timeData()
        var ys = backend.valueData()
        if (xs.length > 0) {
            // 深浅色自适应曲线颜色
            var curveColor = Fluent.isDark ? "#60cdff" : "#005fb8"
            chart.setData(xs, ys, curveColor, "default")
            // 自动滚动：保留最近 200 个点
            if (xs.length > 200) {
                chart.setXRange(xs[xs.length-200], xs[xs.length-1])
            }
        }
    }
}
