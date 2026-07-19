import AppKit
import SwiftUI

struct SettingsWindowView: View {
    @ObservedObject var model: JarvisLineModel
    @State private var destination = SettingsDestination.general

    var body: some View {
        VStack(spacing: 0) {
            SettingsHeader(model: model)
            applyStatus
            Divider()
                .overlay(JarvisTheme.border.opacity(0.65))
            HStack(spacing: 0) {
                SettingsSidebar(selection: $destination)
                Divider()
                    .overlay(JarvisTheme.border.opacity(0.65))
                content
            }
        }
        .frame(minWidth: 700, minHeight: 660)
        .background(JarvisTheme.panelBase)
        .preferredColorScheme(.dark)
        .tint(JarvisTheme.cyan)
        .toolbar {
            ToolbarItemGroup(placement: .primaryAction) {
                if model.hasUnsavedChanges {
                    Button {
                        model.revertConfig()
                    } label: {
                        Image(systemName: "arrow.uturn.backward")
                    }
                    .help("Revert unapplied changes")
                    .accessibilityLabel("Revert unapplied changes")
                    .disabled(model.isBusy)

                    Button {
                        Task { await model.applyConfig() }
                    } label: {
                        Label(
                            model.pendingApplyImpact == .restartRuntime ? "Apply & Restart" : "Apply",
                            systemImage: model.pendingApplyImpact == .restartRuntime
                                ? "arrow.triangle.2.circlepath"
                                : "checkmark"
                        )
                    }
                    .buttonStyle(.borderedProminent)
                    .disabled(model.isBusy || !model.validationIssues.isEmpty)
                    .help(applyHelp)
                }
            }
        }
        .task {
            await model.refresh()
        }
        .onChange(of: destination) { newDestination in
            guard newDestination == .diagnostics else { return }
            model.requestCleanupStatusRefresh()
            Task { await model.refreshReliability() }
        }
    }

    @ViewBuilder
    private var applyStatus: some View {
        if let error = model.errorMessage {
            SettingsNotice(
                text: error,
                icon: "exclamationmark.triangle.fill",
                color: JarvisTheme.error
            )
        } else if let issue = model.validationIssues.first {
            SettingsNotice(
                text: validationText(first: issue),
                icon: "exclamationmark.triangle.fill",
                color: JarvisTheme.goldSoft
            )
        } else if let confirmation = model.settingsConfirmation {
            SettingsNotice(
                text: confirmation,
                icon: "checkmark.circle.fill",
                color: JarvisTheme.cyan
            )
        }
    }

    private var content: some View {
        ScrollView {
            VStack(alignment: .leading, spacing: 22) {
                HStack(spacing: 10) {
                    Image(systemName: destination.systemImage)
                        .font(.system(size: 18, weight: .semibold))
                        .foregroundStyle(JarvisTheme.cyan)
                        .frame(width: 24)
                    Text(destination.title)
                        .font(.system(size: 22, weight: .semibold))
                        .foregroundStyle(JarvisTheme.primaryText)
                    Spacer()
                    if model.isBusy {
                        ProgressView()
                            .controlSize(.small)
                            .accessibilityLabel("Working")
                    }
                }

                destinationContent
            }
            .padding(.horizontal, 26)
            .padding(.vertical, 22)
            .frame(maxWidth: .infinity, alignment: .topLeading)
        }
        .background(
            LinearGradient(
                colors: [
                    JarvisTheme.panelBase,
                    JarvisTheme.panelBottom.opacity(0.82),
                ],
                startPoint: .top,
                endPoint: .bottom
            )
        )
    }

    @ViewBuilder
    private var destinationContent: some View {
        switch destination {
        case .general:
            generalSettings
        case .speech:
            speechSettings
        case .voice:
            voiceSettings
        case .updates:
            updateSettings
        case .diagnostics:
            diagnosticsSettings
        case .advanced:
            advancedSettings
        }
    }

    private var generalSettings: some View {
        VStack(alignment: .leading, spacing: 24) {
            SettingsSection(title: "Application") {
                SettingsRow(title: "Show in Dock") {
                    Toggle("Show in Dock", isOn: Binding(
                        get: { model.showDockIcon },
                        set: { model.setDockIconVisible($0) }
                    ))
                    .labelsHidden()
                    .toggleStyle(.switch)
                }

                SettingsRow(title: "Setup") {
                    Button {
                        AppDelegate.showSetupWindow?()
                    } label: {
                        Label("Open Setup Assistant", systemImage: "checklist")
                    }
                    .buttonStyle(.bordered)
                }
            }

            SettingsSection(title: "Product") {
                SettingsValueRow(title: "App version", value: model.appVersion)
                SettingsValueRow(title: "CLI version", value: model.cliVersion)
                SettingsValueRow(
                    title: "Voice runtime",
                    value: model.status.summary,
                    state: model.status.watcherState == "running" ? .healthy : .inactive
                )
                SettingsRow(title: "Codex hook") {
                    if model.codexHookInstalled {
                        SettingsStatusLabel(text: "Installed", state: .healthy)
                    } else {
                        Button {
                            Task { await model.installCodexHook() }
                        } label: {
                            Label("Install", systemImage: "link.badge.plus")
                        }
                        .buttonStyle(.bordered)
                        .disabled(model.isBusy)
                    }
                }
            }
        }
    }

    private var speechSettings: some View {
        VStack(alignment: .leading, spacing: 24) {
            SettingsSection(title: "Events") {
                SettingsRow(title: "Speech") {
                    Toggle("Speech", isOn: $model.config.speechEnabled)
                        .labelsHidden()
                        .toggleStyle(.switch)
                }

                SettingsRow(
                    title: "Attention alerts",
                    detail: model.config.speechEnabled && model.config.speakMode != "off"
                        ? nil
                        : "Requires speech"
                ) {
                    Toggle("Attention alerts", isOn: $model.config.attentionEnabled)
                        .labelsHidden()
                        .toggleStyle(.switch)
                        .disabled(!model.config.speechEnabled || model.config.speakMode == "off")
                }

                SettingsRow(title: "Speak mode", restartRequired: true) {
                    Picker("Speak mode", selection: $model.config.speakMode) {
                        ForEach(
                            model.configContract.stringOptions(
                                "speak_mode",
                                fallback: JarvisConfigDraft.speakModeOptions
                            ),
                            id: \.self
                        ) { value in
                            Text(SettingsPresentation.speakModeLabel(value)).tag(value)
                        }
                    }
                    .labelsHidden()
                    .pickerStyle(.menu)
                    .frame(width: 210)
                }
            }

            SettingsSection(title: "Output") {
                SettingsRow(title: "Line language", restartRequired: true) {
                    Picker("Line language", selection: $model.config.lineLanguage) {
                        ForEach(
                            model.configContract.stringOptions(
                                "line_language",
                                fallback: JarvisConfigDraft.lineLanguageOptions
                            ),
                            id: \.self
                        ) { value in
                            Text(value).tag(value)
                        }
                    }
                    .labelsHidden()
                    .pickerStyle(.menu)
                    .frame(width: 210)
                }

                SettingsRow(title: "Spoken length", restartRequired: true) {
                    Picker("Spoken length", selection: $model.config.maxSpokenChars) {
                        ForEach(
                            model.configContract.intOptions(
                                "max_spoken_chars",
                                fallback: JarvisConfigDraft.maxSpokenCharsOptions
                            ),
                            id: \.self
                        ) { value in
                            Text(SettingsPresentation.spokenLengthLabel(value)).tag(value)
                        }
                    }
                    .labelsHidden()
                    .pickerStyle(.menu)
                    .frame(width: 210)
                }

                SettingsRow(title: "Quiet hours", restartRequired: true) {
                    Picker("Quiet hours", selection: $model.config.quietHours) {
                        ForEach(quietHourOptions, id: \.self) { value in
                            Text(SettingsPresentation.quietHoursLabel(value)).tag(value)
                        }
                    }
                    .labelsHidden()
                    .pickerStyle(.menu)
                    .frame(width: 210)
                }
            }
        }
    }

    private var voiceSettings: some View {
        VStack(alignment: .leading, spacing: 24) {
            SettingsSection(title: "Engine") {
                SettingsRow(title: "Backend", restartRequired: true) {
                    Picker("Backend", selection: $model.config.tts) {
                        ForEach(
                            model.configContract.stringOptions(
                                "tts",
                                fallback: JarvisConfigDraft.ttsOptions
                            ),
                            id: \.self
                        ) { value in
                            Text(SettingsPresentation.ttsLabel(value)).tag(value)
                        }
                    }
                    .labelsHidden()
                    .pickerStyle(.menu)
                    .frame(width: 250)
                }

                SettingsRow(title: "Fallback", restartRequired: true) {
                    Picker("Fallback", selection: $model.config.fallbackTTS) {
                        ForEach(fallbackOptions, id: \.self) { value in
                            Text(SettingsPresentation.fallbackLabel(value)).tag(value)
                        }
                    }
                    .labelsHidden()
                    .pickerStyle(.menu)
                    .frame(width: 250)
                }

                SettingsRow(title: "Volume", restartRequired: true) {
                    HStack(spacing: 10) {
                        Slider(value: $model.config.volume, in: 0...1)
                            .frame(width: 168)
                            .accessibilityLabel("Volume")
                        Text(String(format: "%.2f", model.config.volume))
                            .font(.system(size: 11, weight: .medium, design: .monospaced))
                            .foregroundStyle(JarvisTheme.mutedText)
                            .frame(width: 34, alignment: .trailing)
                    }
                }
            }

            backendSettings

            ForEach(model.config.guidance, id: \.self) { guidance in
                SettingsCompatibilityNote(text: guidance)
            }

            SettingsSection(title: "Preview") {
                SettingsRow(
                    title: "Voice test",
                    detail: model.hasUnsavedChanges ? "Apply changes before testing" : nil
                ) {
                    Button {
                        Task { await model.testVoice() }
                    } label: {
                        Label("Play Test", systemImage: "speaker.wave.2.fill")
                    }
                    .buttonStyle(.borderedProminent)
                    .disabled(
                        model.isBusy
                            || model.hasUnsavedChanges
                            || !model.validationIssues.isEmpty
                    )
                }
            }
        }
    }

    @ViewBuilder
    private var backendSettings: some View {
        if model.config.tts == "kokoro" {
            SettingsSection(title: "Kokoro") {
                SettingsRow(title: "Voice", restartRequired: true) {
                    Picker("Kokoro voice", selection: $model.config.voice) {
                        ForEach(
                            model.configContract.stringOptions(
                                "voice",
                                fallback: JarvisConfigDraft.kokoroVoiceOptions
                            ),
                            id: \.self
                        ) { value in
                            Text(SettingsPresentation.kokoroVoiceLabel(value)).tag(value)
                        }
                    }
                    .labelsHidden()
                    .pickerStyle(.menu)
                    .frame(width: 250)
                }

                SettingsRow(title: "Model language", restartRequired: true) {
                    Picker("Kokoro language", selection: $model.config.lang) {
                        ForEach(
                            model.configContract.stringOptions(
                                "lang",
                                fallback: JarvisConfigDraft.kokoroLangOptions
                            ),
                            id: \.self
                        ) { value in
                            Text(SettingsPresentation.kokoroLanguageLabel(value)).tag(value)
                        }
                    }
                    .labelsHidden()
                    .pickerStyle(.menu)
                    .frame(width: 250)
                }

                SettingsRow(title: "Speed", restartRequired: true) {
                    Picker("Kokoro speed", selection: $model.config.speed) {
                        ForEach(
                            model.configContract.doubleOptions(
                                "speed",
                                fallback: JarvisConfigDraft.speedOptions
                            ),
                            id: \.self
                        ) { value in
                            Text(SettingsPresentation.speedLabel(value)).tag(value)
                        }
                    }
                    .labelsHidden()
                    .pickerStyle(.menu)
                    .frame(width: 250)
                }

                SettingsRow(title: "Keep engine warm", restartRequired: true) {
                    Toggle("Keep engine warm", isOn: $model.config.warmTTS)
                        .labelsHidden()
                        .toggleStyle(.switch)
                }

                SettingsRow(title: "Warm-up phrase", restartRequired: true) {
                    Picker("Warm-up phrase", selection: $model.config.warmTTSText) {
                        ForEach(warmTextOptions, id: \.self) { value in
                            Text(value).tag(value)
                        }
                    }
                    .labelsHidden()
                    .pickerStyle(.menu)
                    .frame(width: 250)
                }
            }
        } else if model.config.tts == "system" || model.config.tts == "macos" {
            SettingsSection(title: model.config.tts == "macos" ? "macOS Voice" : "System Voice") {
                SettingsRow(title: "Voice", restartRequired: true) {
                    Picker("System voice", selection: $model.config.systemVoice) {
                        ForEach(model.systemVoices, id: \.self) { value in
                            Text(value.isEmpty ? "System default" : value).tag(value)
                        }
                    }
                    .labelsHidden()
                    .pickerStyle(.menu)
                    .frame(width: 250)
                }

                SettingsRow(title: "Rate", restartRequired: true) {
                    Picker("System rate", selection: $model.config.systemRate) {
                        ForEach(
                            model.configContract.intOptions(
                                "system_rate",
                                fallback: JarvisConfigDraft.systemRateOptions
                            ),
                            id: \.self
                        ) { value in
                            Text("\(value) words/min").tag(value)
                        }
                    }
                    .labelsHidden()
                    .pickerStyle(.menu)
                    .frame(width: 250)
                }
            }
        } else if model.config.tts == "command" {
            SettingsSection(title: "Custom Command") {
                SettingsValueRow(
                    title: "Configuration",
                    value: model.config.command.isEmpty ? "Needs setup" : "Configured",
                    state: model.config.command.isEmpty ? .warning : .healthy
                )
                SettingsValueRow(title: "Editor", value: "Advanced")
            }
        }
    }

    private var updateSettings: some View {
        VStack(alignment: .leading, spacing: 24) {
            SettingsSection(title: "Automatic Checks") {
                SettingsRow(title: "Check for updates") {
                    Toggle("Check for updates", isOn: $model.config.updateCheckEnabled)
                        .labelsHidden()
                        .toggleStyle(.switch)
                }

                SettingsRow(title: "Interval") {
                    Picker("Update interval", selection: $model.config.updateCheckIntervalHours) {
                        ForEach(
                            model.configContract.intOptions(
                                "update_check_interval_hours",
                                fallback: JarvisConfigDraft.updateIntervalOptions
                            ),
                            id: \.self
                        ) { value in
                            Text(value == 168 ? "Weekly" : "Every \(value) hours").tag(value)
                        }
                    }
                    .labelsHidden()
                    .pickerStyle(.menu)
                    .frame(width: 210)
                    .disabled(!model.config.updateCheckEnabled)
                }

                SettingsValueRow(title: "Source", value: "GitHub release tags")
            }

            SettingsSection(title: "Version") {
                SettingsValueRow(title: "Installed", value: model.cliVersion)
                SettingsValueRow(title: "Latest check", value: model.updateStatusText)
                SettingsRow(title: "Check now") {
                    Button {
                        Task { await model.checkForUpdates() }
                    } label: {
                        Label("Check Now", systemImage: "arrow.triangle.2.circlepath")
                    }
                    .buttonStyle(.borderedProminent)
                    .disabled(model.isBusy)
                }
            }
        }
    }

    private var diagnosticsSettings: some View {
        VStack(alignment: .leading, spacing: 24) {
            ReliabilityCenterView(
                snapshot: model.reliabilitySnapshot,
                resultText: model.reliabilityResultText,
                doctorText: model.doctorText,
                isBusy: model.isBusy,
                onRefresh: { Task { await model.refreshReliability() } },
                onAction: { action in
                    Task { await model.runReliabilityAction(action) }
                }
            )

            SettingsSection(title: "Storage & Cleanup") {
                SettingsRow(title: "Automatic cleanup") {
                    Toggle("Automatic cleanup", isOn: $model.config.cleanupEnabled)
                        .labelsHidden()
                        .toggleStyle(.switch)
                }

                SettingsRow(title: "Frequency") {
                    Picker("Cleanup frequency", selection: $model.config.cleanupIntervalHours) {
                        Text("Daily").tag(24)
                        Text("Weekly").tag(168)
                    }
                    .labelsHidden()
                    .pickerStyle(.menu)
                    .frame(width: 150)
                    .disabled(!model.config.cleanupEnabled)
                }

                SettingsValueRow(
                    title: "Last cleanup",
                    value: model.cleanupStatus.lastSuccessText
                )
                SettingsValueRow(
                    title: "Reclaimable",
                    value: cleanupReclaimableText
                )
                SettingsValueRow(
                    title: "Last result",
                    value: model.cleanupResultText,
                    state: cleanupResultState
                )

                SettingsRow(title: "Maintenance") {
                    HStack(spacing: 9) {
                        Button {
                            Task { await model.refreshCleanupStatus() }
                        } label: {
                            Image(systemName: "arrow.clockwise")
                                .frame(width: 22, height: 22)
                        }
                        .buttonStyle(.borderless)
                        .help("Refresh cleanup status")
                        .accessibilityLabel("Refresh cleanup status")
                        .accessibilityHint("Updates cleanup history and reclaimable storage")

                        Button {
                            Task { await model.cleanStorage() }
                        } label: {
                            Label("Clean Now", systemImage: "trash")
                        }
                        .buttonStyle(.borderedProminent)
                        .help("Clean eligible storage now")
                        .accessibilityLabel("Clean storage now")
                        .accessibilityHint("Removes eligible files and refreshes cleanup status")
                    }
                    .disabled(model.isBusy)
                }
            }

            SettingsSection(title: "Files") {
                HStack(spacing: 9) {
                    Button {
                        model.openWatcherLog()
                    } label: {
                        Label("Watcher Log", systemImage: "doc.text.magnifyingglass")
                    }
                    Button {
                        model.openAudioWorkerLog()
                    } label: {
                        Label("Worker Log", systemImage: "waveform.badge.magnifyingglass")
                    }
                    Button {
                        model.openConfig()
                    } label: {
                        Label("Config", systemImage: "doc.badge.gearshape")
                    }
                }
                .buttonStyle(.bordered)
                .padding(.vertical, 8)
            }
        }
    }

    private var advancedSettings: some View {
        VStack(alignment: .leading, spacing: 24) {
            SettingsSection(title: "Queue And Parsing") {
                SettingsRow(title: "Queue size", restartRequired: true) {
                    Picker("Queue size", selection: $model.config.maxQueueSize) {
                        ForEach(
                            model.configContract.intOptions(
                                "max_queue_size",
                                fallback: JarvisConfigDraft.maxQueueSizeOptions
                            ),
                            id: \.self
                        ) { value in
                            Text("\(value) lines").tag(value)
                        }
                    }
                    .labelsHidden()
                    .pickerStyle(.menu)
                    .frame(width: 210)
                }

                SettingsRow(title: "Speak without prefix", restartRequired: true) {
                    Toggle("Speak without prefix", isOn: $model.config.speakWithoutPrefix)
                        .labelsHidden()
                        .toggleStyle(.switch)
                }
            }

            SettingsSection(title: "Custom TTS Command") {
                SettingsRow(
                    title: "Command",
                    detail: "Use {text} or {text_json}",
                    restartRequired: true
                ) {
                    TextField("Command", text: $model.config.command)
                        .textFieldStyle(.roundedBorder)
                        .font(.system(size: 11, design: .monospaced))
                        .frame(width: 300)
                        .accessibilityLabel("Custom TTS command")
                }

                SettingsValueRow(
                    title: "Secrets",
                    value: "Environment variables only",
                    state: .warning
                )
            }
        }
    }

    private var quietHourOptions: [String] {
        [""] + model.configContract.stringOptions(
            "quiet_hours",
            fallback: JarvisConfigDraft.quietHourOptions.filter { !$0.isEmpty }
        )
    }

    private var warmTextOptions: [String] {
        SettingsPresentation.options(
            model.configContract.stringOptions(
                "warm_tts_text",
                fallback: JarvisConfigDraft.warmTextOptions
            ),
            preserving: model.config.warmTTSText
        )
    }

    private var fallbackOptions: [String] {
        SettingsPresentation.fallbackOptions(
            contract: model.configContract,
            command: model.config.command
        )
    }

    private var applyHelp: String {
        model.pendingApplyImpact == .restartRuntime
            ? "Save settings and restart the voice runtime"
            : "Save settings"
    }

    private var cleanupReclaimableText: String {
        let count = model.cleanupStatus.eligibleFiles
        let fileWord = count == 1 ? "file" : "files"
        return "\(count) \(fileWord) · \(model.cleanupStatus.reclaimableText)"
    }

    private var cleanupResultState: SettingsStatusState? {
        if model.cleanupResultText == "Cleanup failed"
            || model.cleanupResultText.contains("error")
            || model.cleanupResultText.contains("unavailable") {
            return .warning
        }
        if model.cleanupResultText != "Not checked" {
            return .healthy
        }
        return nil
    }

    private func validationText(first issue: String) -> String {
        let remaining = max(0, model.validationIssues.count - 1)
        return remaining == 0 ? issue : "\(issue) (+\(remaining) more)"
    }

}

private struct SettingsSidebar: View {
    @Binding var selection: SettingsDestination

    var body: some View {
        VStack(alignment: .leading, spacing: 6) {
            ForEach(SettingsDestination.allCases) { destination in
                Button {
                    selection = destination
                } label: {
                    HStack(spacing: 10) {
                        Image(systemName: destination.systemImage)
                            .font(.system(size: 13, weight: .semibold))
                            .frame(width: 18)
                        Text(destination.title)
                            .font(.system(size: 13, weight: .medium))
                        Spacer(minLength: 0)
                    }
                    .foregroundStyle(selection == destination ? JarvisTheme.primaryText : JarvisTheme.mutedText)
                    .padding(.horizontal, 11)
                    .frame(height: 34)
                    .background(
                        RoundedRectangle(cornerRadius: 6, style: .continuous)
                            .fill(selection == destination ? JarvisTheme.cyanDeep.opacity(0.68) : Color.clear)
                    )
                    .overlay {
                        if selection == destination {
                            RoundedRectangle(cornerRadius: 6, style: .continuous)
                                .stroke(JarvisTheme.cyan.opacity(0.32), lineWidth: 1)
                        }
                    }
                }
                .buttonStyle(.plain)
                .accessibilityLabel(destination.title)
                .accessibilityHint(destination.accessibilityDescription)
                .accessibilityAddTraits(selection == destination ? .isSelected : [])
            }

            Spacer()
        }
        .padding(.horizontal, 12)
        .padding(.vertical, 18)
        .frame(width: 184)
        .background(JarvisTheme.panelBottom.opacity(0.78))
    }
}

private struct SettingsHeader: View {
    @ObservedObject var model: JarvisLineModel

    var body: some View {
        HStack(spacing: 12) {
            ZStack {
                RoundedRectangle(cornerRadius: 7, style: .continuous)
                    .fill(JarvisTheme.surfaceRaised)
                    .overlay(
                        RoundedRectangle(cornerRadius: 7, style: .continuous)
                            .stroke(JarvisTheme.gold.opacity(0.34), lineWidth: 1)
                    )
                if let image = NSImage(named: "BrandMark") ?? NSImage(named: "AppIcon") {
                    Image(nsImage: image)
                        .resizable()
                        .scaledToFit()
                        .padding(3)
                } else {
                    Image(systemName: model.statusIcon)
                        .foregroundStyle(JarvisTheme.cyan)
                }
            }
            .frame(width: 40, height: 40)

            VStack(alignment: .leading, spacing: 3) {
                Text("Jarvis Line")
                    .font(.system(size: 16, weight: .semibold))
                    .foregroundStyle(JarvisTheme.primaryText)
                Text("\(model.appVersion)  ·  \(model.cliVersion)")
                    .font(.system(size: 10, weight: .medium, design: .monospaced))
                    .foregroundStyle(JarvisTheme.subtleText)
                    .lineLimit(1)
            }

            Spacer()

            SettingsStatusLabel(
                text: model.status.watcherState == "running" ? "Runtime active" : "Runtime stopped",
                state: model.status.watcherState == "running" ? .healthy : .inactive
            )

            Button {
                Task { await model.refresh() }
            } label: {
                Image(systemName: "arrow.triangle.2.circlepath")
                    .frame(width: 22, height: 22)
            }
            .buttonStyle(.borderless)
            .help("Refresh status")
            .accessibilityLabel("Refresh status")
            .disabled(model.isBusy)
        }
        .padding(.horizontal, 18)
        .frame(height: 62)
        .background(
            LinearGradient(
                colors: [
                    JarvisTheme.panelTop,
                    JarvisTheme.panelBase,
                    JarvisTheme.cyan.opacity(0.06),
                ],
                startPoint: .leading,
                endPoint: .trailing
            )
        )
        .background(WindowDragRegion())
    }
}

private struct SettingsNotice: View {
    let text: String
    let icon: String
    let color: Color

    var body: some View {
        Label(text, systemImage: icon)
            .font(.system(size: 11, weight: .medium))
            .foregroundStyle(color)
            .fixedSize(horizontal: false, vertical: true)
            .frame(maxWidth: .infinity, alignment: .leading)
            .padding(.horizontal, 18)
            .padding(.vertical, 7)
            .background(color.opacity(0.08))
            .overlay(alignment: .bottom) {
                Rectangle()
                    .fill(color.opacity(0.18))
                    .frame(height: 1)
            }
            .textSelection(.enabled)
    }
}

struct SettingsSection<Content: View>: View {
    let title: String
    @ViewBuilder let content: Content

    var body: some View {
        VStack(alignment: .leading, spacing: 0) {
            Text(title)
                .font(.system(size: 11, weight: .semibold))
                .foregroundStyle(JarvisTheme.goldSoft)
                .padding(.bottom, 7)
            Rectangle()
                .fill(JarvisTheme.border.opacity(0.62))
                .frame(height: 1)
            content
        }
        .frame(maxWidth: .infinity, alignment: .leading)
    }
}

struct SettingsRow<Control: View>: View {
    let title: String
    let detail: String?
    let restartRequired: Bool
    @ViewBuilder let control: Control

    init(
        title: String,
        detail: String? = nil,
        restartRequired: Bool = false,
        @ViewBuilder control: () -> Control
    ) {
        self.title = title
        self.detail = detail
        self.restartRequired = restartRequired
        self.control = control()
    }

    var body: some View {
        HStack(alignment: .center, spacing: 18) {
            VStack(alignment: .leading, spacing: 3) {
                HStack(spacing: 6) {
                    Text(title)
                        .font(.system(size: 13, weight: .medium))
                        .foregroundStyle(JarvisTheme.primaryText)
                    if restartRequired {
                        Image(systemName: "arrow.clockwise")
                            .font(.system(size: 9, weight: .semibold))
                            .foregroundStyle(JarvisTheme.goldSoft)
                            .help("Runtime restarts when this change is applied")
                            .accessibilityLabel("Requires runtime restart")
                    }
                }
                if let detail {
                    Text(detail)
                        .font(.system(size: 10))
                        .foregroundStyle(JarvisTheme.subtleText)
                        .fixedSize(horizontal: false, vertical: true)
                }
            }
            .frame(maxWidth: .infinity, alignment: .leading)

            control
        }
        .padding(.vertical, 10)
        .overlay(alignment: .bottom) {
            Rectangle()
                .fill(JarvisTheme.border.opacity(0.32))
                .frame(height: 1)
        }
    }
}

struct SettingsValueRow: View {
    let title: String
    let value: String
    var state: SettingsStatusState?

    init(title: String, value: String, state: SettingsStatusState? = nil) {
        self.title = title
        self.value = value
        self.state = state
    }

    var body: some View {
        SettingsRow(title: title) {
            if let state {
                SettingsStatusLabel(text: value, state: state)
            } else {
                Text(value)
                    .font(.system(size: 12, weight: .medium, design: .monospaced))
                    .foregroundStyle(JarvisTheme.mutedText)
                    .lineLimit(2)
                    .multilineTextAlignment(.trailing)
                    .textSelection(.enabled)
            }
        }
    }
}

enum SettingsStatusState {
    case healthy
    case warning
    case inactive

    var color: Color {
        switch self {
        case .healthy: return JarvisTheme.healthy
        case .warning: return JarvisTheme.goldSoft
        case .inactive: return JarvisTheme.mutedText
        }
    }

    var icon: String {
        switch self {
        case .healthy: return "checkmark.circle.fill"
        case .warning: return "exclamationmark.triangle.fill"
        case .inactive: return "pause.circle"
        }
    }
}

struct SettingsStatusLabel: View {
    let text: String
    let state: SettingsStatusState

    var body: some View {
        Label(text, systemImage: state.icon)
            .font(.system(size: 11, weight: .semibold))
            .foregroundStyle(state.color)
            .lineLimit(1)
            .padding(.horizontal, 8)
            .padding(.vertical, 4)
            .background(state.color.opacity(0.10))
            .clipShape(RoundedRectangle(cornerRadius: 6, style: .continuous))
            .accessibilityLabel(text)
    }
}

private struct SettingsCompatibilityNote: View {
    let text: String

    var body: some View {
        Label(text, systemImage: "info.circle")
            .font(.system(size: 11, weight: .medium))
            .foregroundStyle(JarvisTheme.goldSoft)
            .fixedSize(horizontal: false, vertical: true)
            .frame(maxWidth: .infinity, alignment: .leading)
            .padding(.vertical, 2)
            .accessibilityLabel("Compatibility: \(text)")
    }
}
