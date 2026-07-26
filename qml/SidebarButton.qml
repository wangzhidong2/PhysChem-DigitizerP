// SidebarButton.qml — 侧边栏按钮（图标 + 文字 + 选中指示条）
import QtQuick
import QtQuick.Controls
import FluentTheme 1.0

Button {
    id: root
    property string iconText: "?"
    property string labelText: "Item"
    property bool selected: false

    implicitHeight: 44
    checked: selected
    checkable: true
    flat: true

    background: Rectangle {
        color: root.selected ? Fluent.accentSelected
                              : (root.hovered ? Fluent.controlAltBackgroundHover
                                              : "transparent")
        radius: Fluent.radiusMedium
        // 左侧选中指示条（较短、居中）
        Rectangle {
            width: 3; height: parent.height - 16
            anchors.verticalCenter: parent.verticalCenter
            anchors.left: parent.left; anchors.leftMargin: 4
            color: Fluent.accent
            visible: root.selected
            radius: 2
        }
    }

    contentItem: Row {
        spacing: 10
        anchors.fill: parent
        anchors.leftMargin: 12
        Item {
            width: 24; height: parent.height
            Label {
                anchors.centerIn: parent
                text: root.iconText
                font.pixelSize: 16
                color: Fluent.textPrimary
            }
        }
        Label {
            text: root.labelText
            anchors.verticalCenter: parent.verticalCenter
            color: root.selected ? Fluent.accent : Fluent.textPrimary
            font.pixelSize: 13
            font.bold: root.selected
        }
    }
}
