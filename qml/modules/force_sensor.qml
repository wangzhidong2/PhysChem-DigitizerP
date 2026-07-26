// force_sensor.qml — 力传感器模块视图（HX711）
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
            text: "力传感器（HX711）"
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
            // yLabel 根据当前单位动态切换
            yLabel: {
                var u = root.backend ? root.backend.currentUnit : "g"
                if (u === "kg") return "质量 (kg)"
                if (u === "N") return "力 (N)"
                return "质量 (g)"
            }
        }

        // 校准 / 去皮 / 单位 控制行（位于 ActionBar 上方）
        RowLayout {
            Layout.fillWidth: true
            spacing: 8

            Label { text: "校准系数:" }
            TextField {
                id: calibInput
                text: root.backend ? String(root.backend.calibrationFactor) : "1.0"
                placeholderText: "1.0"
                Layout.preferredWidth: 120
                selectByMouse: true
                validator: DoubleValidator { bottom: 0.0; notation: DoubleValidator.StandardNotation }
            }
            Button {
                text: "设置"
                enabled: root.backend !== null
                onClicked: {
                    if (!root.backend) return
                    var v = parseFloat(calibInput.text)
                    if (!isNaN(v)) root.backend.setCalibrationFactor(v)
                }
            }

            Button {
                text: "去皮"
                enabled: root.backend !== null
                onClicked: if (root.backend) root.backend.performTare()
            }

            Item { Layout.fillWidth: true }

            Label { text: "单位:" }
            ComboBox {
                id: unitCombo
                model: ["g", "kg", "N"]
                currentIndex: {
                    if (!root.backend) return 0
                    var u = root.backend.currentUnit
                    return ["g", "kg", "N"].indexOf(u)
                }
                onActivated: {
                    if (root.backend) root.backend.setUnit(currentText)
                }
            }
        }

        ActionBar {
            Layout.fillWidth: true
            backend: root.backend
        }
    }
}
