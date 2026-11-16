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
    readonly property bool ecoMode: (pluginApi && pluginApi.pluginSettings && pluginApi.pluginSettings.ecoMode !== undefined) ? pluginApi.pluginSettings.ecoMode : false
    readonly property bool savedMirror: (pluginApi && pluginApi.pluginSettings && pluginApi.pluginSettings.mirrorCam !== undefined) ? Boolean(pluginApi.pluginSettings.mirrorCam) : true
    readonly property string savedSnapMessage: (pluginApi && pluginApi.pluginSettings && pluginApi.pluginSettings.customSnapMessage) ? pluginApi.pluginSettings.customSnapMessage : ""
    readonly property string savedVirtualBg: (pluginApi && pluginApi.pluginSettings && pluginApi.pluginSettings.virtualBgPath) ? pluginApi.pluginSettings.virtualBgPath : ""
    readonly property string cliCommand: (pluginApi && pluginApi.pluginSettings && pluginApi.pluginSettings.cliCommand) ? pluginApi.pluginSettings.cliCommand : "vanish-cam"

    property bool camRunning: false
    property bool startingUp: false
    property string camMode: "snap"
    property string camPhase: "off"
    property bool gesturesPaused: false
    property bool previewVisible: !startHidden
    property bool ghostEcho: false
    property bool blurBg: false
    property bool mirrorCam: savedMirror
    property string virtualBg: savedVirtualBg
    property string snapMessage: savedSnapMessage ? savedSnapMessage : "BRB..."
    property var modesModel: [
        { id: "snap", label: "Snap Void", shortLabel: "SNAP", vanishHint: "Pinch & snap", reappearHint: "Peace sign / R", icon: "sparkles" },
        { id: "naruto", label: "Naruto Log", shortLabel: "NARU", vanishHint: "Join both hands", reappearHint: "Button / R", icon: "flame" },
        { id: "normal", label: "Dissolve", shortLabel: "NORM", vanishHint: "Peace sign", reappearHint: "Button / R", icon: "wand" },
        { id: "particles", label: "Particles", shortLabel: "PART", vanishHint: "Peace sign", reappearHint: "Button / R", icon: "atom" },
        { id: "itachi", label: "Itachi Crows", shortLabel: "ITAC", vanishHint: "Hands at chest", reappearHint: "Hands at chest / R", icon: "feather" },
        { id: "goku", label: "Goku Teleport", shortLabel: "GOKU", vanishHint: "Forehead tap", reappearHint: "Forehead tap / R", icon: "bolt" }
    ]

    FileView {
        id: modesFileView
        path: Qt.resolvedUrl("modes.json").toString().replace("file://", "")
        watchChanges: false
        printErrors: false
        onLoaded: {
            try {
                const parsed = JSON.parse(text().trim());
                if (Array.isArray(parsed) && parsed.length > 0) {
                    root.modesModel = parsed;
                }
            } catch (e) {}
        }
    }

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
                    root.blurBg = Boolean(data.blur_bg);
                    root.mirrorCam = data.mirror !== undefined ? Boolean(data.mirror) : root.savedMirror;
                    root.virtualBg = data.virtual_bg || "";
                    if (data.snap_message) {
                        root.snapMessage = data.snap_message;
                    }
                } else {
                    root.camPhase = "off";
                    root.gesturesPaused = false;
                    root.ghostEcho = false;
                    root.blurBg = false;
                    root.mirrorCam = root.savedMirror;
                    root.virtualBg = root.savedVirtualBg;
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
        interval: root.camRunning ? 850 : 3500
        repeat: true
        running: true
        onTriggered: stateFileView.reload()
    }

    Timer {
        id: burstPollTimer
        interval: 150
        repeat: false
        onTriggered: stateFileView.reload()
    }

    Timer {
        id: startupResetTimer
        interval: 6000
        repeat: false
        onTriggered: root.startingUp = false
    }

    Component.onCompleted: {
        modesFileView.reload();
        stateFileView.reload();
    }

    function runCli(args) {
        const fullArgs = ["sh", "-c", "export PATH=\"$HOME/.local/bin:$PATH\"; exec \"$0\" \"$@\"", root.cliCommand].concat(args);
        Quickshell.execDetached(fullArgs);
        burstPollTimer.restart();
    }

    function buildBgArgs(targetMode) {
        const args = ["bg", "--mode", targetMode];
        if (root.startHidden) args.push("--no-preview");
        if (root.ecoMode) args.push("--width", "960", "--height", "540", "--fps", "24");
        if (!root.mirrorCam) args.push("--no-mirror");
        const msg = (root.savedSnapMessage || "").trim();
        if (msg) args.push("--snap-text", msg);
        const vbg = (root.savedVirtualBg || "").trim();
        if (vbg) args.push("--bg-image", vbg);
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

    function toggleBlur() {
        if (root.camRunning) runCli(["blur"]);
    }

    function toggleMirror() {
        const nextVal = !root.mirrorCam;
        root.mirrorCam = nextVal;
        if (pluginApi && pluginApi.pluginSettings) {
            pluginApi.pluginSettings.mirrorCam = nextVal;
            pluginApi.saveSettings();
        }
        if (root.camRunning) runCli(["mirror", nextVal ? "on" : "off"]);
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

    Process {
        id: bgPickerProc
        command: ["zenity", "--file-selection", "--title=Choose Virtual Background", "--file-filter=Images | *.png *.jpg *.jpeg *.webp *.bmp"]
        stdout: SplitParser {
            onRead: data => {
                const picked = (data || "").trim();
                if (picked) root.setVirtualBg(picked);
            }
        }
    }

    function setVirtualBg(spec) {
        const cleaned = (spec || "").trim();
        const nextVal = (!cleaned || cleaned === "off" || cleaned === "none") ? "" : cleaned;
        root.virtualBg = nextVal;
        if (pluginApi && pluginApi.pluginSettings) {
            pluginApi.pluginSettings.virtualBgPath = nextVal;
            pluginApi.saveSettings();
        }
        if (root.camRunning) {
            runCli(["bg-image", nextVal ? nextVal : "off"]);
        }
    }

    function browseVirtualBg() {
        if (!bgPickerProc.running) {
            bgPickerProc.running = true;
        }
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
        function blur() { root.toggleBlur(); }
        function mirror() { root.toggleMirror(); }
        function echo() { root.toggleEcho(); }
        function pause() { root.togglePause(); }
        function preview() { root.togglePreview(); }
        function mode(name: string) { root.switchMode(name); }
        function bg(spec: string) { root.setVirtualBg(spec); }
    }
}
