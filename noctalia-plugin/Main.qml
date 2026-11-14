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
    readonly property bool startHidden: (pluginApi && pluginApi.pluginSettings && pluginApi.pluginSettings.startHidden !== undefined) ? pluginApi.pluginSettings.startHidden : true
    readonly property string savedSnapMessage: (pluginApi && pluginApi.pluginSettings && pluginApi.pluginSettings.customSnapMessage) ? pluginApi.pluginSettings.customSnapMessage : ""
    readonly property string cliCommand: (pluginApi && pluginApi.pluginSettings && pluginApi.pluginSettings.cliCommand) ? pluginApi.pluginSettings.cliCommand : "vanish-cam"

    property bool camRunning: false
    property bool startingUp: false
    property string camMode: "snap"
    property string camPhase: "off"
    property bool gesturesPaused: false
    property bool previewVisible: !startHidden
    property bool ghostEcho: false
    property string snapMessage: savedSnapMessage ? savedSnapMessage : "BRB..."

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
                    root.startingUp = false;
                    startupResetTimer.stop();
                    root.camMode = data.mode || root.defaultMode;
                    root.camPhase = data.phase || "ready";
                    root.gesturesPaused = Boolean(data.gestures_paused);
                    root.previewVisible = data.preview_visible !== undefined ? Boolean(data.preview_visible) : !root.startHidden;
                    root.ghostEcho = Boolean(data.ghost_echo);
                    if (data.snap_message) {
                        root.snapMessage = data.snap_message;
                    }
                } else {
                    root.camPhase = "off";
                    root.gesturesPaused = false;
                    root.ghostEcho = false;
                    if (root.savedSnapMessage) {
                        root.snapMessage = root.savedSnapMessage;
                    }
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

    Timer {
        id: startupResetTimer
        interval: 6000
        repeat: false
        onTriggered: root.startingUp = false
    }

    Component.onCompleted: stateFileView.reload()

    function runCli(args) {
        const fullArgs = ["sh", "-c", "export PATH=\"$HOME/.local/bin:$PATH\"; exec \"$0\" \"$@\"", root.cliCommand].concat(args);
        Quickshell.execDetached(fullArgs);
        burstPollTimer.restart();
    }

    function buildBgArgs(targetMode) {
        const args = ["bg", "--mode", targetMode];
        if (root.startHidden) args.push("--no-preview");
        const msg = (root.savedSnapMessage || "").trim();
        if (msg) args.push("--snap-text", msg);
        return args;
    }

    function launchBg(targetMode) {
        root.startingUp = true;
        startupResetTimer.restart();
        runCli(buildBgArgs(targetMode));
    }

    function togglePower() {
        if (root.camRunning) {
            root.startingUp = false;
            runCli(["stop"]);
        } else {
            launchBg(root.defaultMode);
        }
    }

    function triggerAction() {
        if (!root.camRunning) {
            launchBg(root.defaultMode);
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

    function toggleFreeze() {
        if (root.camRunning) runCli(["freeze"]);
    }

    function toggleEcho() {
        if (root.camRunning) runCli(["echo"]);
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
        if (root.camRunning) {
            runCli(["mode", newMode]);
        } else {
            launchBg(newMode);
        }
    }

    function nextExcuse() {
        if (root.camRunning) runCli(["next-text"]);
    }

    function setExcuse(text) {
        const cleaned = (text || "").trim().toUpperCase();
        if (!cleaned) return;
        root.snapMessage = cleaned;
        if (pluginApi && pluginApi.pluginSettings) {
            pluginApi.pluginSettings.customSnapMessage = cleaned;
            pluginApi.saveSettings();
        }
        if (root.camRunning) runCli(["snap-text", cleaned]);
    }

    IpcHandler {
        target: "plugin:vanish-cam"

        function toggle() { root.togglePower(); }
        function action() { root.triggerAction(); }
        function freeze() { root.toggleFreeze(); }
        function echo() { root.toggleEcho(); }
        function pause() { root.togglePause(); }
        function preview() { root.togglePreview(); }
        function mode(name: string) { root.switchMode(name); }
    }
}
