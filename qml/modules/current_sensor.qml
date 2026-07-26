// current_sensor.qml — 电流传感器模块视图（ACS712）
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
            text: "电流传感器 (ACS712)"
            font.pixelSize: 20; font.bold: true
        }

        SensorToolbar {
            Layout.fillWidth: true
            backend: root.backend
        }

        // ACS712 配置区
        RowLayout {
            Layout.fillWidth: true
            spacing: 8

            Label { text: "量程:" }
            ComboBox {
                id: rangeCombo
                model: ["5A", "20A", "30A"]
                enabled: backend && !backend.collecting
                onActivated: {
                    if (backend) backend.setAcsRange(parseInt(currentText))
                }
                Component.onCompleted: {
                    if (backend) {
                        var r = backend.acsRange
                        currentIndex = (r === 20) ? 1 : (r === 30) ? 2 : 0
                    }
                }
            }

            Label { text: "模式:" }
            ComboBox {
                id: modeCombo
                model: ["DC", "AC"]
                enabled: backend && !backend.collecting
                onActivated: if (backend) backend.setCurrentMode(currentText)
            }

            Label { text: "单位:" }
            ComboBox {
                id: unitCombo
                model: ["A", "mA"]
                onActivated: if (backend) backend.setCurrentUnit(currentText)
                Component.onCompleted: {
                    if (backend) {
                        currentIndex = (backend.currentUnit === "mA") ? 1 : 0
                    }
                }
            }

            Label { text: "分压比:" }
            TextField {
                id: dividerField
                text: "1.0"
                Layout.preferredWidth: 80
                horizontalAlignment: TextInput.AlignHCenter
                validator: DoubleValidator { bottom: 0.1; top: 10.0; decimals: 3 }
            }
            Button {
                text: "设置"
                enabled: backend && !backend.collecting
                onClicked: {
                    if (backend) backend.setDividerRatio(parseFloat(dividerField.text))
                }
            }

            Button {
                text: "零点校准"
                highlighted: true
                enabled: backend && backend.connected
                onClicked: if (backend) backend.performZeroCalibration()
            }

            Item { Layout.fillWidth: true }
        }

        ChartPanel {
            Layout.fillWidth: true
            Layout.fillHeight: true
            backend: root.backend
            xLabel: "时间 (s)"
            yLabel: backend ? "电流 (" + backend.currentUnit + ")" : "电流 (A)"
        }

        ActionBar {
            Layout.fillWidth: true
            backend: root.backend
        }
    }
}
