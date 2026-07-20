from __future__ import annotations

import hashlib
import json
import re
import shlex
from dataclasses import dataclass
from typing import Any, Mapping
from urllib.parse import urlsplit


ATTENTION_TYPES = {"input_required", "permission_request"}
MAX_ARGUMENT_CHARS = 32_768
MAX_FIELD_CHARS = 1_024
MAX_QUESTION_CHARS = 160
MAX_SPOKEN_CHARS = 240


@dataclass(frozen=True)
class AttentionMessage:
    category: str
    line: str


@dataclass(frozen=True)
class InputRequest:
    header: str
    question: str
    correlation_token: str | None


@dataclass(frozen=True)
class _PermissionIntent:
    category: str
    detail: str = ""
    tool_label: str = ""


_ACTIONS = {
    "English": {
        "network": "connect to the network",
        "dependency_install": "install project dependencies",
        "git_push": "push changes to the remote repository",
        "git_pull": "pull changes from the remote repository",
        "git_clone": "clone a remote repository",
        "file_delete": "delete files",
        "process_terminate": "stop a process",
        "privileged": "run a privileged command",
        "test_build": "run project checks",
        "file_modify": "modify project files",
        "github_pull_request": "create a GitHub pull request",
    },
    "Turkish": {
        "network": "ağa bağlanmak",
        "dependency_install": "proje bağımlılıklarını yüklemek",
        "git_push": "değişiklikleri uzak depoya göndermek",
        "git_pull": "değişiklikleri uzak depodan almak",
        "git_clone": "uzak depoyu klonlamak",
        "file_delete": "dosyaları silmek",
        "process_terminate": "bir işlemi durdurmak",
        "privileged": "yönetici yetkili bir komut çalıştırmak",
        "test_build": "proje kontrollerini çalıştırmak",
        "file_modify": "proje dosyalarını değiştirmek",
        "github_pull_request": "GitHub pull request oluşturmak",
    },
    "French": {
        "network": "se connecter au réseau",
        "dependency_install": "installer les dépendances du projet",
        "git_push": "envoyer les modifications vers le dépôt distant",
        "git_pull": "récupérer les modifications du dépôt distant",
        "git_clone": "cloner un dépôt distant",
        "file_delete": "supprimer des fichiers",
        "process_terminate": "arrêter un processus",
        "privileged": "exécuter une commande privilégiée",
        "test_build": "exécuter les contrôles du projet",
        "file_modify": "modifier les fichiers du projet",
        "github_pull_request": "créer une pull request GitHub",
    },
    "Italian": {
        "network": "connettersi alla rete",
        "dependency_install": "installare le dipendenze del progetto",
        "git_push": "inviare le modifiche al repository remoto",
        "git_pull": "ricevere le modifiche dal repository remoto",
        "git_clone": "clonare un repository remoto",
        "file_delete": "eliminare file",
        "process_terminate": "arrestare un processo",
        "privileged": "eseguire un comando privilegiato",
        "test_build": "eseguire i controlli del progetto",
        "file_modify": "modificare i file del progetto",
        "github_pull_request": "creare una pull request GitHub",
    },
    "Japanese": {
        "network": "ネットワークに接続する",
        "dependency_install": "プロジェクトの依存関係をインストールする",
        "git_push": "変更をリモートリポジトリへ送信する",
        "git_pull": "リモートリポジトリから変更を取得する",
        "git_clone": "リモートリポジトリを複製する",
        "file_delete": "ファイルを削除する",
        "process_terminate": "プロセスを停止する",
        "privileged": "管理者権限のコマンドを実行する",
        "test_build": "プロジェクトの確認を実行する",
        "file_modify": "プロジェクトファイルを変更する",
        "github_pull_request": "GitHubプルリクエストを作成する",
    },
    "Chinese": {
        "network": "连接网络",
        "dependency_install": "安装项目依赖",
        "git_push": "将更改推送到远程仓库",
        "git_pull": "从远程仓库拉取更改",
        "git_clone": "克隆远程仓库",
        "file_delete": "删除文件",
        "process_terminate": "停止进程",
        "privileged": "运行特权命令",
        "test_build": "运行项目检查",
        "file_modify": "修改项目文件",
        "github_pull_request": "创建GitHub拉取请求",
    },
}

_SECRET_ASSIGNMENT = re.compile(
    r"\b(?:api[_-]?key|token|secret|password|authorization)\s*[:=]\s*[^\s,;]+",
    re.IGNORECASE,
)
_BEARER_VALUE = re.compile(r"\bbearer\s+[^\s,;]+", re.IGNORECASE)
_URL = re.compile(r"(?:https?|ftp)://\S+", re.IGNORECASE)
_CODE_SPAN = re.compile(r"`[^`]*`")
_PATH = re.compile(r"(?<!\w)(?:~?/|[A-Za-z]:\\)\S+")


def _language(value: object) -> str:
    requested = str(value or "English").strip().casefold()
    for language in _ACTIONS:
        if language.casefold() == requested:
            return language
    return "English"


def _bounded_text(value: object, limit: int = MAX_FIELD_CHARS) -> str:
    if not isinstance(value, (str, int, float)):
        return ""
    text = str(value)
    text = "".join(" " if ord(char) < 32 or ord(char) == 127 else char for char in text)
    return " ".join(text.split())[:limit].strip()


def _tool_label(value: object) -> str:
    raw = _bounded_text(value, 128)
    safe = re.sub(r"[^A-Za-z0-9_.-]+", "_", raw).strip("_.-")
    if not safe:
        return "Tool"
    words = [part for part in re.split(r"[_.-]+", safe) if part]
    return " ".join(word.upper() if word.lower() in {"api", "mcp"} else word.capitalize() for word in words)[:80]


def _command_text(tool_input: object) -> str:
    if not isinstance(tool_input, Mapping):
        return ""
    command = tool_input.get("command", tool_input.get("cmd", ""))
    if isinstance(command, list):
        return " ".join(_bounded_text(part, 512) for part in command)[:MAX_ARGUMENT_CHARS]
    return _bounded_text(command, MAX_ARGUMENT_CHARS)


def _safe_hostname(tokens: list[str]) -> str:
    for token in tokens:
        if "://" not in token:
            continue
        try:
            hostname = (urlsplit(token).hostname or "").rstrip(".").lower()
        except ValueError:
            continue
        if len(hostname) <= 253 and re.fullmatch(r"[a-z0-9.-]+", hostname):
            return hostname
    return ""


def _classify_shell(tool_input: object) -> _PermissionIntent:
    command = _command_text(tool_input)
    if not command:
        return _PermissionIntent("shell")
    try:
        tokens = shlex.split(command, posix=True)
    except ValueError:
        return _PermissionIntent("shell")
    if not tokens:
        return _PermissionIntent("shell")

    executable = tokens[0].rsplit("/", 1)[-1].casefold()
    args = [token.casefold() for token in tokens[1:]]
    subcommand = args[0] if args else ""

    if executable in {"sudo", "doas"}:
        return _PermissionIntent("privileged")
    if executable in {"npm", "pnpm", "yarn", "pip", "pip3", "uv", "poetry", "bundle", "gem"} and subcommand in {
        "add",
        "install",
        "i",
        "sync",
    }:
        return _PermissionIntent("dependency_install")
    if executable == "git" and subcommand in {"push", "pull", "clone"}:
        return _PermissionIntent(f"git_{subcommand}")
    if executable in {"curl", "wget", "http", "https"}:
        hostname = _safe_hostname(tokens)
        if hostname:
            return _PermissionIntent("network", detail=hostname)
        if not args or all(argument.startswith("-") for argument in args):
            return _PermissionIntent("shell")
        return _PermissionIntent("network")
    if executable in {"rm", "rmdir", "unlink", "trash"}:
        return _PermissionIntent("file_delete")
    if executable in {"kill", "killall", "pkill", "taskkill"}:
        return _PermissionIntent("process_terminate")
    if executable in {"pytest", "tox", "nox", "make", "cmake", "gradle", "mvn", "swift", "cargo", "go"}:
        return _PermissionIntent("test_build")
    if executable in {"npm", "pnpm", "yarn"} and subcommand in {"test", "build", "check", "lint"}:
        return _PermissionIntent("test_build")
    return _PermissionIntent("shell")


def _classify_permission(tool_name: object, tool_input: object) -> _PermissionIntent:
    normalized = _bounded_text(tool_name, 128).casefold().replace("-", "_")
    if normalized in {"bash", "shell", "exec_command", "command"}:
        return _classify_shell(tool_input)
    if normalized in {"apply_patch", "edit", "write", "write_file", "replace"}:
        return _PermissionIntent("file_modify")
    if normalized in {
        "mcp__github__create_pull_request",
        "github__create_pull_request",
        "github_create_pull_request",
    }:
        return _PermissionIntent("github_pull_request")
    return _PermissionIntent("generic_tool", tool_label=_tool_label(tool_name))


def _permission_line(intent: _PermissionIntent, language: str) -> str:
    if language == "English":
        if intent.category == "network" and intent.detail:
            return f"Permission is needed to connect to {intent.detail}."
        if intent.category == "shell":
            return "Permission is required for a shell command."
        if intent.category == "generic_tool":
            return f"Permission is required for {intent.tool_label}."
        return f"Permission is needed to {_ACTIONS[language][intent.category]}."

    if language == "Turkish":
        if intent.category == "network" and intent.detail:
            return f"{intent.detail} adresine bağlanmak için izin gerekiyor."
        if intent.category == "shell":
            return "Bir shell komutu için izin gerekiyor."
        action = intent.tool_label if intent.category == "generic_tool" else _ACTIONS[language][intent.category]
        action = action[:1].upper() + action[1:]
        return f"{action} için izin gerekiyor."
    if language == "French":
        if intent.category == "network" and intent.detail:
            return f"Une autorisation est nécessaire pour se connecter à {intent.detail}."
        action = "une commande shell" if intent.category == "shell" else (
            intent.tool_label if intent.category == "generic_tool" else _ACTIONS[language][intent.category]
        )
        return f"Une autorisation est nécessaire pour {action}."
    if language == "Italian":
        if intent.category == "network" and intent.detail:
            return f"È necessaria l'autorizzazione per connettersi a {intent.detail}."
        action = "un comando shell" if intent.category == "shell" else (
            intent.tool_label if intent.category == "generic_tool" else _ACTIONS[language][intent.category]
        )
        return f"È necessaria l'autorizzazione per {action}."
    if intent.category == "generic_tool":
        action = intent.tool_label
    elif intent.category == "network" and intent.detail:
        action = intent.detail
    elif intent.category == "shell":
        action = "shell"
    else:
        action = _ACTIONS[language][intent.category]
    if language == "Japanese":
        return f"{action}には許可が必要です。"
    return f"{action}需要权限。"


def format_permission_request(
    tool_name: object,
    tool_input: object,
    language: object,
) -> AttentionMessage:
    intent = _classify_permission(tool_name, tool_input)
    selected_language = _language(language)
    return AttentionMessage(intent.category, _permission_line(intent, selected_language)[:MAX_SPOKEN_CHARS])


def _sanitize_question(header: object, question: object) -> str:
    parts = [_bounded_text(header), _bounded_text(question)]
    cleaned = []
    for part in parts:
        part = _CODE_SPAN.sub(" ", part)
        part = _URL.sub(" ", part)
        part = _SECRET_ASSIGNMENT.sub(" ", part)
        part = _BEARER_VALUE.sub(" ", part)
        part = _PATH.sub(" ", part)
        part = " ".join(part.split()).strip(" -:;,.")
        if part and part.casefold() not in {value.casefold() for value in cleaned}:
            cleaned.append(part)
    return ". ".join(cleaned)[:MAX_QUESTION_CHARS].rstrip()


def _input_line(safe_question: str, language: str) -> str:
    def punctuated(mark: str) -> str:
        if safe_question.endswith((".", "?", "!", "。", "？", "！")):
            return safe_question
        return safe_question + mark

    if language == "Turkish":
        generic = "Devam etmek için yanıtınız gerekiyor."
        return f"Yanıtınız gerekiyor: {punctuated('.')}" if safe_question else generic
    if language == "French":
        generic = "Votre réponse est nécessaire pour continuer."
        return f"Votre réponse est nécessaire: {punctuated('.')}" if safe_question else generic
    if language == "Italian":
        generic = "È necessaria una risposta per continuare."
        return f"È necessaria una risposta: {punctuated('.')}" if safe_question else generic
    if language == "Japanese":
        generic = "続行するには入力が必要です。"
        return f"入力が必要です: {punctuated('。')}" if safe_question else generic
    if language == "Chinese":
        generic = "需要您的输入才能继续。"
        return f"需要您的输入: {punctuated('。')}" if safe_question else generic
    generic = "Your input is needed to continue."
    return f"Your input is needed: {punctuated('.')}" if safe_question else generic


def format_input_required(
    header: object,
    question: object,
    language: object,
) -> AttentionMessage:
    selected_language = _language(language)
    safe_question = _sanitize_question(header, question)
    return AttentionMessage(
        "input_required",
        _input_line(safe_question, selected_language)[:MAX_SPOKEN_CHARS],
    )


def correlation_token(call_id: object) -> str | None:
    value = _bounded_text(call_id, 1_024)
    if not value:
        return None
    return hashlib.sha256(value.encode("utf-8")).hexdigest()[:20]


def parse_input_request_payload(payload: object) -> InputRequest | None:
    if not isinstance(payload, Mapping):
        return None
    if payload.get("type") != "function_call" or payload.get("name") != "request_user_input":
        return None
    arguments = payload.get("arguments")
    if not isinstance(arguments, str) or not arguments or len(arguments) > MAX_ARGUMENT_CHARS:
        return None
    try:
        parsed: Any = json.loads(arguments)
    except (TypeError, ValueError):
        return None
    if not isinstance(parsed, Mapping):
        return None
    auto_resolution_ms = parsed.get("autoResolutionMs")
    if (
        isinstance(auto_resolution_ms, (int, float))
        and not isinstance(auto_resolution_ms, bool)
        and auto_resolution_ms > 0
    ):
        return None
    questions = parsed.get("questions")
    if not isinstance(questions, list) or not questions or not isinstance(questions[0], Mapping):
        return None
    first = questions[0]
    header = _bounded_text(first.get("header"))
    question = _bounded_text(first.get("question"))
    if not header and not question:
        return None
    return InputRequest(
        header=header,
        question=question,
        correlation_token=correlation_token(payload.get("call_id")),
    )
