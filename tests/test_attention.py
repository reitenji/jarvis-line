import json

import pytest

from jarvis_line.attention import (
    correlation_token,
    format_input_required,
    format_permission_request,
    parse_input_request_payload,
)


@pytest.mark.parametrize(
    ("command", "category", "expected"),
    [
        ("npm install", "dependency_install", "install project dependencies"),
        ("git push origin develop", "git_push", "push changes to the remote repository"),
        ("rm -rf build", "file_delete", "delete files"),
        ("kill 123", "process_terminate", "stop a process"),
        ("sudo make install", "privileged", "run a privileged command"),
        ("pytest -q", "test_build", "run project checks"),
    ],
)
def test_permission_formatter_classifies_common_shell_intents(command, category, expected):
    result = format_permission_request("Bash", {"command": command}, "English")

    assert result.category == category
    assert expected in result.line


def test_permission_formatter_keeps_only_safe_url_hostname():
    result = format_permission_request(
        "Bash",
        {"command": "curl https://user:password@api.example.com:8443/items?token=secret#private"},
        "English",
    )

    assert result.category == "network"
    assert result.line == "Permission is needed to connect to api.example.com."
    assert "password" not in result.line
    assert "secret" not in result.line
    assert "8443" not in result.line


@pytest.mark.parametrize(
    ("tool_name", "expected_category", "expected_text"),
    [
        ("apply_patch", "file_modify", "modify project files"),
        ("Write", "file_modify", "modify project files"),
        ("mcp__github__create_pull_request", "github_pull_request", "create a GitHub pull request"),
        ("custom_tool", "generic_tool", "Custom Tool"),
    ],
)
def test_permission_formatter_classifies_tools_without_arguments(
    tool_name, expected_category, expected_text
):
    result = format_permission_request(tool_name, {"secret": "do-not-speak"}, "English")

    assert result.category == expected_category
    assert expected_text in result.line
    assert "do-not-speak" not in result.line


def test_malformed_shell_request_uses_safe_fallback():
    result = format_permission_request("Bash", {"command": "'unterminated secret"}, "English")

    assert result.category == "shell"
    assert result.line == "Permission is required for a shell command."
    assert "secret" not in result.line


@pytest.mark.parametrize(
    ("language", "expected"),
    [
        ("English", "Permission is needed"),
        ("Turkish", "izin gerekiyor"),
        ("French", "Une autorisation est nécessaire"),
        ("Italian", "È necessaria l'autorizzazione"),
        ("Japanese", "許可が必要です"),
        ("Chinese", "需要权限"),
        ("German", "Permission is needed"),
    ],
)
def test_permission_templates_cover_supported_languages_and_fallback(language, expected):
    result = format_permission_request("apply_patch", {}, language)

    assert expected in result.line


def test_input_formatter_redacts_secret_assignments_urls_and_code():
    result = format_input_required(
        "Deploy",
        "Choose `production` for TOKEN=secret at https://private.example/path?key=value?",
        "English",
    )

    assert result.category == "input_required"
    assert result.line.startswith("Your input is needed:")
    assert "Deploy" in result.line
    assert "secret" not in result.line
    assert "private.example" not in result.line
    assert "production" not in result.line
    assert len(result.line) <= 240


def test_input_formatter_uses_generic_line_when_question_is_unsafe():
    result = format_input_required("", "TOKEN=secret https://example.test/private", "English")

    assert result.line == "Your input is needed to continue."


@pytest.mark.parametrize(
    ("language", "expected"),
    [
        ("English", "Your input is needed"),
        ("Turkish", "Yanıtınız gerekiyor"),
        ("French", "Votre réponse est nécessaire"),
        ("Italian", "È necessaria una risposta"),
        ("Japanese", "入力が必要です"),
        ("Chinese", "需要您的输入"),
    ],
)
def test_input_templates_cover_supported_languages(language, expected):
    result = format_input_required("Release", "Which channel should be used?", language)

    assert expected in result.line
    assert not result.line.endswith("?.")


def test_parse_input_request_accepts_only_observed_structured_shape():
    payload = {
        "type": "function_call",
        "name": "request_user_input",
        "call_id": "call-secret-value",
        "arguments": json.dumps(
            {
                "questions": [
                    {
                        "header": "Release",
                        "id": "release_channel",
                        "question": "Which release channel should be used?",
                        "options": [
                            {"label": "Beta", "description": "Publish a beta release."}
                        ],
                    }
                ]
            }
        ),
    }

    request = parse_input_request_payload(payload)

    assert request is not None
    assert request.header == "Release"
    assert request.question == "Which release channel should be used?"
    assert request.correlation_token == correlation_token("call-secret-value")
    assert "call-secret-value" not in request.correlation_token
    assert not hasattr(request, "options")


@pytest.mark.parametrize(
    "payload",
    [
        None,
        {},
        {"type": "function_call", "name": "another_tool", "arguments": "{}"},
        {"type": "function_call", "name": "request_user_input", "arguments": "not-json"},
        {
            "type": "function_call",
            "name": "request_user_input",
            "call_id": "call-1",
            "arguments": json.dumps({"questions": []}),
        },
    ],
)
def test_parse_input_request_rejects_incompatible_payloads(payload):
    assert parse_input_request_payload(payload) is None


def test_correlation_token_is_bounded_deterministic_and_content_free():
    first = correlation_token("private-call-id")

    assert first == correlation_token("private-call-id")
    assert first != correlation_token("another-call-id")
    assert len(first) == 20
    assert "private" not in first
    assert correlation_token("") is None
