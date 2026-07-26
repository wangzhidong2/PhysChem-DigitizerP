// ActionBar.qml — 操作按钮栏（开始/停止/保存/清除 + 模块自定义控件占位）
import QtQuick
import QtQuick.Controls
import QtQuick.Layouts
import QtQuick.Dialogs as D

RowLayout {
    id: root
    property var backend: null
    property var extraControls: null  // 模块可注入额外按钮
    spacing: 8

    Button {
        text: "开始采集"
        highlighted: true
        enabled: backend && backend.connected && !backend.collecting
        onClicked: if (backend) backend.startCollecting()
    }
    Button {
        text: "停止采集"
        enabled: backend && backend.collecting
        onClicked: if (backend) backend.stopCollecting()
    }
    Button {
        text: "保存数据"
        enabled: backend && backend.valueData().length > 0
                  && !(backend && backend.collecting)
        onClicked: saveDialog.open()
    }
    Button {
        text: "清除数据"
        onClicked: if (backend) backend.clearData()
    }

    // 模块特有控件
    Loader { sourceComponent: root.extraControls }

    Item { Layout.fillWidth: true }

    D.FileDialog {
        id: saveDialog
        title: "保存数据"
        fileMode: D.FileDialog.SaveFile
        defaultSuffix: "csv"
        nameFilters: ["CSV 文件 (*.csv)", "所有文件 (*)"]
        onAccepted: if (backend) backend.saveData(currentFile.toString().replace("file://", ""))
    }
}
