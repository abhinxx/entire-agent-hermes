# Hermes Agent — External Agent Research (entire-agent-hermes, bridge variant)

Research + design doc following the
[external-agents](https://github.com/entireio/external-agents) AGENT.md conventions.
Companion to `README.md`. This variant is a standalone Python implementation; the
upstream `agents/entire-agent-hermes` (Go, observer plugin, strict sanitization) is a
different design against the same protocol.

## Verdict: COMPATIBLE (live-verified)

Hermes Agent exposes a public Python plugin system with lifecycle hooks that fire in
CLI, gateway, desktop, and TUI sessions. A user plugin can maintain a repository-keyed
JSONL transcript and forward lifecycle events to `entire hooks hermes <hook>` without
reading Hermes' private SQLite state. Unlike the upstream preview ("STATIC VERIFIED /
LIVE UNVERIFIED"), this variant was verified end-to-end against a real Hermes install
and the Entire CLI 0.11.4: a forwarded session appeared in `entire session list` and a
commit received an `Entire-Checkpoint:` trailer with prompt + modified files.

## Static checks (verified live, macOS arm64)

| Check | Result | Notes |
|-------|--------|-------|
| Entire CLI | PASS | v0.11.4, external protocol v1 discovered via `$PATH` + `external_agents: true` |
| External discovery | PASS | `entire enable --agent hermes` installs hooks, calls `info` at every CLI start |
| `entire hooks hermes <hook>` | PASS | accepted for external agents once enabled |
| Hermes plugin API | PASS | `register(ctx)` + `ctx.register_hook()`; `hermes plugins validate` clean |
| Hook kwargs source-verified | PASS | see `docs/hermes-plugin-api.md` (file:line citations) |
| TurnEnd checkpoint flow | PASS | parse-hook → TurnEnd → transcript read → modified-file extraction → checkpoint ref + commit trailer |

## Hook mechanism

- Plugin: `hermes-entire-bridge` (install to `$HERMES_HOME/plugins/`, `hermes plugins enable`).
- Hooks registered: `on_session_start`, `post_llm_call`, `post_tool_call`,
  `on_session_end`, `on_session_reset`. All forwarding is daemon-thread fire-and-forget,
  25 s timeout, fail-open; no-ops entirely when `entire` is absent or the repo has no
  enabled `.entire/settings.json` (60 s cached upward-walk probe).

### Hook mapping

| Hermes hook | Fires | Protocol Event |
|-------------|-------|----------------|
| `on_session_start` | new session begins | 1 = SessionStart |
| `post_llm_call` (first per turn) | turn's final response ready | 2 = TurnStart (prompt + transcript user line) |
| `post_llm_call` (every) | turn's final response ready | 3 = TurnEnd (checkpoint save) |
| `post_tool_call` | after tool returns | transcript-only line for `write_file`/`patch`/`skill_manage` paths |
| `on_session_end` / `on_session_reset` | session end or `/new` reset | 5 = SessionEnd |

Note: this differs from the upstream preview's mapping (`on_session_end` = TurnEnd,
`on_session_finalize` = SessionEnd for v0.20.0). Verified against current Hermes
source, `post_llm_call` is the reliable per-turn boundary on every surface, so this
variant uses TurnStart/TurnEnd from it and needs no `pre_tool_call`/buffering logic.

## Sessions & transcript

- Session ID: public `session_id` hook kwarg.
- Directory: `~/.entire-hermes/sessions/<repo-slug>/` where repo-slug =
  abspath with separator→`-` + `sha256(abspath)[:8]` (path logic identical in plugin
  and protocol binary).
- File: `<session_id>.jsonl`, Claude-style lines: `{"type":"user"|"assistant","message":...}`,
  `{"type":"tool","tool_name":...,"tool_input":{"path":...}}`.
- Resume: `hermes --resume <session_id>`.
- Hermes `state.db`, memory, credentials, and native sessions are never read.

## Protocol mapping

| Subcommand | Implementation | Status |
|-----------|----------------|--------|
| `info` | static metadata, capabilities below | required, live-verified |
| `detect` | `hermes` on PATH or `$HERMES_HOME`/`~/.hermes` exists | required |
| `get-session-id` | echo HookInput `session_id` | required |
| `get-session-dir` | session base + repo slug | required |
| `resolve-session-file` | `<dir>/<id>.jsonl` | required |
| `read-session` / `write-session` | `.session.json` sidecar next to transcript | required |
| `read-transcript` / `chunk-transcript` / `reassemble-transcript` | raw bytes; line-aware chunks | required |
| `format-resume-command` | `hermes --resume <id>` | required |
| `parse-hook` | map forwarded payload → Event 1/2/3/5; unknown → `null` | hooks |
| `install-hooks` / `uninstall-hooks` / `are-hooks-installed` | marker files in `<repo>/.entire-hermes/hooks/` + `.git/info/exclude` entry (capture itself is driven by the Hermes plugin, markers record the wiring) | hooks |
| `get-transcript-position` / `extract-modified-files` / `extract-prompts` / `extract-summary` | JSONL line parse after byte offset | transcript_analyzer |

## Capabilities

| Capability | Declared | Justification |
|-----------|----------|---------------|
| hooks | true | public plugin lifecycle hooks on all surfaces |
| transcript_analyzer | true | stable user/assistant/tool JSONL entries |
| transcript_preparer | false | transcript is already Entire-compatible |
| token_calculator | false | token fields not in hook payloads |
| text_generator | false | no model calls inside the adapter |
| hook_response_writer | false | non-intervening, fail-open |
| subagent_aware_extractor | false | subagent transcripts not captured (yet) |

## Safety invariants

- Never read `state.db`, memory, credentials, or request dumps.
- Forwarded payloads exclude `conversation_history` (bounded to prompt + final response).
- No effect when Entire is not enabled for the repo; `ENTIRE_HERMES_BRIDGE=0` kills all hooks.
- Daemon threads only; plugin callbacks never block the agent loop.
- Checkpoint privacy is Entire's own model: pushing the repo publishes transcripts.
  README warns; `--skip-push-sessions` documented.

## Gaps & limitations

- TurnStart fires after the model's first response (Hermes has no
  `user_prompt_submit`-equivalent that is both reliable and pre-mutation). Upstream's
  `pre_tool_call` synchronous-activation trick fixes this at the cost of a blocking
  hook; documented trade-off, upgrade path is one hook.
- `terminal` git commands are not parsed for modified files; only path-bearing file
  tools are recorded. Entire's checkpoint baseline remains authoritative for content.
- No `compact_transcript` capability yet; long sessions store full transcripts.
- Hard-killed Hermes may skip `on_session_end`; TurnEnd checkpoints still exist.

## E2E prerequisites (for a PR to external-agents)

- Python shape (like crewai/langgraph): `mise.toml` `[tasks.build]` emits
  `entire-agent-hermes` launcher inside the agent dir, `[tasks.test]` runs unittest +
  protocol smoke; shared compliance suite from `external-agents-tests`.
- `testdata/compliance.json` + transcript fixtures; `e2e/agents/hermes.go` Register/GATE.
- Isolated `HERMES_HOME` via `mktemp -d`; test credentials supplied out of band.
