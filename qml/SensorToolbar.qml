// SensorToolbar.qml — 串口工具栏（端口选择 + 刷新 + 连接 + 采样率）
import QtQuick
import QtQuick.Controls
import QtQuick.Layouts
import FluentTheme 1.0

RowLayout {
    id: root
    property var backend: null
    spacing: Fluent.spacingS

    Label {
        text: "串口:"
        color: Fluent.textPrimary
    }
    ComboBox {
        id: portCombo
        model: backend ? backend.ports : []
        Layout.preferredWidth: 180
        enabled: backend && !backend.connected
    }
    Button {
        text: "刷新"
        enabled: backend && !backend.connected
        onClicked: if (backend) backend.refreshPorts()
    }
    Button {
        text: backend && backend.connected ? "断开" : "连接"
        highlighted: !(backend && backend.connected)
        onClicked: {
            if (!backend) return
            if (backend.connected) {
                backend.disconnectPort()
            } else {
                backend.connectPort(portCombo.currentText)
            }
        }
    }

    Item { Layout.fillWidth: true }

    Label {
        text: "采样:"
        color: Fluent.textSecondary
    }
    Label {
        text: backend ? (backend.sampleRateHz + " Hz") : "—"
        color: Fluent.accent
        font.bold: true
    }
    Label {
        text: "状态:"
        color: Fluent.textSecondary
    }
    Label {
        text: backend && backend.collecting ? "采集中" : "停止"
        color: backend && backend.collecting ? Fluent.critical : Fluent.textSecondary
        font.bold: true
    }
}
