// ultrasonic_displacement.qml — 超声波位移模块视图
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
            text: "超声波位移传感器"
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
            yLabel: "距离 (cm)"
        }

        ActionBar {
            Layout.fillWidth: true
            backend: root.backend
        }
    }
}
