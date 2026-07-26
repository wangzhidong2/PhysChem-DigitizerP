// HomePage.qml — 主页：项目卡片 + 物理模块网格 + 化学模块网格
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
                text: "主页"
                font.pixelSize: Fluent.fontTitleSize; font.bold: true
                color: Fluent.textPrimary
                Layout.bottomMargin: 4
            }

            // ============ 项目信息卡 ============
            Frame {
                Layout.fillWidth: true
                Layout.margins: 0
                ColumnLayout {
                    width: parent.width
                    spacing: 12

                    RowLayout {
                        spacing: 16
                        Rectangle {
                            width: 64; height: 64; radius: Fluent.radiusLarge
                            color: Fluent.accentSelected
                            Label {
                                anchors.centerIn: parent
                                text: "🔬"
                                font.pixelSize: 32
                            }
                        }
                        ColumnLayout {
                            spacing: 2
                            Label {
                                text: "PhysChem-DigitizerP"
                                font.pixelSize: Fluent.fontBodyLargeSize; font.bold: true
                                color: Fluent.textPrimary
                            }
                            Label {
                                text: "版本 2.0.0 | GPL-3.0 | QML + FluentPySide | pyqtgraph"
                                font.pixelSize: Fluent.fontCaptionSize
                                color: Fluent.textSecondary
                            }
                        }
                        Item { Layout.fillWidth: true }
                        Button {
                            text: "  GitHub"
                            highlighted: true
                            onClicked: Qt.openUrlExternally(
                                "https://github.com/wangzhidong2/PhysChem-DigitizerP")
                        }
                    }

                    Label {
                        text: "基于 Arduino/ESP32 的低成本理化实验数字化采集系统，"
                            + "为中学和大学物理/化学实验室提供低成本、高精度的传感器解决方案。"
                        wrapMode: Text.Wrap
                        font.pixelSize: Fluent.fontCaptionSize
                        color: Fluent.textSecondary
                        Layout.fillWidth: true
                    }
                }
            }

            // ============ 模块网格（物理 + 化学并排）============
            RowLayout {
                Layout.fillWidth: true
                spacing: 16

                // 物理模块
                Frame {
                    Layout.fillWidth: true; Layout.preferredWidth: 1
                    Layout.minimumHeight: 200
                    ColumnLayout {
                        width: parent.width
                        spacing: 8
                        Label {
                            text: "⚛️ 物理实验模块"
                            font.pixelSize: Fluent.fontBodyStrongSize; font.bold: true
                            color: Fluent.textPrimary
                        }
                        Label {
                            text: qsTr("%1 个模块").arg(
                                physicsModel ? physicsModel.count : 0)
                            font.pixelSize: Fluent.fontCaptionSize
                            color: Fluent.textSecondary
                        }

                        GridLayout {
                            columns: 2
                            columnSpacing: 8; rowSpacing: 8
                            Layout.fillWidth: true

                            Repeater {
                                model: physicsModel
                                delegate: ModuleCard {
                                    Layout.fillWidth: true
                                    iconText: model.icon
                                    titleText: model.name
                                    onClicked: {
                                        currentIndex = model.index
                                        currentPage = "module"
                                        var b = backendsMap[model.backendKey]
                                        if (b) b.refreshPorts()
                                    }
                                }
                            }
                        }
                    }
                }

                // 化学模块
                Frame {
                    Layout.fillWidth: true; Layout.preferredWidth: 1
                    Layout.minimumHeight: 200
                    ColumnLayout {
                        width: parent.width
                        spacing: 8
                        Label {
                            text: "🧪 化学实验模块"
                            font.pixelSize: Fluent.fontBodyStrongSize; font.bold: true
                            color: Fluent.textPrimary
                        }
                        Label {
                            text: qsTr("%1 个模块").arg(
                                chemistryModel ? chemistryModel.count : 0)
                            font.pixelSize: Fluent.fontCaptionSize
                            color: Fluent.textSecondary
                        }

                        GridLayout {
                            columns: 2
                            columnSpacing: 8; rowSpacing: 8
                            Layout.fillWidth: true

                            Repeater {
                                model: chemistryModel
                                delegate: ModuleCard {
                                    Layout.fillWidth: true
                                    iconText: model.icon
                                    titleText: model.name
                                    onClicked: {
                                        currentIndex = model.index
                                        currentPage = "module"
                                        var b = backendsMap[model.backendKey]
                                        if (b) b.refreshPorts()
                                    }
                                }
                            }
                        }
                    }
                }
            }

            Item { Layout.fillHeight: true; Layout.minimumHeight: 24 }
        }
    }
}
