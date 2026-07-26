// ModuleView.qml — 通用模块视图模板
// 各模块 QML 顶层用本组件，只需指定 backend、xLabel、yLabel、extraControls
import QtQuick
import QtQuick.Controls
import QtQuick.Layouts

Item {
    id: root
    property var backend: null
    property string xLabel: "时间 (s)"
    property string yLabel: "数值"
    property Component extraControls: null

    ColumnLayout {
        anchors.fill: parent
        anchors.margins: 16
        spacing: 12

        SensorToolbar {
            Layout.fillWidth: true
            backend: root.backend
        }

        ChartPanel {
            Layout.fillWidth: true
            Layout.fillHeight: true
            backend: root.backend
            xLabel: root.xLabel
            yLabel: root.yLabel
        }

        ActionBar {
            Layout.fillWidth: true
            backend: root.backend
            extraControls: root.extraControls
        }
    }
}
