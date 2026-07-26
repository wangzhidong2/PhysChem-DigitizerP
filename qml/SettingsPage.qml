// SettingsPage.qml — 设置页
import QtQuick
import QtQuick.Controls
import QtQuick.Layouts
import FluentTheme 1.0

Item {
    id: root

    ScrollView {
        anchors.fill: parent
        anchors.margins: 24
        clip: true

        ColumnLayout {
            width: parent.width
            spacing: 16

            Label {
                text: "设置"
                font.pixelSize: Fluent.fontTitleSize; font.bold: true
                color: Fluent.textPrimary
                Layout.bottomMargin: 4
            }

            Frame {
                Layout.fillWidth: true
                ColumnLayout {
                    width: parent.width
                    spacing: 10

                    Label {
                        text: "关于软件"
                        font.pixelSize: Fluent.fontBodyStrongSize; font.bold: true
                        color: Fluent.textPrimary
                    }
                    Label {
                        text: "PhysChem-DigitizerP v2.0.0\n"
                            + "QtQuick + FluentPySide（WinUI3 风格）+ pyqtgraph\n"
                            + "GPL-3.0 协议开源\n"
                            + "模块化架构：新增传感器只需丢文件，无需修改主程序"
                        wrapMode: Text.Wrap
                        font.pixelSize: Fluent.fontCaptionSize
                        color: Fluent.textSecondary
                    }
                }
            }

            Frame {
                Layout.fillWidth: true
                ColumnLayout {
                    width: parent.width
                    spacing: 10

                    Label {
                        text: "主题"
                        font.pixelSize: Fluent.fontBodyStrongSize; font.bold: true
                        color: Fluent.textPrimary
                    }
                    Label {
                        text: "本版本使用 FluentWinUI3 风格，"
                            + "跟随系统主题（当前：" + (Fluent.isDark ? "深色" : "浅色") + "）。"
                        font.pixelSize: Fluent.fontCaptionSize
                        color: Fluent.textSecondary
                    }
                }
            }

            Frame {
                Layout.fillWidth: true
                ColumnLayout {
                    width: parent.width
                    spacing: 10

                    Label {
                        text: "项目链接"
                        font.pixelSize: Fluent.fontBodyStrongSize; font.bold: true
                        color: Fluent.textPrimary
                    }
                    Button {
                        text: "GitHub 仓库"
                        onClicked: Qt.openUrlExternally(
                            "https://github.com/wangzhidong2/PhysChem-DigitizerP")
                    }
                    Button {
                        text: "Gitee 仓库"
                        onClicked: Qt.openUrlExternally(
                            "https://gitee.com/wangzhidong2/PhysChem-DigitizerP/")
                    }
                    Button {
                        text: "提交 Issue"
                        onClicked: Qt.openUrlExternally(
                            "https://github.com/wangzhidong2/PhysChem-DigitizerP/issues")
                    }
                }
            }

            Item { Layout.fillHeight: true; Layout.minimumHeight: 24 }
        }
    }
}
