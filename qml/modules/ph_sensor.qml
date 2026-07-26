// ph_sensor.qml — pH 传感器模块视图
import QtQuick
import QtQuick.Controls
import QtQuick.Layouts
import Charts 1.0
import FluentTheme 1.0
import ".."

Item {
    id: root
    property var backend: null

    // 校准模式名称映射
    function modeName(m) {
        if (m === 1) return "单点校准"
        if (m === 2) return "两点校准"
        if (m === 3) return "三点校准"
        return String(m) + "点校准"
    }

    // 各模式默认校准点 [[ph, adc], ...]
    function defaultPoints(m) {
        if (m === 1) return [[7.00, 2281]]
        if (m === 2) return [[4.00, 2555], [9.18, 2030]]
        return [[4.00, 2555], [6.86, 2281], [9.18, 2030]]
    }

    ColumnLayout {
        anchors.fill: parent
        anchors.margins: 16
        spacing: 12

        // 标题
        Label {
            text: "pH 传感器"
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
            yLabel: "pH 值"
        }

        // 校准按钮行（ActionBar 上方）
        RowLayout {
            Layout.fillWidth: true
            spacing: 8

            Label { text: "校准:" }
            Label {
                text: backend ? root.modeName(backend.calibrationMode) : ""
                color: Fluent.success; font.bold: true
            }

            Button {
                text: "✏️ 编辑校准"
                enabled: backend !== null
                onClicked: calibDialog.open()
            }

            Item { Layout.fillWidth: true }
        }

        ActionBar {
            Layout.fillWidth: true
            backend: root.backend
        }
    }

    // ============= 校准对话框 =============
    Dialog {
        id: calibDialog
        title: "pH 校准参数"
        modal: true
        anchors.centerIn: parent
        width: 380
        standardButtons: Dialog.Ok | Dialog.Cancel

        // 对话框内部编辑状态
        property int selMode: 3
        property var points: [[4.0, 2555], [6.86, 2281], [9.18, 2030]]

        onOpened: {
            if (!backend) return
            selMode = backend.getCalibrationMode()
            var pts = []
            for (var i = 0; i < 3; i++) {
                var p = backend.getCalibrationPoint(i)
                if (p && p.length === 2) {
                    pts.push([p[0], p[1]])
                } else {
                    pts.push([4.0, 2555])
                }
            }
            points = pts
        }

        onAccepted: {
            if (!backend) return
            // 1. 设置模式（重置为默认点）
            backend.setCalibrationMode(selMode)
            // 2. 逐个覆写为对话框中的值
            for (var i = 0; i < selMode; i++) {
                if (points[i] && points[i].length === 2) {
                    backend.setCalibrationPoint(i, points[i][0], points[i][1])
                }
            }
            // 3. 持久化
            backend.saveCalibration()
        }

        contentItem: ColumnLayout {
            spacing: 12

            // ----- 模式选择 -----
            RowLayout {
                spacing: 12
                Label { text: "校准模式:"; font.bold: true }
                RadioButton {
                    text: "单点"
                    checked: calibDialog.selMode === 1
                    onClicked: {
                        if (calibDialog.selMode === 1) return
                        calibDialog.selMode = 1
                        var d = root.defaultPoints(1)
                        for (var i = 0; i < d.length; i++) calibDialog.points[i] = d[i]
                    }
                }
                RadioButton {
                    text: "两点"
                    checked: calibDialog.selMode === 2
                    onClicked: {
                        if (calibDialog.selMode === 2) return
                        calibDialog.selMode = 2
                        var d = root.defaultPoints(2)
                        for (var i = 0; i < d.length; i++) calibDialog.points[i] = d[i]
                    }
                }
                RadioButton {
                    text: "三点"
                    checked: calibDialog.selMode === 3
                    onClicked: {
                        if (calibDialog.selMode === 3) return
                        calibDialog.selMode = 3
                        var d = root.defaultPoints(3)
                        for (var i = 0; i < d.length; i++) calibDialog.points[i] = d[i]
                    }
                }
            }

            // ----- 校准点输入（Repeater 生成 3 行，按模式显隐） -----
            Repeater {
                model: 3
                delegate: RowLayout {
                    Layout.fillWidth: true
                    visible: calibDialog.selMode >= (index + 1)
                    spacing: 8

                    Label { text: "点 " + (index + 1) + ":"; Layout.preferredWidth: 40 }
                    Label { text: "pH" }
                    TextField {
                        Layout.preferredWidth: 80
                        horizontalAlignment: Text.AlignHCenter
                        text: {
                            var p = calibDialog.points[index]
                            return p ? Number(p[0]).toFixed(2) : ""
                        }
                        validator: DoubleValidator { bottom: 0.0; top: 14.0; decimals: 2 }
                        onTextEdited: {
                            var v = parseFloat(text)
                            if (!isNaN(v) && calibDialog.points[index]) {
                                calibDialog.points[index][0] = v
                            }
                        }
                    }
                    Label { text: "ADC" }
                    TextField {
                        Layout.preferredWidth: 80
                        horizontalAlignment: Text.AlignHCenter
                        text: {
                            var p = calibDialog.points[index]
                            return p ? Math.round(p[1]) : ""
                        }
                        validator: IntValidator { bottom: 0; top: 4095 }
                        onTextEdited: {
                            var v = parseInt(text)
                            if (!isNaN(v) && calibDialog.points[index]) {
                                calibDialog.points[index][1] = v
                            }
                        }
                    }
                }
            }
        }
    }
}
