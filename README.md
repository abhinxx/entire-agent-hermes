# entire-agent-hermes

Entire CLI integration for [Hermes Agent](https://hermes-agent.nousresearch.com/) (Nous Research).

Every Hermes session gets Entire checkpoints: prompts, transcripts, and modified files
attached to your commits as inspectable, searchable git checkpoints.

Two pieces:

| Piece | Role |
|---|---|
| `bin/entire-agent-hermes` | The Entire [external agent integration](https://docs.entire.io/agents/agent-integration-protocol/overview) (protocol v1). A single Python 3 stdlib script, discovered by the Entire CLI from `$PATH`. |
| `plugin/hermes-entire-bridge/` | A Hermes plugin that maintains a Claude-style JSONL transcript per session/repo and forwards lifecycle events to `entire hooks hermes <hook>`. |

## How it works

```
Hermes session                        Entire CLI                     git repo
─────────────                         ──────────                     ────────
plugin hooks fire  ──►  transcript    parse-hook → Event        ──►  checkpoint ref
on_session_start        ~/.entire-     (SessionStart/TurnStart/       (refs/entire/…)
post_llm_call           hermes/…        TurnEnd/SessionEnd)           Entire-Checkpoint:
post_tool_call          <session>.jsonl read-transcript /              trailer on commit
on_session_end          + forward to    extract-modified-files
                        entire hooks …
```

- Turn mapping: `on_session_start` → SessionStart, first `post_llm_call` of a turn → TurnStart,
  every `post_llm_call` → TurnEnd (checkpoint save), `on_session_end`/`on_session_reset` → SessionEnd.
- `post_tool_call` records `write_file` / `patch` / `skill_manage` paths into the transcript so
  `extract-modified-files` reports real changed files.
- All forwarding runs in daemon threads with a 25 s timeout; the agent loop never waits on Entire.
- Zero-effect default: no `entire` binary on `PATH`, or no enabled `.entire/settings.json` above
  the cwd → every hook no-ops. Kill switch: `ENTIRE_HERMES_BRIDGE=0`.

## Requirements

- Entire CLI ≥ 0.11 (external agent protocol v1) — `brew install --cask entire` or https://entire.io/install.sh
- Hermes Agent (any surface: CLI, desktop, TUI, dashboard chat)
- Python 3.8+ (stdlib only)

## Install

```bash
./install.sh            # copies binary to ~/.local/bin, plugin to ~/.hermes/plugins/
```

Or manually:

```bash
chmod +x bin/entire-agent-hermes && cp bin/entire-agent-hermes ~/.local/bin/   # must be on $PATH
cp -r plugin/hermes-entire-bridge ~/.hermes/plugins/
hermes plugins enable hermes-entire-bridge
```

## Enable per repository

```bash
cd /path/to/repo
entire enable --agent hermes --telemetry=false
```

Then work through Hermes as usual. Commit; the commit gets an `Entire-Checkpoint:` trailer:

```bash
entire status
entire checkpoint list
entire checkpoint explain <CHECKPOINT_ID>
```

## Verify

```bash
python3 tests/test_smoke.py           # protocol unit tests, no network
```

## Scope of capture (read before using on a public repo)

This bridge forwards the user prompt and final assistant response of each turn to the Entire
CLI, which stores them (redacted per Entire's settings) in your repo's checkpoint refs.
Pushing the repo publishes the transcripts to everyone with repo access. Entire's redaction
covers transcripts, not committed source. If that is not what you want, keep checkpoints local:
`entire configure --skip-push-sessions` or use a private repo.

## Relationship to upstream

[`entireio/external-agents`](https://github.com/entireio/external-agents) already ships an
`agents/entire-agent-hermes` preview integration (Go binary + a stricter "observer" plugin with
aggressive sanitization and an explicit `HERMES_HOME` requirement). This project is a separate,
simpler, dependency-free implementation that captures richer transcript data (full prompt +
final response + file paths) via the standard Hermes plugin system. If you want it upstream,
their CONTRIBUTING process requires opening an issue and getting maintainer approval first.

## Layout

```
bin/entire-agent-hermes          protocol binary (Python 3, stdlib only)
plugin/hermes-entire-bridge/     Hermes plugin (plugin.yaml + __init__.py)
tests/test_smoke.py              protocol smoke tests
install.sh                       one-shot installer
mise.toml                        build/test tasks (external-agents CI contract)
AGENT.md                         protocol/design doc (research, hook mapping, gaps)
docs/                            research notes (upstream conventions, Hermes hook kwargs)
```

## License

MIT
