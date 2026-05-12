# Agent Instructions

Jarvis Line only speaks lines that the agent explicitly emits. For it to work, the Jarvis Line instruction block must be present in the Markdown instruction file your agent actually reads.

Jarvis Line does not edit your Markdown instruction files by default. This is intentional: different users keep instructions in different places, and the right scope may be project-level or global/user-level.

## Choose Scope

| Scope | Use When | Example Location |
|---|---|---|
| Project | You want Jarvis Line only for one repository or workspace | `./AGENTS.md`, `./CLAUDE.md`, `./GEMINI.md` |
| Global/user | You want the same Jarvis Line instruction across many projects | Your agent's global instruction file |

Then print the instruction, review it, and paste it into the file you chose:

```bash
jarvis-line instructions print agents --language "English"
```

If the block is not pasted into the instruction file your agent uses, Jarvis Line may be installed but the agent will not know to emit `Jarvis line: ...` messages.

## Integration Support

| Agent | Instruction file | Hook/runtime install |
|---|---:|---:|
| Codex | `AGENTS.md` | Yes, via `jarvis-line install codex` |
| Claude | `CLAUDE.md` | Not yet |
| Gemini | `GEMINI.md` | Not yet |

Codex is the only full hook integration today. Claude and Gemini support currently means Jarvis Line can generate the instruction block that tells the agent to emit `Jarvis line: ...`; native Claude/Gemini session watching or hook installation is planned as a separate integration.

Codex:

```bash
jarvis-line instructions print agents --language "English"
```

Claude:

```bash
jarvis-line instructions print claude --language "English"
```

Gemini:

```bash
jarvis-line instructions print gemini --language "English"
```

Minimal output:

```bash
jarvis-line instructions print agents --language "English"
jarvis-line instructions print agents --language "English" --style minimal
```

## Default Instruction

The installed instruction tells the agent to include exactly one line like:

```text
Jarvis line: The requested change is implemented and verified.
```

The default instruction is strict on purpose:

- every final response must include exactly one `Jarvis line: ...`
- progress/commentary messages may include one, but do not have to
- normal user-facing text stays in the user's language
- the spoken Jarvis line follows the selected instruction language
- secrets, raw logs, code, and long file contents are forbidden in spoken lines

The same instruction template can be generated for any spoken language by changing `--language`.

```bash
jarvis-line instructions print agents --language "German"
jarvis-line instructions print agents --language "Japanese"
jarvis-line instructions print agents --language "Brazilian Portuguese"
```

Default English instruction:

```markdown
## Jarvis Line

Jarvis Line is enabled for this agent.

Every final assistant response must include exactly one spoken status line using this format:

`Jarvis line: <one short spoken summary>`

Rules:
- Any `Jarvis line` must be written in English.
- Include exactly one `Jarvis line: ...` line in every final response.
- You may include an optional `Jarvis line: ...` line in commentary/progress messages.
- Keep each Jarvis line to one short natural sentence.
- Use Jarvis lines only for status, completion, or the next action.
- Do not include secrets, private data, raw logs, code, or long file contents in the Jarvis line.
- Do not start normal messages with phrases like "Jarvis here" or similar persona announcements.
- Keep normal user-facing text in the user's language unless there is a separate reason to switch.
- If the response language differs from the Jarvis line language rule, only the Jarvis line is governed by this section.
- Before sending any final response, verify that it includes exactly one `Jarvis line: ...` line.
```

## Language Choice

The instruction language and TTS language must match.

Recommended default:

```bash
jarvis-line instructions print agents --language "English"
```

Turkish instructions:

```bash
jarvis-line instructions print agents --language "Turkish"
```

Then manually paste the printed `## Jarvis Line` section into the correct instruction file.

After editing the file, check the result:

```bash
jarvis-line instructions doctor agents
```

`instructions install` still exists for disposable files or advanced users who explicitly want Jarvis Line to edit an instruction file:

```bash
jarvis-line instructions install agents --language "English" --replace
```

Notes:

- `--language "English"` keeps the spoken line English and works well with Kokoro English voices.
- `--language "Turkish"` makes the agent write Turkish Jarvis lines; your selected TTS voice must also be Turkish.
- There is no automatic language matching mode. Pick the exact spoken language you want Jarvis Line to use.
