import QtQuick
import QtQuick.Layouts
import QtQuick.Controls
import Quickshell
import qs.Commons
import qs.Widgets
import qs.Services.UI

Item {
    id: root

    property var pluginApi: null
    property ShellScreen screen
    readonly property var geometryPlaceholder: panelContainer
    readonly property bool allowAttach: true
    readonly property var mainInstance: pluginApi ? pluginApi.mainInstance : null

    property bool panelReady: true
    property real contentPreferredWidth: 410 * Style.uiScaleRatio
    property real contentPreferredHeight: 510 * Style.uiScaleRatio

    readonly property bool camRunning: mainInstance ? mainInstance.camRunning : false
    readonly property string camMode: mainInstance ? mainInstance.camMode : "snap"
    readonly property string camPhase: mainInstance ? mainInstance.camPhase : "off"
    readonly property bool gesturesPaused: mainInstance ? mainInstance.gesturesPaused : false
    readonly property bool previewVisible: mainInstance ? mainInstance.previewVisible : true
    readonly property string snapMessage: mainInstance ? mainInstance.snapMessage : "BRB..."

    readonly property bool isVanished: camRunning && (camPhase === "vanished" || camPhase.indexOf("vanish") !== -1 || camPhase.indexOf("disappear") !== -1)

    readonly property var modesModel: [
        { id: "snap", label: "Snap Void" },
        { id: "naruto", label: "Naruto Log" },
        { id: "normal", label: "Dissolve" },
        { id: "particles", label: "Particles" },
        { id: "itachi", label: "Itachi Crows" },
        { id: "goku", label: "Goku Teleport" }
    ]

    readonly property var excusesModel: [
        "BRB...",
        "GONE",
        "AFK",
        "MY INTERNET DIED",
        "IN A MEETING"
    ]

    anchors.fill: parent

    Rectangle {
        id: panelContainer
        anchors.fill: parent
        color: "transparent"
        visible: panelReady

        ColumnLayout {
            anchors.fill: parent
            anchors.margins: Style.marginM
            spacing: Style.marginM

            // 1. Header & Power Card
            NBox {
                Layout.fillWidth: true
                implicitHeight: headerRow.implicitHeight + Style.marginM * 2
                color: Color.mSurfaceVariant

                RowLayout {
                    id: headerRow
                    anchors.fill: parent
                    anchors.margins: Style.marginM
                    spacing: Style.marginM

                    Rectangle {
                        width: 40 * Style.uiScaleRatio
                        height: 40 * Style.uiScaleRatio
                        radius: Style.radiusM
                        color: root.camRunning
                            ? (root.isVanished ? Qt.alpha(Color.mSecondary, 0.22) : Qt.alpha(Color.mPrimary, 0.22))
                            : Color.mSurface

                        NIcon {
                            anchors.centerIn: parent
                            icon: !root.camRunning ? "video-off" : (root.isVanished ? "eye-off" : "video")
                            pointSize: Style.fontSizeL
                            color: !root.camRunning ? Color.mOnSurfaceVariant : (root.isVanished ? Color.mSecondary : Color.mPrimary)
                        }
                    }

                    ColumnLayout {
                        Layout.fillWidth: true
                        spacing: 2

                        NText {
                            text: "VanishCam Studio"
                            pointSize: Style.fontSizeL
                            font.bold: true
                            color: Color.mOnSurface
                        }

                        NText {
                            text: !root.camRunning
                                ? "Stopped (/dev/video2 idle)"
                                : ("Active: " + root.camMode.toUpperCase() + "  ·  Phase: " + root.camPhase.toUpperCase())
                            pointSize: Style.fontSizeXS
                            color: root.camRunning ? Color.mPrimary : Color.mOnSurfaceVariant
                        }
                    }

                    NButton {
                        text: root.camRunning ? "Stop" : "Start"
                        outlined: false
                        backgroundColor: root.camRunning ? Color.mError : Color.mPrimary
                        textColor: root.camRunning ? Color.mOnError : Color.mOnPrimary
                        onClicked: {
                            if (mainInstance) mainInstance.togglePower();
                        }
                    }
                }
            }

            // 2. Primary Meeting Controls
            NBox {
                Layout.fillWidth: true
                implicitHeight: actionCol.implicitHeight + Style.marginM * 2
                color: Color.mSurfaceVariant

                ColumnLayout {
                    id: actionCol
                    anchors.fill: parent
                    anchors.margins: Style.marginM
                    spacing: Style.marginS

                    NButton {
                        Layout.fillWidth: true
                        text: !root.camRunning
                            ? "Start & Ready Camera"
                            : (root.isVanished ? "Reappear Smoothly Now (R)" : "Vanish Now (V)")
                        outlined: false
                        backgroundColor: !root.camRunning
                            ? Color.mSurface
                            : (root.isVanished ? Color.mSecondary : Color.mPrimary)
                        textColor: !root.camRunning
                            ? Color.mOnSurface
                            : (root.isVanished ? Color.mOnSecondary : Color.mOnPrimary)
                        onClicked: {
                            if (mainInstance) mainInstance.triggerAction();
                        }
                    }

                    RowLayout {
                        Layout.fillWidth: true
                        spacing: Style.marginS

                        NButton {
                            Layout.fillWidth: true
                            enabled: root.camRunning
                            text: root.gesturesPaused ? "Resume Gestures (G)" : "Pause Gestures (G)"
                            outlined: false
                            backgroundColor: root.gesturesPaused ? Qt.alpha(Color.mError, 0.25) : Color.mSurface
                            textColor: root.gesturesPaused ? Color.mError : Color.mOnSurface
                            onClicked: {
                                if (mainInstance) mainInstance.togglePause();
                            }
                        }

                        NButton {
                            Layout.fillWidth: true
                            enabled: root.camRunning
                            text: root.previewVisible ? "Hide Preview (P)" : "Show Preview (P)"
                            outlined: false
                            backgroundColor: Color.mSurface
                            textColor: Color.mOnSurface
                            onClicked: {
                                if (mainInstance) mainInstance.togglePreview();
                            }
                        }
                    }
                }
            }

            // 3. Live Effect Mode Switcher (Zero Frame Drop)
            NBox {
                Layout.fillWidth: true
                implicitHeight: modeCol.implicitHeight + Style.marginM * 2
                color: Color.mSurfaceVariant

                ColumnLayout {
                    id: modeCol
                    anchors.fill: parent
                    anchors.margins: Style.marginM
                    spacing: Style.marginS

                    NText {
                        text: "Effect Mode (Live Hot-Swap)"
                        pointSize: Style.fontSizeS
                        font.bold: true
                        color: Color.mOnSurface
                    }

                    GridLayout {
                        Layout.fillWidth: true
                        columns: 3
                        rowSpacing: Style.marginXS
                        columnSpacing: Style.marginXS

                        Repeater {
                            model: root.modesModel
                            delegate: NButton {
                                required property var modelData
                                Layout.fillWidth: true
                                text: modelData.label
                                outlined: false
                                backgroundColor: (root.camMode === modelData.id) ? Color.mPrimary : Color.mSurface
                                textColor: (root.camMode === modelData.id) ? Color.mOnPrimary : Color.mOnSurface
                                onClicked: {
                                    if (mainInstance) mainInstance.switchMode(modelData.id);
                                }
                            }
                        }
                    }
                }
            }

            // 4. Snap Void Excuse Message Picker
            NBox {
                Layout.fillWidth: true
                implicitHeight: snapCol.implicitHeight + Style.marginM * 2
                color: Color.mSurfaceVariant

                ColumnLayout {
                    id: snapCol
                    anchors.fill: parent
                    anchors.margins: Style.marginM
                    spacing: Style.marginS

                    RowLayout {
                        Layout.fillWidth: true
                        NText {
                            text: "Snap Void Particle Excuse"
                            pointSize: Style.fontSizeS
                            font.bold: true
                            color: Color.mOnSurface
                            Layout.fillWidth: true
                        }
                        NText {
                            text: root.snapMessage
                            pointSize: Style.fontSizeXS
                            font.bold: true
                            color: Color.mPrimary
                        }
                    }

                    GridLayout {
                        Layout.fillWidth: true
                        columns: 3
                        rowSpacing: Style.marginXS
                        columnSpacing: Style.marginXS

                        Repeater {
                            model: root.excusesModel
                            delegate: NButton {
                                required property string modelData
                                Layout.fillWidth: true
                                text: modelData
                                outlined: false
                                backgroundColor: (root.snapMessage === modelData) ? Qt.alpha(Color.mPrimary, 0.28) : Color.mSurface
                                textColor: (root.snapMessage === modelData) ? Color.mPrimary : Color.mOnSurface
                                onClicked: {
                                    if (mainInstance) mainInstance.setExcuse(modelData);
                                }
                            }
                        }

                        NButton {
                            Layout.fillWidth: true
                            text: "Cycle Next (T)"
                            outlined: false
                            backgroundColor: Color.mSurface
                            textColor: Color.mSecondary
                            onClicked: {
                                if (mainInstance) mainInstance.nextExcuse();
                            }
                        }
                    }
                }
            }

            // 5. Room Background Calibration
            NBox {
                Layout.fillWidth: true
                implicitHeight: bgRow.implicitHeight + Style.marginM * 2
                color: Color.mSurfaceVariant

                RowLayout {
                    id: bgRow
                    anchors.fill: parent
                    anchors.margins: Style.marginM
                    spacing: Style.marginS

                    NButton {
                        Layout.fillWidth: true
                        enabled: root.camRunning
                        text: "Load Saved Room (B)"
                        outlined: false
                        backgroundColor: Color.mSurface
                        textColor: Color.mOnSurface
                        onClicked: {
                            if (mainInstance) mainInstance.loadSavedRoom();
                        }
                    }

                    NButton {
                        Layout.fillWidth: true
                        enabled: root.camRunning
                        text: "Recapture Room (7s)"
                        outlined: false
                        backgroundColor: Color.mSurface
                        textColor: Color.mOnSurface
                        onClicked: {
                            if (mainInstance) mainInstance.recaptureRoom();
                        }
                    }
                }
            }
        }
    }
}
