import QtQuick
import QtQuick.Layouts
import QtQuick.Controls
import Quickshell
import qs.Commons
import qs.Widgets
import qs.Services.UI

ColumnLayout {
    id: root

    property var pluginApi: null

    property var cfg: (pluginApi && pluginApi.pluginSettings) ? pluginApi.pluginSettings : ({})
    property var defaults: (pluginApi && pluginApi.manifest && pluginApi.manifest.metadata && pluginApi.manifest.metadata.defaultSettings) ? pluginApi.manifest.metadata.defaultSettings : ({})

    property string editDefaultMode: cfg.defaultMode ?? defaults.defaultMode ?? "snap"
    property bool editCompactBar: cfg.compactBar ?? defaults.compactBar ?? false
    property bool editHideWhenOff: cfg.hideWhenOff ?? defaults.hideWhenOff ?? false
    property string editCliCommand: cfg.cliCommand ?? defaults.cliCommand ?? "vanish-cam"

    readonly property var modeChoices: [
        { key: "snap", name: "Snap Void (Particle Excuse)" },
        { key: "naruto", name: "Naruto Substitution Log" },
        { key: "normal", name: "Silhouette Dissolve" },
        { key: "particles", name: "Wind Particles" },
        { key: "itachi", name: "Itachi Crow Swarm" },
        { key: "goku", name: "Goku Instant Transmission" }
    ]

    function save() {
        if (!pluginApi) return;
        pluginApi.pluginSettings.defaultMode = root.editDefaultMode;
        pluginApi.pluginSettings.compactBar = root.editCompactBar;
        pluginApi.pluginSettings.hideWhenOff = root.editHideWhenOff;
        pluginApi.pluginSettings.cliCommand = root.editCliCommand;
        pluginApi.saveSettings();
    }

    function saveSettings() {
        root.save();
    }

    spacing: Style.marginM

    NText {
        text: "VanishCam Bar & Launch Settings"
        pointSize: Style.fontSizeL
        font.weight: Style.fontWeightBold
        color: Color.mPrimary
    }

    NComboBox {
        label: "Default Launch Mode"
        description: "Mode used when starting VanishCam from the bar widget."
        model: root.modeChoices
        currentKey: root.editDefaultMode
        onSelected: key => {
            root.editDefaultMode = key;
            root.save();
        }
    }

    NToggle {
        label: "Compact Bar Icon Only"
        description: "Show only the status icon in the bar without the mode text."
        checked: root.editCompactBar
        onToggled: checked => {
            root.editCompactBar = checked;
            root.save();
        }
    }

    NToggle {
        label: "Hide Bar Widget When Off"
        description: "Only display the VanishCam bar capsule while VanishCam is actively running."
        checked: root.editHideWhenOff
        onToggled: checked => {
            root.editHideWhenOff = checked;
            root.save();
        }
    }

    NTextInput {
        Layout.fillWidth: true
        label: "CLI Command / Path"
        description: "Command or path to vanish-cam executable (searched in PATH and ~/.local/bin)."
        placeholderText: "vanish-cam"
        text: root.editCliCommand
        onTextChanged: {
            root.editCliCommand = text;
            root.save();
        }
    }
}
