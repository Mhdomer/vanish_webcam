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
    property real contentPreferredWidth: 420 * Style.uiScaleRatio
    property real contentPreferredHeight: 590 * Style.uiScaleRatio

    readonly property bool camRunning: mainInstance ? mainInstance.camRunning : false
    readonly property bool startingUp: mainInstance ? mainInstance.startingUp : false
    readonly property string camMode: mainInstance ? mainInstance.camMode : "snap"
    readonly property string camPhase: mainInstance ? mainInstance.camPhase : "off"
    readonly property bool gesturesPaused: mainInstance ? mainInstance.gesturesPaused : false
    readonly property bool previewVisible: mainInstance ? mainInstance.previewVisible : false
    readonly property bool ghostEcho: mainInstance ? mainInstance.ghostEcho : false
    readonly property string snapMessage: mainInstance ? mainInstance.snapMessage : "BRB..."

    readonly property bool isCalibrating: camRunning && camPhase === "calibrating"
    readonly property bool isFrozen: camRunning && camPhase === "frozen"
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
                            ? ((root.isVanished || root.isFrozen) ? Qt.alpha(Color.mSecondary, 0.22) : Qt.alpha(Color.mPrimary, 0.22))
                            : Color.mSurface

                        NIcon {
                            anchors.centerIn: parent
                            icon: !root.camRunning ? "video-off" : ((root.isVanished || root.isFrozen) ? "eye-off" : "video")
                            pointSize: Style.fontSizeL
                            color: !root.camRunning ? Color.mOnSurfaceVariant : ((root.isVanished || root.isFrozen) ? Color.mSecondary : Color.mPrimary)
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
                                ? (root.startingUp ? "Starting virtual camera..." : "Stopped (/dev/video2 idle)")
                                : (root.isCalibrating
                                    ? ("Active: " + root.camMode.toUpperCase() + "  ·  CALIBRATING (Step out)")
                                    : ("Active: " + root.camMode.toUpperCase() + "  ·  Phase: " + root.camPhase.toUpperCase()))
                            pointSize: Style.fontSizeXS
                            color: root.camRunning ? Color.mPrimary : (root.startingUp ? Color.mSecondary : Color.mOnSurfaceVariant)
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
                        enabled: !root.startingUp || root.camRunning
                        text: !root.camRunning
                            ? (root.startingUp ? "Starting camera..." : "Start & Ready Camera")
                            : (root.isCalibrating
                                ? "Capturing Empty Room... Step Out"
                                : ((root.isVanished || root.isFrozen) ? "Reappear Smoothly Now (R)" : "Vanish Now (V)"))
                        outlined: false
                        backgroundColor: !root.camRunning
                            ? Color.mSurface
                            : ((root.isVanished || root.isFrozen) ? Color.mSecondary : Color.mPrimary)
                        textColor: !root.camRunning
                            ? Color.mOnSurface
                            : ((root.isVanished || root.isFrozen) ? Color.mOnSecondary : Color.mOnPrimary)
                        onClicked: {
                            if (mainInstance) mainInstance.triggerAction();
                        }
                    }

                    GridLayout {
                        Layout.fillWidth: true
                        columns: 2
                        rowSpacing: Style.marginXS
                        columnSpacing: Style.marginXS

                        NButton {
                            Layout.fillWidth: true
                            enabled: root.camRunning
                            text: root.isFrozen ? "Unfreeze Frame (Z)" : "Freeze Frame (Z)"
                            outlined: false
                            backgroundColor: root.isFrozen ? Qt.alpha(Color.mSecondary, 0.28) : Color.mSurface
                            textColor: root.isFrozen ? Color.mSecondary : Color.mOnSurface
                            onClicked: {
                                if (mainInstance) mainInstance.toggleFreeze();
                            }
                        }

                        NButton {
                            Layout.fillWidth: true
                            enabled: root.camRunning
                            text: root.ghostEcho ? "Ghost Echo: ON (E)" : "Ghost Echo: OFF (E)"
                            outlined: false
                            backgroundColor: root.ghostEcho ? Qt.alpha(Color.mPrimary, 0.25) : Color.mSurface
                            textColor: root.ghostEcho ? Color.mPrimary : Color.mOnSurface
                            onClicked: {
                                if (mainInstance) mainInstance.toggleEcho();
                            }
                        }

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

            // 4. Snap Void Excuse Message Picker & Custom Editor
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

                    RowLayout {
                        Layout.fillWidth: true
                        spacing: Style.marginXS

                        TextField {
                            id: customExcuseField
                            Layout.fillWidth: true
                            placeholderText: "Type custom excuse (e.g. COFFEE BREAK)..."
                            color: Color.mOnSurface
                            placeholderTextColor: Color.mOnSurfaceVariant
                            font.pointSize: Style.fontSizeXS
                            maximumLength: 22
                            leftPadding: Style.marginS
                            rightPadding: Style.marginS
                            topPadding: 6
                            bottomPadding: 6
                            background: Rectangle {
                                radius: Style.radiusS
                                color: Color.mSurface
                                border.color: customExcuseField.activeFocus ? Color.mPrimary : Style.capsuleBorderColor
                                border.width: 1
                            }
                            onAccepted: {
                                if (mainInstance && customExcuseField.text.trim().length > 0) {
                                    mainInstance.setExcuse(customExcuseField.text);
                                    customExcuseField.text = "";
                                }
                            }
                        }

                        NButton {
                            text: "Set"
                            outlined: false
                            backgroundColor: Color.mPrimary
                            textColor: Color.mOnPrimary
                            onClicked: {
                                if (mainInstance && customExcuseField.text.trim().length > 0) {
                                    mainInstance.setExcuse(customExcuseField.text);
                                    customExcuseField.text = "";
                                }
                            }
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
