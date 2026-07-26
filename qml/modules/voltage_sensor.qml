// voltage_sensor.qml — 电压传感器模块视图
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
            text: "电压传感器"
            font.pixelSize: 20; font.bold: true
        }

        SensorToolbar {
            Layout.fillWidth: true
            backend: root.backend
        }

        // ===== 配置区：ADC 模式 / HX711 通道增益 / 分压比 / 放大倍数 / 单位 / 去皮 =====
        RowLayout {
            Layout.fillWidth: true
            spacing: 8

            Label { text: "ADC 模式:" }
            ComboBox {
                id: adcModeCombo
                model: ["ESP32", "HX711"]
                currentIndex: (backend && backend.adcMode === "hx711") ? 1 : 0
                enabled: backend && !backend.collecting
                onActivated: if (backend) {
                    backend.setAdcMode(currentIndex === 1 ? "hx711" : "esp32")
                }
            }

            // HX711 模式才显示：通道 + 增益
            Label { text: "通道:"; visible: adcModeCombo.currentIndex === 1 }
            ComboBox {
                id: channelCombo
                model: ["A", "B"]
                currentIndex: (backend && backend.hx711Channel === "B") ? 1 : 0
                visible: adcModeCombo.currentIndex === 1
                enabled: backend && !backend.collecting
                onActivated: if (backend) backend.setHx711Channel(currentText)
            }

            Label { text: "增益:"; visible: adcModeCombo.currentIndex === 1 }
            ComboBox {
                id: gainCombo
                model: [128, 32]
                currentIndex: (backend && backend.hx711Gain === 32) ? 1 : 0
                visible: adcModeCombo.currentIndex === 1
                enabled: backend && !backend.collecting
                onActivated: if (backend) backend.setHx711Gain(parseInt(currentText))
            }

            // 分压比
            Label { text: "分压比:" }
            TextField {
                id: dividerField
                text: backend ? backend.dividerRatio.toString() : "1.0"
                Layout.preferredWidth: 80
                horizontalAlignment: Text.AlignHCenter
                validator: DoubleValidator { bottom: 0.001; top: 1000.0; decimals: 3 }
            }
            Button {
                text: "设置"
                enabled: backend && !backend.collecting
                onClicked: if (backend) {
                    var v = parseFloat(dividerField.text)
                    if (!isNaN(v) && v > 0) backend.setDividerRatio(v)
                }
            }

            // 放大倍数
            Label { text: "放大倍数:" }
            TextField {
                id: ampField
                text: backend ? backend.amplifierGain.toString() : "1.0"
                Layout.preferredWidth: 80
                horizontalAlignment: Text.AlignHCenter
                validator: DoubleValidator { bottom: 0.001; top: 1000.0; decimals: 3 }
            }
            Button {
                text: "设置"
                enabled: backend && !backend.collecting
                onClicked: if (backend) {
                    var v = parseFloat(ampField.text)
                    if (!isNaN(v) && v > 0) backend.setAmplifierGain(v)
                }
            }

            // 单位
            Label { text: "单位:" }
            ComboBox {
                id: unitCombo
                model: ["kV", "V", "mV"]
                currentIndex: {
                    if (!backend) return 1
                    if (backend.currentUnit === "kV") return 0
                    if (backend.currentUnit === "mV") return 2
                    return 1
                }
                onActivated: if (backend) backend.setUnit(currentText)
            }

            // 去皮
            Button {
                text: "去皮"
                highlighted: true
                enabled: backend && backend.connected
                onClicked: if (backend) backend.performTare()
            }

            Item { Layout.fillWidth: true }
        }

        ChartPanel {
            Layout.fillWidth: true
            Layout.fillHeight: true
            backend: root.backend
            xLabel: "时间 (s)"
            yLabel: {
                var u = backend ? backend.currentUnit : "V"
                return "电压 (" + u + ")"
            }
        }

        ActionBar {
            Layout.fillWidth: true
            backend: root.backend
        }
    }
}
