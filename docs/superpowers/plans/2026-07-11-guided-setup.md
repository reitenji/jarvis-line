# Guided Setup Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace the primitive interactive setup prompts with one safe, platform-aware setup engine shared by the CLI and a native macOS Setup Assistant.

**Architecture:** A new Python `setup_flow` module owns versioned setup models, recommendations, config construction, and review text. The CLI provides interactive and bounded JSON adapters over that module, while the SwiftUI app decodes the JSON contract and submits reviewed plans without reimplementing backend rules.

**Tech Stack:** Python 3.10+, argparse, dataclasses, pytest, Swift 5.9, SwiftUI, AppKit, Swift Testing, JSON over local subprocess stdin/stdout.

## Global Constraints

- Preserve `jarvis-line setup --default`, `init`, existing config keys, and every current advanced command.
- Do not edit `AGENTS.md`, `CLAUDE.md`, or `GEMINI.md` automatically.
- Use full language names; reject short codes such as `en` and `tr`.
- Recommend Kokoro only for English; recommend platform system TTS for other languages.
- Do not load the ONNX model during inspection; voice testing remains opt-in.
- No network access without explicit Kokoro license/download confirmation.
- JSON setup input is versioned, rejects unknown fields, and is limited to 64 KiB.
- Config writes happen once after confirmation via same-directory temporary file and `os.replace()`.
- The graphical flow is macOS-only; Windows and Linux retain the CLI flow.
- SwiftUI must use controlled native inputs and the existing Jarvis Line visual theme, with no raw JSON editor.
- No telemetry, remote setup reporting, secret-bearing command environment, or automatic instruction-file path writes.

## File Structure

- Create `src/jarvis_line/setup_flow.py`: setup contract, plan validation, recommendations, config construction, review and instruction guidance.
- Create `tests/test_setup_flow.py`: pure domain and prompt tests.
- Create `tests/test_cli_setup.py`: machine adapter, transaction, cancellation, and parser tests.
- Modify `src/jarvis_line/cli.py`: environment detection, atomic JSON writes, setup adapters, side-effect execution, and parser routing.
- Create `apps/macos/JarvisLine/Sources/SetupContract.swift`: Codable contract and plan/result models.
- Create `apps/macos/JarvisLine/Sources/SetupAssistant.swift`: coordinator, window controller, and SwiftUI flow.
- Create `apps/macos/JarvisLine/Tests/JarvisLineTests/SetupContractTests.swift`: decoding, encoding, defaults, and first-run policy tests.
- Create `apps/macos/JarvisLine/Tests/JarvisLineTests/SetupAssistantModelTests.swift`: navigation, apply, cancellation, and retry tests.
- Modify `apps/macos/JarvisLine/Sources/JarvisLineApp.swift`: minimal first-run and Settings/menu integration plus stdin-capable CLI runner.
- Modify `docs/COMMANDS.md`, `README.md`, `apps/macos/JarvisLine/README.md`, and `CHANGELOG.md`: user-facing behavior and examples.

---

### Task 1: Python Setup Domain Contract

**Files:**
- Create: `src/jarvis_line/setup_flow.py`
- Create: `tests/test_setup_flow.py`

**Interfaces:**
- Consumes: `config_contract.DEFAULT_*`, `BACKEND_CAPABILITIES`, and `UI_OPTIONS`.
- Produces: `SetupEnvironment`, `SetupPlan`, `SetupContractError`, `build_inspection()`, `build_config()`, `instruction_guidance()`, and prompt helpers used by later tasks.

- [ ] **Step 1: Write failing contract and recommendation tests**

```python
from jarvis_line import setup_flow


def environment(**overrides):
    values = {
        "platform": "Darwin",
        "config_exists": False,
        "kokoro_ready": True,
        "kokoro_detail": "ready",
        "system_tts_ready": True,
        "system_tts_detail": "say",
        "macos_say_ready": True,
    }
    values.update(overrides)
    return setup_flow.SetupEnvironment(**values)


def test_inspection_recommends_ready_kokoro_for_english():
    inspection = setup_flow.build_inspection(environment(), {}, language="English")
    options = {item["id"]: item for item in inspection["backend_options"]}
    assert inspection["version"] == 1
    assert options["kokoro"]["recommended"] is True
    assert options["system"]["available"] is True


def test_inspection_recommends_system_for_turkish():
    inspection = setup_flow.build_inspection(environment(), {}, language="Turkish")
    options = {item["id"]: item for item in inspection["backend_options"]}
    assert options["system"]["recommended"] is True
    assert options["kokoro"]["available"] is False


def test_plan_rejects_unknown_fields_and_short_language_codes():
    with pytest.raises(setup_flow.SetupContractError, match="unknown field"):
        setup_flow.SetupPlan.from_mapping({**valid_plan(), "instruction_path": "/tmp/AGENTS.md"})
    with pytest.raises(setup_flow.SetupContractError, match="full language name"):
        setup_flow.SetupPlan.from_mapping({**valid_plan(), "language": "tr"})
```

- [ ] **Step 2: Run the domain tests and verify RED**

Run: `.venv/bin/python -m pytest tests/test_setup_flow.py -q`

Expected: collection fails because `jarvis_line.setup_flow` does not exist.

- [ ] **Step 3: Implement the versioned setup models**

```python
SETUP_SCHEMA_VERSION = 1
MAX_SETUP_PLAN_BYTES = 65_536
PLAN_FIELDS = {
    "version", "language", "tts", "speak_mode", "agent_target",
    "instruction_scope", "install_kokoro", "install_codex_hook",
    "start_runtime", "test_voice", "project_path", "command",
}


class SetupContractError(ValueError):
    pass


def validate_full_language(value: Any) -> str:
    text = str(value or "").strip()
    if not text or (text.isascii() and text.isalpha() and len(text) <= 3):
        raise SetupContractError('use a full language name, for example "English" or "Turkish"')
    if len(text) > 80 or any(ord(char) < 32 for char in text):
        raise SetupContractError("language name is invalid")
    return text


@dataclass(frozen=True)
class SetupEnvironment:
    platform: str
    config_exists: bool
    kokoro_ready: bool
    kokoro_detail: str
    system_tts_ready: bool
    system_tts_detail: str
    macos_say_ready: bool


@dataclass(frozen=True)
class SetupPlan:
    version: int
    language: str
    tts: str
    speak_mode: str
    agent_target: str
    instruction_scope: str
    install_kokoro: bool = False
    install_codex_hook: bool = False
    start_runtime: bool = True
    test_voice: bool = False
    project_path: str | None = None
    command: str | list[str] | None = None

    @classmethod
    def from_mapping(cls, value: Mapping[str, Any]) -> "SetupPlan":
        unknown = sorted(set(value) - PLAN_FIELDS)
        if unknown:
            raise SetupContractError(f"unknown field: {unknown[0]}")
        if value.get("version") != SETUP_SCHEMA_VERSION:
            raise SetupContractError("unsupported setup plan version")
        language = validate_full_language(value.get("language"))

        def enum(name: str, allowed: set[str]) -> str:
            selected = value.get(name)
            if selected not in allowed:
                raise SetupContractError(f"invalid {name}: {selected!r}")
            return str(selected)

        def boolean(name: str, default: bool) -> bool:
            selected = value.get(name, default)
            if type(selected) is not bool:
                raise SetupContractError(f"{name} must be boolean")
            return selected

        tts = enum("tts", {"kokoro", "system", "macos", "command"})
        speak_mode = enum("speak_mode", {"final_only", "commentary_and_final", "off"})
        agent_target = enum("agent_target", {"agents", "codex", "claude", "gemini"})
        scope = enum("instruction_scope", {"project", "global"})
        install_kokoro = boolean("install_kokoro", False)
        install_hook = boolean("install_codex_hook", False)
        if install_kokoro and (tts != "kokoro" or language != "English"):
            raise SetupContractError("verified Kokoro install requires English and the kokoro backend")
        if install_hook and agent_target != "codex":
            raise SetupContractError("Codex hook installation requires the codex target")

        project_path = value.get("project_path")
        if project_path is not None and (not isinstance(project_path, str) or "\x00" in project_path):
            raise SetupContractError("project_path must be a safe string or null")
        if scope == "global" and project_path is not None:
            raise SetupContractError("global instruction scope cannot include project_path")

        command = value.get("command")
        command_parts = [command] if isinstance(command, str) else command
        if command_parts is not None:
            if not isinstance(command_parts, list) or not command_parts or len(command_parts) > 32:
                raise SetupContractError("command must be a string or 1-32 argument strings")
            if any(not isinstance(part, str) or not part or "\x00" in part for part in command_parts):
                raise SetupContractError("command arguments must be non-empty safe strings")
            if sum(len(part) for part in command_parts) > 2048:
                raise SetupContractError("command exceeds 2048 characters")

        return cls(
            version=SETUP_SCHEMA_VERSION,
            language=language,
            tts=tts,
            speak_mode=speak_mode,
            agent_target=agent_target,
            instruction_scope=scope,
            install_kokoro=install_kokoro,
            install_codex_hook=install_hook,
            start_runtime=boolean("start_runtime", True),
            test_voice=boolean("test_voice", False),
            project_path=project_path,
            command=command,
        )
```

- [ ] **Step 4: Implement deterministic options and config construction**

```python
def backend_options(env: SetupEnvironment, language: str, current: Mapping[str, Any]) -> list[dict[str, Any]]:
    english = normalize_language(language) == "English"
    kokoro_supported = env.platform in {"Darwin", "Linux", "Windows"}
    kokoro_recommended = english and env.kokoro_ready
    system_recommended = (not kokoro_recommended) and env.system_tts_ready
    command_ready = bool(current.get("command"))
    return [
        {
            "id": "kokoro",
            "label": "Kokoro local",
            "available": english and kokoro_supported,
            "ready": env.kokoro_ready,
            "recommended": kokoro_recommended,
            "requires_install": english and not env.kokoro_ready,
            "detail": env.kokoro_detail if english else "Use a matching custom model for non-English speech.",
        },
        {
            "id": "system",
            "label": "System voice",
            "available": env.system_tts_ready,
            "ready": env.system_tts_ready,
            "recommended": system_recommended,
            "requires_install": False,
            "detail": env.system_tts_detail,
        },
        {
            "id": "macos",
            "label": "macOS say",
            "available": env.platform == "Darwin" and env.macos_say_ready,
            "ready": env.macos_say_ready,
            "recommended": False,
            "requires_install": False,
            "detail": "Explicit macOS voice and rate controls.",
        },
        {
            "id": "command",
            "label": "Advanced custom TTS",
            "available": command_ready,
            "ready": command_ready,
            "recommended": not kokoro_recommended and not system_recommended and command_ready,
            "requires_install": False,
            "detail": "Uses the existing reviewed custom command." if command_ready else "Configure a custom command first.",
        },
    ]


def build_config(plan: SetupPlan, current: Mapping[str, Any]) -> dict[str, Any]:
    cfg = config_for_preset(plan.tts, dict(current))
    cfg["line_language"] = plan.language
    cfg["speak_mode"] = plan.speak_mode
    cfg["speech_enabled"] = plan.speak_mode != "off"
    if plan.tts == "kokoro" and plan.language == "English":
        cfg["lang"] = "en-gb"
    if plan.tts == "command" and plan.command:
        cfg["command"] = plan.command
    return cfg
```

- [ ] **Step 5: Run domain tests and verify GREEN**

Run: `.venv/bin/python -m pytest tests/test_setup_flow.py -q`

Expected: all setup domain tests pass.

- [ ] **Step 6: Commit the setup domain**

```bash
git add src/jarvis_line/setup_flow.py tests/test_setup_flow.py
git commit -m "feat: add versioned setup domain"
```

---

### Task 2: Atomic Apply And Machine CLI

**Files:**
- Modify: `src/jarvis_line/cli.py`
- Create: `tests/test_cli_setup.py`

**Interfaces:**
- Consumes: `setup_flow.SetupPlan`, `build_inspection()`, `build_config()`, and existing Kokoro/hook/runtime/doctor helpers.
- Produces: `detect_setup_environment()`, `apply_setup_plan()`, `setup_inspect()`, `setup_apply()`, and parser commands consumed by Swift.

- [ ] **Step 1: Write failing parser, JSON-boundary, and transaction tests**

```python
def test_setup_inspect_prints_parseable_versioned_json(monkeypatch, capsys):
    monkeypatch.setattr(cli, "detect_setup_environment", lambda: ready_environment())
    monkeypatch.setattr(cli, "load_effective_config", lambda default=None: {"tts": "system"})
    assert cli.setup_inspect(argparse.Namespace(json_output=True)) == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["version"] == 1
    assert payload["config_exists"] is False


def test_setup_apply_rejects_oversized_stdin_before_mutation(monkeypatch, capsys):
    monkeypatch.setattr(sys, "stdin", io.StringIO("x" * 65_537))
    writes = []
    monkeypatch.setattr(cli, "save_json", lambda *_args: writes.append(True))
    assert cli.setup_apply(argparse.Namespace(stdin=True, json_output=True)) == 2
    assert writes == []
    assert json.loads(capsys.readouterr().out)["ok"] is False


def test_apply_writes_config_once_after_preflight(monkeypatch, tmp_path):
    patch_setup_paths(monkeypatch, tmp_path)
    calls = []
    monkeypatch.setattr(cli, "run_setup_kokoro_install", lambda: calls.append("kokoro") or None)
    monkeypatch.setattr(cli, "save_json", lambda path, data: calls.append(("write", data["tts"])))
    monkeypatch.setattr(cli, "install_codex", lambda _args: calls.append("hook") or 0)
    monkeypatch.setattr(cli, "launch_runtime", lambda _args, selected: calls.append("runtime") or 0)
    result = cli.apply_setup_plan(kokoro_codex_plan(), json_mode=True)
    assert result["ok"] is True
    assert calls == ["kokoro", ("write", "kokoro"), "hook", "runtime"]
```

- [ ] **Step 2: Run the machine adapter tests and verify RED**

Run: `.venv/bin/python -m pytest tests/test_cli_setup.py -q`

Expected: failures for missing setup parser and apply functions.

- [ ] **Step 3: Make CLI JSON writes atomic**

Replace `save_json()` with a same-directory temporary write:

```python
def save_json(path: Path, data) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = json.dumps(data, ensure_ascii=False, indent=2) + "\n"
    fd, temporary = tempfile.mkstemp(prefix=f".{path.name}.", suffix=".tmp", dir=path.parent)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            handle.write(payload)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
        if os.name != "nt":
            path.chmod(0o600)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)
```

Add a test that monkeypatches `os.replace` to fail and confirms the original
file remains readable and no temporary file remains.

- [ ] **Step 4: Implement inspection and bounded plan parsing**

```python
def detect_setup_environment() -> setup_flow.SetupEnvironment:
    kokoro_ok, kokoro_detail = kokoro_ready()
    system_ok, system_detail = system_tts_ready()
    return setup_flow.SetupEnvironment(
        platform=platform.system(),
        config_exists=CONFIG_PATH.exists(),
        kokoro_ready=kokoro_ok,
        kokoro_detail=kokoro_detail,
        system_tts_ready=system_ok,
        system_tts_detail=system_detail,
        macos_say_ready=platform.system() == "Darwin" and bool(shutil.which("say")),
    )


def read_setup_plan_stdin() -> setup_flow.SetupPlan:
    text = sys.stdin.read(setup_flow.MAX_SETUP_PLAN_BYTES + 1)
    if len(text) > setup_flow.MAX_SETUP_PLAN_BYTES:
        raise setup_flow.SetupContractError("setup plan exceeds 64 KiB")
    return setup_flow.SetupPlan.from_mapping(json.loads(text))
```

- [ ] **Step 5: Implement one apply pipeline and structured result**

`apply_setup_plan()` must:

1. Build and validate config in memory.
2. Run approved Kokoro download/dependency preflight before config mutation.
3. Create `jarvis_line_config.json.setup.bak` once when an old config exists.
4. Write config once.
5. Install the Codex hook only when selected.
6. Start/restart runtime only when selected.
7. Obtain doctor JSON and run the optional quiet voice test.
8. Return `{"version": 1, "ok": ..., "steps": ..., "instruction": ...}`.

Use `contextlib.redirect_stdout`/`redirect_stderr` for Python wrappers and add a
`quiet` argument to Kokoro dependency install and TTS test subprocesses so JSON
stdout cannot be polluted by child processes.

- [ ] **Step 6: Route setup subcommands without breaking existing syntax**

```python
setup = sub.add_parser("setup", help="Configure Jarvis Line.")
setup.add_argument("--default", action="store_true")
setup.add_argument("--test", action="store_true")
setup_sub = setup.add_subparsers(dest="setup_command")
inspect = setup_sub.add_parser("inspect", help="Inspect setup choices for apps and automation.")
inspect.add_argument("--json", action="store_true", dest="json_output", required=True)
apply = setup_sub.add_parser("apply", help="Apply a reviewed setup plan.")
apply.add_argument("--stdin", action="store_true", required=True)
apply.add_argument("--json", action="store_true", dest="json_output", required=True)
setup.set_defaults(func=setup_command)
```

`setup_command()` dispatches `inspect`, `apply`, `--default`, or the interactive
wizard in that order.

- [ ] **Step 7: Run focused and full Python tests**

Run:

```bash
.venv/bin/python -m pytest tests/test_setup_flow.py tests/test_cli_setup.py tests/test_cli.py -q
.venv/bin/python -m pytest -q
```

Expected: setup tests and the full suite pass.

- [ ] **Step 8: Commit the machine adapter**

```bash
git add src/jarvis_line/cli.py tests/test_cli_setup.py
git commit -m "feat: add setup machine interface"
```

---

### Task 3: Interactive Guided CLI Wizard

**Files:**
- Modify: `src/jarvis_line/setup_flow.py`
- Modify: `src/jarvis_line/cli.py`
- Modify: `tests/test_setup_flow.py`
- Modify: `tests/test_cli_setup.py`

**Interfaces:**
- Consumes: the same inspection and apply pipeline as machine clients.
- Produces: `collect_setup_plan()` and a replacement `setup_wizard()` with no pre-confirmation side effects.

- [ ] **Step 1: Write failing prompt, cancellation, and parity tests**

```python
def test_prompt_choice_retries_invalid_input():
    answers = iter(["99", "x", "2"])
    output = []
    chosen = setup_flow.prompt_choice(
        "Voice", [("kokoro", "Kokoro"), ("system", "System")],
        default="kokoro", input_fn=lambda _prompt: next(answers), output_fn=output.append,
    )
    assert chosen == "system"
    assert sum("Choose a number" in line for line in output) == 2


def test_wizard_decline_leaves_files_and_runtime_unchanged(monkeypatch, tmp_path):
    patch_setup_paths(monkeypatch, tmp_path)
    original = {"tts": "system", "line_language": "English"}
    cli.save_json(cli.CONFIG_PATH, original)
    monkeypatch.setattr(cli, "collect_setup_plan", lambda *_args, **_kwargs: sample_plan())
    monkeypatch.setattr(cli, "confirm_setup_plan", lambda *_args, **_kwargs: False)
    assert cli.setup_wizard(argparse.Namespace(test=False)) == 0
    assert cli.load_json(cli.CONFIG_PATH, {}) == original
```

- [ ] **Step 2: Run wizard tests and verify RED**

Run: `.venv/bin/python -m pytest tests/test_setup_flow.py tests/test_cli_setup.py -q`

Expected: missing prompt and collection helpers.

- [ ] **Step 3: Implement injectable prompt helpers and plan collection**

The flow selects language, available backend, speech mode, agent, scope, Codex
hook, runtime, and voice test. Common languages come from `UI_OPTIONS`; `Other
language...` calls the full-name validator. Project scope uses `Path.cwd()` for
guidance only. Advanced command TTS is selectable only when a command is already
configured; otherwise the wizard prints the existing `tts use command` path.

- [ ] **Step 4: Replace the old incremental wizard**

```python
def setup_wizard(args) -> int:
    try:
        env = detect_setup_environment()
        current = load_effective_config({})
        plan = setup_flow.collect_setup_plan(
            env, current, force_test=bool(getattr(args, "test", False))
        )
        for line in setup_flow.review_lines(plan, env):
            print(line)
        if not setup_flow.prompt_yes_no("Apply this setup?", default=True):
            print("Setup cancelled. No changes were made.")
            return 0
        result = apply_setup_plan(plan, json_mode=False)
        print_setup_result(result)
        return 0 if result["ok"] else 1
    except (EOFError, KeyboardInterrupt):
        print("\nSetup cancelled. No changes were made.", file=sys.stderr)
        return 130
```

- [ ] **Step 5: Run interactive, parser, and full tests**

Run:

```bash
.venv/bin/python -m pytest tests/test_setup_flow.py tests/test_cli_setup.py -q
.venv/bin/python -m pytest -q
```

Expected: all tests pass; existing `setup --default` and `init` tests stay green.

- [ ] **Step 6: Commit the guided CLI flow**

```bash
git add src/jarvis_line/setup_flow.py src/jarvis_line/cli.py tests/test_setup_flow.py tests/test_cli_setup.py
git commit -m "feat: guide interactive setup"
```

---

### Task 4: Swift Setup Contract And CLI Bridge

**Files:**
- Create: `apps/macos/JarvisLine/Sources/SetupContract.swift`
- Create: `apps/macos/JarvisLine/Tests/JarvisLineTests/SetupContractTests.swift`
- Modify: `apps/macos/JarvisLine/Sources/JarvisLineApp.swift`

**Interfaces:**
- Consumes: JSON from `setup inspect --json` and `setup apply --stdin --json`.
- Produces: `SetupInspection`, `SetupBackendOption`, `SetupPlanPayload`, `SetupApplyResult`, `JarvisLineCommandRunning`, `inspectSetup()`, and `applySetup()`.

- [ ] **Step 1: Write failing Codable and first-run policy tests**

```swift
@Test func inspectionDecodesVersionedChoices() throws {
    let inspection = try SetupInspection.decode(#"{"version":1,"config_exists":false,"platform":"Darwin","languages":["English","Turkish"],"backend_options":[{"id":"kokoro","label":"Kokoro local","available":true,"ready":true,"recommended":true,"requires_install":false,"detail":"ready"}],"current":{"language":"English","tts":"kokoro","speak_mode":"final_only"}}"#)
    #expect(inspection.version == 1)
    #expect(inspection.backendOptions.first?.recommended == true)
    #expect(SetupFirstRunPolicy.shouldOffer(configExists: false, wasOffered: false))
    #expect(!SetupFirstRunPolicy.shouldOffer(configExists: true, wasOffered: false))
}


@Test func planEncodingUsesSnakeCaseAndNoInstructionPath() throws {
    let data = try SetupPlanPayload.defaults.encoded()
    let text = String(decoding: data, as: UTF8.self)
    #expect(text.contains("\"agent_target\""))
    #expect(!text.contains("instruction_path"))
}
```

- [ ] **Step 2: Run Swift tests and verify RED**

Run: `swift test --package-path apps/macos/JarvisLine`

Expected: compile failure because setup contract types do not exist.

- [ ] **Step 3: Implement typed contract models**

```swift
struct SetupInspection: Decodable, Sendable {
    let version: Int
    let configExists: Bool
    let platform: String
    let languages: [String]
    let backendOptions: [SetupBackendOption]
    let current: SetupCurrentValues

    static func decode(_ text: String) throws -> Self {
        let decoder = JSONDecoder()
        decoder.keyDecodingStrategy = .convertFromSnakeCase
        let value = try decoder.decode(Self.self, from: Data(text.utf8))
        guard value.version == 1 else {
            throw SetupContractError.unsupportedVersion(value.version)
        }
        return value
    }
}


struct SetupBackendOption: Decodable, Identifiable, Sendable {
    let id: String
    let label: String
    let available: Bool
    let ready: Bool
    let recommended: Bool
    let requiresInstall: Bool
    let detail: String
}


struct SetupCurrentValues: Decodable, Sendable {
    let language: String
    let tts: String
    let speakMode: String
}


struct SetupPlanPayload: Codable, Equatable, Sendable {
    var version = 1
    var language: String
    var tts: String
    var speakMode: String
    var agentTarget: String
    var instructionScope: String
    var installKokoro: Bool
    var installCodexHook: Bool
    var startRuntime: Bool
    var testVoice: Bool
    var projectPath: String?
    var command: String?

    init(
        version: Int = 1,
        language: String,
        tts: String,
        speakMode: String,
        agentTarget: String,
        instructionScope: String,
        installKokoro: Bool,
        installCodexHook: Bool,
        startRuntime: Bool,
        testVoice: Bool,
        projectPath: String?,
        command: String?
    ) {
        self.version = version
        self.language = language
        self.tts = tts
        self.speakMode = speakMode
        self.agentTarget = agentTarget
        self.instructionScope = instructionScope
        self.installKokoro = installKokoro
        self.installCodexHook = installCodexHook
        self.startRuntime = startRuntime
        self.testVoice = testVoice
        self.projectPath = projectPath
        self.command = command
    }

    static let defaults = SetupPlanPayload(
        language: "English",
        tts: "system",
        speakMode: "final_only",
        agentTarget: "codex",
        instructionScope: "project",
        installKokoro: false,
        installCodexHook: true,
        startRuntime: true,
        testVoice: false,
        projectPath: nil,
        command: nil
    )

    init(inspection: SetupInspection) {
        let available = inspection.backendOptions.filter(\.available)
        let currentBackend = available.first(where: { $0.id == inspection.current.tts })
        let selected = currentBackend ?? available.first(where: \.recommended) ?? available.first
        self = .defaults
        language = inspection.current.language
        tts = selected?.id ?? "system"
        speakMode = inspection.current.speakMode
        installKokoro = selected?.requiresInstall == true
    }

    func encoded() throws -> Data {
        let encoder = JSONEncoder()
        encoder.keyEncodingStrategy = .convertToSnakeCase
        return try encoder.encode(self)
    }
}


struct SetupInstructionResult: Decodable, Sendable {
    let command: String
    let filename: String
    let scope: String
    let text: String
}


struct SetupResultStep: Decodable, Sendable {
    let id: String
    let ok: Bool
    let detail: String
}


struct SetupApplyResult: Decodable, Sendable {
    let version: Int
    let ok: Bool
    let steps: [SetupResultStep]
    let instruction: SetupInstructionResult

    static func decode(_ text: String) throws -> Self {
        let decoder = JSONDecoder()
        decoder.keyDecodingStrategy = .convertFromSnakeCase
        let value = try decoder.decode(Self.self, from: Data(text.utf8))
        guard value.version == 1 else {
            throw SetupContractError.unsupportedVersion(value.version)
        }
        return value
    }
}


enum SetupContractError: LocalizedError {
    case unsupportedVersion(Int)

    var errorDescription: String? {
        switch self {
        case .unsupportedVersion(let version):
            return "Unsupported setup contract version: \(version)"
        }
    }
}
```

- [ ] **Step 4: Make the CLI runner accept bounded stdin**

Introduce a protocol and preserve all existing call sites with a default value:

```swift
protocol JarvisLineCommandRunning: Sendable {
    func run(_ args: [String], stdin: Data?) async throws -> String
}


extension JarvisLineCommandRunning {
    func run(_ args: [String]) async throws -> String {
        try await run(args, stdin: nil)
    }
}


struct JarvisLineCLI: JarvisLineCommandRunning {
    func run(_ args: [String], stdin: Data? = nil) async throws -> String {
        let executable = findExecutable()
        return try await withCheckedThrowingContinuation { continuation in
            let process = Process()
            process.executableURL = URL(fileURLWithPath: executable)
            process.arguments = args

            let outputPipe = Pipe()
            let errorPipe = Pipe()
            let inputPipe = stdin == nil ? nil : Pipe()
            process.standardOutput = outputPipe
            process.standardError = errorPipe
            process.standardInput = inputPipe

            do {
                try process.run()
                if let stdin, let inputPipe {
                    inputPipe.fileHandleForWriting.write(stdin)
                    try inputPipe.fileHandleForWriting.close()
                }
            } catch {
                continuation.resume(throwing: error)
                return
            }

            process.terminationHandler = { proc in
                let output = String(
                    data: outputPipe.fileHandleForReading.readDataToEndOfFile(),
                    encoding: .utf8
                ) ?? ""
                let error = String(
                    data: errorPipe.fileHandleForReading.readDataToEndOfFile(),
                    encoding: .utf8
                ) ?? ""
                if proc.terminationStatus == 0 {
                    continuation.resume(returning: output)
                } else {
                    continuation.resume(throwing: CLIError(output + error))
                }
            }
        }
    }
}
```

Add `inspectSetup()` and `applySetup(_:)` helpers that use snake-case JSON
encoding and reject unsupported response versions.

- [ ] **Step 5: Run Swift and Python contract tests**

Run:

```bash
swift test --package-path apps/macos/JarvisLine
.venv/bin/python -m pytest tests/test_cli_setup.py -q
```

Expected: both contract implementations pass their version and shape tests.

- [ ] **Step 6: Commit the Swift bridge**

```bash
git add apps/macos/JarvisLine/Sources/SetupContract.swift apps/macos/JarvisLine/Sources/JarvisLineApp.swift apps/macos/JarvisLine/Tests/JarvisLineTests/SetupContractTests.swift
git commit -m "feat: bridge setup contract to macos"
```

---

### Task 5: Native macOS Setup Assistant

**Files:**
- Create: `apps/macos/JarvisLine/Sources/SetupAssistant.swift`
- Create: `apps/macos/JarvisLine/Tests/JarvisLineTests/SetupAssistantModelTests.swift`
- Modify: `apps/macos/JarvisLine/Sources/JarvisLineApp.swift`

**Interfaces:**
- Consumes: Task 4 contract and `JarvisLineCommandRunning`.
- Produces: `SetupAssistantModel`, `SetupAssistantWindowController`, `SetupAssistantView`, first-run offering, Settings relaunch, copy/test/done completion actions.

- [ ] **Step 1: Write failing coordinator tests with a fake runner**

```swift
actor FakeSetupRunner: JarvisLineCommandRunning {
    var calls: [([String], Data?)] = []
    let inspectionJSON: String
    let resultJSON: String

    init(inspectionJSON: String, resultJSON: String) {
        self.inspectionJSON = inspectionJSON
        self.resultJSON = resultJSON
    }

    func run(_ args: [String], stdin: Data?) async throws -> String {
        calls.append((args, stdin))
        return args.contains("inspect") ? inspectionJSON : resultJSON
    }
}


@MainActor
@Test func applySubmitsReviewedPlanAndCompletes() async throws {
    let runner = FakeSetupRunner(inspectionJSON: fixtureInspection, resultJSON: fixtureSuccess)
    let model = SetupAssistantModel(runner: runner)
    await model.load()
    model.plan.language = "Turkish"
    await model.apply()
    #expect(model.step == .complete)
    #expect(model.result?.ok == true)
    #expect(await runner.calls.count == 2)
}


@MainActor
@Test func unavailableBackendBlocksContinueAndCancelDoesNotApply() async {
    // Load an inspection with unavailable Kokoro, select it, and assert
    // canContinue is false and the fake runner has no apply call after cancel.
}
```

- [ ] **Step 2: Run Swift tests and verify RED**

Run: `swift test --package-path apps/macos/JarvisLine`

Expected: missing assistant coordinator types.

- [ ] **Step 3: Implement the focused coordinator and first-run preference**

`SetupAssistantModel` owns only setup state:

```swift
@MainActor
final class SetupAssistantModel: ObservableObject {
    enum Step: Int, CaseIterable { case welcome, language, voice, speech, agent, review, applying, complete }
    @Published var step: Step = .welcome
    @Published var inspection: SetupInspection?
    @Published var plan = SetupPlanPayload.defaults
    @Published var result: SetupApplyResult?
    @Published var isBusy = false
    @Published var errorMessage: String?

    let runner: any JarvisLineCommandRunning
    let didComplete: @MainActor () async -> Void

    init(
        runner: any JarvisLineCommandRunning = JarvisLineCLI(),
        didComplete: @escaping @MainActor () async -> Void = {}
    ) {
        self.runner = runner
        self.didComplete = didComplete
    }

    var canContinue: Bool {
        guard !isBusy else { return false }
        switch step {
        case .language: return !plan.language.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty
        case .voice:
            return inspection?.backendOptions.first(where: { $0.id == plan.tts })?.available == true
        case .agent: return plan.instructionScope != "project" || plan.projectPath != nil
        case .applying: return false
        default: return true
        }
    }

    func load() async {
        isBusy = true
        defer { isBusy = false }
        do {
            let output = try await runner.run(["setup", "inspect", "--json"])
            let decoded = try SetupInspection.decode(output)
            inspection = decoded
            plan = SetupPlanPayload(inspection: decoded)
            errorMessage = nil
        } catch {
            errorMessage = error.localizedDescription
        }
    }

    func next() {
        guard canContinue,
              let index = Step.allCases.firstIndex(of: step),
              index + 1 < Step.allCases.count else { return }
        step = Step.allCases[index + 1]
    }

    func back() {
        guard !isBusy,
              let index = Step.allCases.firstIndex(of: step),
              index > 0 else { return }
        step = Step.allCases[index - 1]
    }

    func apply() async {
        guard canContinue else { return }
        isBusy = true
        step = .applying
        errorMessage = nil
        do {
            let data = try plan.encoded()
            let output = try await runner.run(
                ["setup", "apply", "--stdin", "--json"],
                stdin: data
            )
            let decoded = try SetupApplyResult.decode(output)
            result = decoded
            if decoded.ok {
                step = .complete
                await didComplete()
            } else {
                step = .review
                errorMessage = decoded.steps.first(where: { !$0.ok })?.detail ?? "Setup failed."
            }
        } catch {
            step = .review
            errorMessage = error.localizedDescription
        }
        isBusy = false
    }

    func copyInstructions() {
        guard let text = result?.instruction.text else { return }
        NSPasteboard.general.clearContents()
        NSPasteboard.general.setString(text, forType: .string)
    }
}
```

Store only `setupAssistantWasOffered` in `UserDefaults`; config existence remains
authoritative from inspection.

- [ ] **Step 4: Implement the native window and views**

Create one `NSWindow` through `SetupAssistantWindowController.shared` with a
stable 700 x 560 content size, 640 x 500 minimum, current dark theme, fixed
header/footer, scrollable center, and no nested cards. Reopening activates the
existing window. Screens use:

- Welcome: detected readiness and privacy statement.
- Language: Picker plus controlled Other-language field.
- Voice: selection rows with recommended/disabled states and Kokoro license.
- Speech: segmented final/commentary mode and enabled toggle semantics.
- Agent: agent and scope segmented controls, project folder picker, Codex hook toggle.
- Review: concise values and explicit network/audio actions.
- Applying: one progress view and safe step label.
- Complete: health summary, Copy Instructions, optional Test Voice, Done.

- [ ] **Step 5: Integrate first-run and manual entry points minimally**

In `JarvisLineApp.swift`:

- Register `AppDelegate.showSetupWindow` beside the Settings closure.
- After the first successful model refresh, call `offerIfNeeded` only when
  inspection says config is absent and the offer preference is false.
- Show `Complete Setup` in the menu panel when `setupRequired` is true.
- Add `Run Setup Assistant...` inside the full Settings Runtime section.
- Refresh `JarvisLineModel` exactly once after successful apply.

- [ ] **Step 6: Run Swift tests and package smoke**

Run:

```bash
swift test --package-path apps/macos/JarvisLine
bash scripts/verify-macos-artifacts.sh
```

Expected: Swift tests pass; app and DMG verification prints `macos_artifacts_ok`.

- [ ] **Step 7: Commit the native assistant**

```bash
git add apps/macos/JarvisLine/Sources/SetupAssistant.swift apps/macos/JarvisLine/Sources/JarvisLineApp.swift apps/macos/JarvisLine/Tests/JarvisLineTests/SetupAssistantModelTests.swift
git commit -m "feat: add native setup assistant"
```

---

### Task 6: Documentation, Visual QA, And Release Verification

**Files:**
- Modify: `README.md`
- Modify: `docs/COMMANDS.md`
- Modify: `apps/macos/JarvisLine/README.md`
- Modify: `CHANGELOG.md`
- Modify: `tests/test_release_metadata.py` only if documentation assertions need the new setup references.

**Interfaces:**
- Consumes: completed CLI and app behavior.
- Produces: user-facing setup guidance and final verification evidence.

- [ ] **Step 1: Add documentation assertions before editing docs**

```python
def test_guided_setup_documentation_is_present():
    readme = (ROOT / "README.md").read_text(encoding="utf-8")
    commands = (ROOT / "docs/COMMANDS.md").read_text(encoding="utf-8")
    app_readme = (ROOT / "apps/macos/JarvisLine/README.md").read_text(encoding="utf-8")
    assert "jarvis-line setup" in readme
    assert "setup inspect --json" in commands
    assert "Setup Assistant" in app_readme
```

- [ ] **Step 2: Run the documentation test and verify RED**

Run: `.venv/bin/python -m pytest tests/test_release_metadata.py -q`

Expected: failure for missing Guided Setup/Setup Assistant wording.

- [ ] **Step 3: Update concise user documentation**

Document:

- `jarvis-line setup` as the recommended guided first run.
- `setup --default` as non-interactive low-friction setup.
- Network and audio confirmation points.
- Manual instruction-paste requirement and project/global scope.
- macOS first-run Setup Assistant and Settings relaunch path.
- Machine commands in `docs/COMMANDS.md`, clearly marked for apps/automation.
- One `Unreleased` changelog entry covering the shared setup engine and native UI.

- [ ] **Step 4: Run all local automated checks**

Run:

```bash
.venv/bin/python -m compileall -q src/jarvis_line
.venv/bin/python -m pytest -q
.venv/bin/python tests/run_smoke.py
swift test --package-path apps/macos/JarvisLine
bash scripts/verify-macos-artifacts.sh
git diff --check
```

Expected: zero failures and `macos_artifacts_ok`.

- [ ] **Step 5: Exercise isolated CLI flows without user-state mutation**

Use a temporary HOME and command backend:

```bash
tmp_home="$(mktemp -d)"
HOME="$tmp_home" PYTHONPATH=src .venv/bin/python -m jarvis_line.cli setup inspect --json
printf '%s' "$SYSTEM_PLAN_JSON" | HOME="$tmp_home" PYTHONPATH=src .venv/bin/python -m jarvis_line.cli setup apply --stdin --json
test ! -e "$tmp_home/AGENTS.md"
rm -rf "$tmp_home"
```

Expected: parseable version-1 JSON, healthy config/runtime result where mocked or
supported, and no instruction Markdown creation.

- [ ] **Step 6: Run graphical visual QA**

Build and launch the development app against the branch CLI, then inspect
screenshots at 700 x 560 and 640 x 500 for every setup step. Verify:

- no clipping or overlap with long language/backend labels;
- unavailable TTS cannot be selected;
- Back/Continue footer remains stable;
- progress, failure, retry, and completion states are readable;
- first-run and Settings entry points reuse one window;
- cancel changes no Jarvis config/hook/runtime files.

- [ ] **Step 7: Commit documentation and QA support**

```bash
git add README.md docs/COMMANDS.md apps/macos/JarvisLine/README.md CHANGELOG.md tests/test_release_metadata.py
git commit -m "docs: explain guided setup flows"
```

- [ ] **Step 8: Request code review and fix validated findings**

Run a focused review of:

- transaction ordering and cancellation safety;
- JSON input validation and stdout purity;
- command/custom-path injection boundaries;
- Swift concurrency and window ownership;
- first-run behavior for existing users;
- resource use and accidental ONNX/audio startup.

Apply only evidence-backed findings, then rerun Step 4.

- [ ] **Step 9: Push and open the feature pull request to develop**

```bash
git push origin feature/guided-setup
gh pr create --base develop --head feature/guided-setup --title "Add guided setup flows" --body-file build/guided-setup-pr.md
gh pr checks --watch --interval 10
```

Expected: Linux/macOS/Windows Python matrix, macOS app, and security dependency
checks all pass before merge consideration.
