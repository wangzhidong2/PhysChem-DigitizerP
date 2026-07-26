// ultrasonic_velocity.qml — 超声波速度模块视图
import QtQuick
import QtQuick.Controls
import QtQuick.Layouts
import Charts 1.0
import ".."

Item {
    id: root
    property var backend: null

    ColumnLayout {
        anchors.fill: parent
        anchors.margins: 16
        spacing: 12

        // 标题
        Label {
            text: "超声波速度传感器"
            font.pixelSize: 20; font.bold: true
        }

        SensorToolbar {
            Layout.fillWidth: true
            backend: root.backend
        }

        ChartPanel {
            Layout.fillWidth: true
            Layout.fillHeight: true
            backend: root.backend
            xLabel: "时间 (s)"
            yLabel: "速度 (cm/s)"
        }

        // 采样窗口设置
        RowLayout {
            Layout.fillWidth: true
            spacing: 8

            Label { text: "采样窗口:" }
            SpinBox {
                id: windowSpin
                from: 5
                to: 100
                value: 10
                onValueModified: if (root.backend) root.backend.setWindowSize(value)
            }
            Label { text: "点" }
            Item { Layout.fillWidth: true }
        }

        ActionBar {
            Layout.fillWidth: true
            backend: root.backend
        }
    }
}
