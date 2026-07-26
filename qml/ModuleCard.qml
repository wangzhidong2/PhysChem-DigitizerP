// ModuleCard.qml — 模块卡片按钮
import QtQuick
import QtQuick.Controls
import FluentTheme 1.0

Button {
    id: root
    property string iconText: "?"
    property string titleText: "Module"

    implicitHeight: 64
    flat: true

    background: Rectangle {
        color: root.hovered ? Fluent.controlAltBackgroundHover : Fluent.cardBackground
        border.color: Fluent.border
        border.width: 1
        radius: Fluent.radiusMedium
    }

    contentItem: Row {
        spacing: 10
        anchors.fill: parent
        anchors.margins: 10

        Rectangle {
            width: 40; height: 40; radius: Fluent.radiusSmall
            color: Fluent.accentSelected
            anchors.verticalCenter: parent.verticalCenter
            Label {
                anchors.centerIn: parent
                text: root.iconText
                font.pixelSize: 16
                color: Fluent.accent
            }
        }
        Label {
            text: root.titleText
            anchors.verticalCenter: parent.verticalCenter
            font.pixelSize: Fluent.fontCaptionSize
            color: Fluent.textPrimary
        }
        Item { width: 1; height: 1 }
    }
}
