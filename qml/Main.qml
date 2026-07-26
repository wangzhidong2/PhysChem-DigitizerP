// Main.qml — 主窗口：侧边栏 + 主区域
import QtQuick
import QtQuick.Controls
import QtQuick.Layouts
import FluentTheme 1.0

ApplicationWindow {
    id: root
    visible: true
    width: 1280; height: 800
    minimumWidth: 960; minimumHeight: 600
    title: "PhysChem-DigitizerP"
    color: Fluent.background

    // 由 main.py 注入：modulesModel / physicsModel / chemistryModel / backendsMap

    property int currentIndex: 0
    property string currentPage: "home"  // "home" / "settings" / "module"

    // 当前激活的 Backend（用于错误提示）
    property var currentBackend: (currentPage === "module"
                                  && modulesModel
                                  && modulesModel.count > 0
                                  && backendsMap)
        ? backendsMap[modulesModel.get(currentIndex).backendKey]
        : null

    RowLayout {
        anchors.fill: parent
        spacing: 0

        // ============= 侧边栏 =============
        Rectangle {
            Layout.fillHeight: true
            Layout.preferredWidth: 220
            color: Fluent.layerAltBackground  // 侧边栏使用稍浅的图层背景

            ColumnLayout {
                anchors.fill: parent
                anchors.margins: 12
                spacing: 8

                Label {
                    text: "🔬 PhysChem"
                    font.pixelSize: 18; font.bold: true
                    color: Fluent.textPrimary
                    Layout.topMargin: 8
                    Layout.leftMargin: 8
                }
                Label {
                    text: "DigitizerP v2.0"
                    font.pixelSize: 11
                    color: Fluent.textSecondary
                    Layout.leftMargin: 8
                    Layout.bottomMargin: 12
                }

                SidebarButton {
                    iconText: "🏠"
                    labelText: "主页"
                    selected: currentPage === "home"
                    onClicked: currentPage = "home"
                    Layout.fillWidth: true
                }

                Repeater {
                    model: modulesModel
                    delegate: SidebarButton {
                        iconText: model.icon
                        labelText: model.name
                        selected: currentPage === "module" && currentIndex === model.index
                        onClicked: {
                            currentIndex = model.index
                            currentPage = "module"
                            var b = backendsMap[model.backendKey]
                            if (b) b.refreshPorts()
                        }
                        Layout.fillWidth: true
                    }
                }

                Item { Layout.fillHeight: true }

                SidebarButton {
                    iconText: "⚙️"
                    labelText: "设置"
                    selected: currentPage === "settings"
                    onClicked: currentPage = "settings"
                    Layout.fillWidth: true
                }
            }
        }

        // ============= 主区域 =============
        Rectangle {
            Layout.fillWidth: true; Layout.fillHeight: true
            color: Fluent.background

            StackLayout {
                id: stack
                anchors.fill: parent
                currentIndex: currentPage === "home" ? 0 :
                              currentPage === "settings" ? 1 : 2

                HomePage { id: homePage }

                SettingsPage { id: settingsPage }

                Item {
                    id: moduleContainer
                    Loader {
                        id: moduleLoader
                        anchors.fill: parent
                        source: (modulesModel && modulesModel.count > 0 && currentPage === "module")
                                ? modulesModel.get(currentIndex).qmlPath
                                : ""
                        onLoaded: {
                            if (item) {
                                var key = modulesModel.get(currentIndex).backendKey
                                item.backend = backendsMap[key]
                            }
                        }
                    }
                }
            }
        }
    }

    // 监听当前 Backend 的错误信号
    Connections {
        target: root.currentBackend
        function onErrorOccurred(msg) {
            errorDialog.text = msg
            errorDialog.open()
        }
    }

    Dialog {
        id: errorDialog
        title: "错误"
        modal: true
        anchors.centerIn: parent
        standardButtons: Dialog.Ok
        property string text: ""
        Label { text: errorDialog.text; wrapMode: Text.Wrap }
    }
}
