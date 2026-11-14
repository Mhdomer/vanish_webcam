import QtQuick
import QtQuick.Layouts
import Quickshell
import qs.Commons
import qs.Widgets
import qs.Services.UI

Item {
    id: root

    property var pluginApi: null
    property ShellScreen screen
    property string widgetId: ""
    property string section: ""
    property int sectionWidgetIndex: -1
    property int sectionWidgetsCount: 0

    readonly property var mainInstance: pluginApi ? pluginApi.mainInstance : null
    readonly property string screenName: screen ? screen.name : ""
    readonly property string resolvedBarPosition: Settings.getBarPositionForScreen(screenName)
    readonly property bool isBarVertical: resolvedBarPosition === "left" || resolvedBarPosition === "right"
    readonly property real capsuleHeight: Style.getCapsuleHeightForScreen(screenName)

    readonly property bool camRunning: mainInstance ? mainInstance.camRunning : false
    readonly property string camMode: mainInstance ? mainInstance.camMode : "snap"
    readonly property string camPhase: mainInstance ? mainInstance.camPhase : "off"
    readonly property bool gesturesPaused: mainInstance ? mainInstance.gesturesPaused : false
    readonly property bool compactBar: mainInstance ? mainInstance.compactBar : false
    readonly property bool hideWhenOff: mainInstance ? mainInstance.hideWhenOff : false

    visible: !hideWhenOff || camRunning

    readonly property bool isFrozen: camRunning && camPhase === "frozen"
    readonly property bool isVanished: camRunning && (camPhase === "vanished" || camPhase.indexOf("vanish") !== -1 || camPhase.indexOf("disappear") !== -1)

    readonly property string statusIcon: {
        if (!camRunning) return "video-off";
        if (isFrozen) return "snowflake";
        if (isVanished) return "eye-off";
        if (gesturesPaused) return "player-pause";
        return "video";
    }

    readonly property string statusLabel: {
        if (!camRunning) return "OFF";
        if (camPhase === "calibrating") return "CALIB";
        if (isFrozen) return "FROZEN";
        if (isVanished) return "VANISHED";
        if (gesturesPaused) return "PAUSED";
        return camMode.toUpperCase();
    }

    readonly property color statusColor: {
        if (!camRunning) return Color.mOnSurfaceVariant;
        if (isFrozen || isVanished) return Color.mSecondary;
        if (gesturesPaused) return Color.mError;
        return Color.mPrimary;
    }

    readonly property real contentWidth: isBarVertical
        ? capsuleHeight
        : ((compactBar || !camRunning) ? capsuleHeight : (rowLayout.implicitWidth + Style.marginM * 2))
    readonly property real contentHeight: capsuleHeight

    implicitWidth: visible ? contentWidth : 0
    implicitHeight: visible ? contentHeight : 0

    Rectangle {
        id: visualCapsule
        anchors.centerIn: parent
        width: root.contentWidth
        height: root.contentHeight
        radius: Style.radiusL
        color: mouseArea.containsMouse
            ? Color.mHover
            : ((root.isVanished || root.isFrozen) ? Qt.alpha(Color.mSecondary, 0.18) : Style.capsuleColor)
        border.color: root.camRunning ? root.statusColor : Style.capsuleBorderColor
        border.width: root.camRunning ? 1 : Style.capsuleBorderWidth

        Behavior on color {
            ColorAnimation { duration: Style.animationFast; easing.type: Easing.OutCubic }
        }

        RowLayout {
            id: rowLayout
            anchors.centerIn: parent
            spacing: Style.marginXS

            NIcon {
                icon: root.statusIcon
                pointSize: Style.fontSizeM
                color: mouseArea.containsMouse ? Color.mOnHover : root.statusColor
                Layout.alignment: Qt.AlignVCenter
            }

            NText {
                visible: !root.isBarVertical && !root.compactBar && root.camRunning
                text: root.statusLabel
                pointSize: Style.fontSizeXS
                font.bold: true
                color: mouseArea.containsMouse ? Color.mOnHover : root.statusColor
                Layout.alignment: Qt.AlignVCenter
            }
        }
    }

    NPopupContextMenu {
        id: contextMenu

        model: [
            {
                "label": root.camRunning ? "Stop VanishCam" : "Start VanishCam",
                "action": "power",
                "icon": root.camRunning ? "power" : "player-play"
            },
            {
                "label": (root.isVanished || root.isFrozen) ? "Reappear Now (R)" : "Vanish Now (V)",
                "action": "action",
                "icon": (root.isVanished || root.isFrozen) ? "eye" : "eye-off",
                "visible": root.camRunning
            },
            {
                "label": root.isFrozen ? "Unfreeze Frame (Z)" : "Freeze Frame (Z)",
                "action": "freeze",
                "icon": "player-pause",
                "visible": root.camRunning
            },
            {
                "label": root.gesturesPaused ? "Resume Gestures (G)" : "Pause Gestures (G)",
                "action": "pause",
                "icon": root.gesturesPaused ? "player-play" : "player-pause",
                "visible": root.camRunning
            },
            {
                "label": "Show / Hide Preview (P)",
                "action": "preview",
                "icon": "layout-sidebar",
                "visible": root.camRunning
            },
            {
                "label": "Recapture Room (SPACE)",
                "action": "recapture",
                "icon": "refresh",
                "visible": root.camRunning
            },
            {
                "label": "Plugin Settings",
                "action": "settings",
                "icon": "settings"
            }
        ]

        onTriggered: action => {
            contextMenu.close();
            PanelService.closeContextMenu(screen);
            if (!mainInstance) return;
            if (action === "power") mainInstance.togglePower();
            else if (action === "action") mainInstance.triggerAction();
            else if (action === "freeze") mainInstance.toggleFreeze();
            else if (action === "pause") mainInstance.togglePause();
            else if (action === "preview") mainInstance.togglePreview();
            else if (action === "recapture") mainInstance.recaptureRoom();
            else if (action === "settings") BarService.openPluginSettings(screen, pluginApi.manifest);
        }
    }

    MouseArea {
        id: mouseArea
        anchors.fill: parent
        hoverEnabled: true
        cursorShape: Qt.PointingHandCursor
        acceptedButtons: Qt.LeftButton | Qt.RightButton | Qt.MiddleButton

        onClicked: mouse => {
            if (mouse.button === Qt.LeftButton) {
                if (pluginApi) {
                    pluginApi.openPanel(root.screen, root);
                }
            } else if (mouse.button === Qt.RightButton) {
                PanelService.showContextMenu(contextMenu, root, screen);
            } else if (mouse.button === Qt.MiddleButton && mainInstance) {
                mainInstance.triggerAction();
            }
        }
    }
}
