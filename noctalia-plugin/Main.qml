import QtQuick
import Quickshell
import Quickshell.Io
import qs.Commons
import qs.Services.UI

Item {
    id: root

    property var pluginApi: null

    readonly property string defaultMode: (pluginApi && pluginApi.pluginSettings && pluginApi.pluginSettings.defaultMode) ? pluginApi.pluginSettings.defaultMode : "snap"
    readonly property bool compactBar: (pluginApi && pluginApi.pluginSettings && pluginApi.pluginSettings.compactBar !== undefined) ? pluginApi.pluginSettings.compactBar : false
    readonly property bool hideWhenOff: (pluginApi && pluginApi.pluginSettings && pluginApi.pluginSettings.hideWhenOff !== undefined) ? pluginApi.pluginSettings.hideWhenOff : false

    property bool camRunning: false
    property string camMode: "snap"
    property string camPhase: "off"
    property bool gesturesPaused: false
    property bool previewVisible: true
    property string snapMessage: "BRB..."

    readonly property string cliPath: "/home/mhdomar/.local/bin/vanish-cam"

    FileView {
        id: stateFileView
        path: "/tmp/vanish_cam.state.json"
        watchChanges: false
        printErrors: false
        onLoaded: {
            try {
                const raw = text().trim();
                if (!raw) {
                    root.camRunning = false;
                    root.camPhase = "off";
                    return;
                }
                const data = JSON.parse(raw);
                const nowSec = Date.now() / 1000.0;
                const fresh = data.updated_at ? ((nowSec - data.updated_at) < 8.0) : true;
                root.camRunning = Boolean(data.running) && fresh;
                if (root.camRunning) {
                    root.camMode = data.mode || root.defaultMode;
                    root.camPhase = data.phase || "ready";
                    root.gesturesPaused = Boolean(data.gestures_paused);
                    root.previewVisible = data.preview_visible !== undefined ? Boolean(data.preview_visible) : true;
                    if (data.snap_message) {
                        root.snapMessage = data.snap_message;
                    }
                } else {
                    root.camPhase = "off";
                    root.gesturesPaused = false;
                }
            } catch (e) {
                root.camRunning = false;
                root.camPhase = "off";
            }
        }
    }

    Timer {
        id: pollTimer
        interval: 650
        repeat: true
        running: true
        onTriggered: stateFileView.reload()
    }

    Timer {
        id: burstPollTimer
        interval: 180
        repeat: false
        onTriggered: stateFileView.reload()
    }

    Component.onCompleted: stateFileView.reload()

    function runCli(args) {
        Quickshell.execDetached([root.cliPath].concat(args));
        burstPollTimer.restart();
    }

    function togglePower() {
        if (root.camRunning) {
            runCli(["stop"]);
        } else {
            runCli(["bg", "--mode", root.defaultMode]);
        }
    }

    function triggerAction() {
        if (!root.camRunning) {
            runCli(["bg", "--mode", root.defaultMode]);
            return;
        }
        runCli(["action"]);
    }

    function vanishNow() {
        if (root.camRunning) runCli(["vanish"]);
    }

    function reappearNow() {
        if (root.camRunning) runCli(["reappear"]);
    }

    function togglePause() {
        if (root.camRunning) runCli(["pause"]);
    }

    function togglePreview() {
        if (root.camRunning) runCli(["preview"]);
    }

    function recaptureRoom() {
        if (root.camRunning) runCli(["recapture"]);
    }

    function loadSavedRoom() {
        if (root.camRunning) runCli(["load-bg"]);
    }

    function switchMode(newMode) {
        root.camMode = newMode;
        runCli(["mode", newMode]);
    }

    function nextExcuse() {
        if (root.camRunning) runCli(["next-text"]);
    }

    function setExcuse(text) {
        root.snapMessage = text;
        if (root.camRunning) runCli(["snap-text", text]);
    }

    IpcHandler {
        target: "plugin:vanish-cam"

        function toggle() { root.togglePower(); }
        function action() { root.triggerAction(); }
        function pause() { root.togglePause(); }
        function preview() { root.togglePreview(); }
        function mode(name: string) { root.switchMode(name); }
    }
}
