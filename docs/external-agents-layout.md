# entireio/external-agents — Repo Conventions for New Integrations

Researched 2026-10-11 from a fresh clone at
`~/.hermes/cache/scratch/external-agents` (HEAD `4acd239`, main).

## TL;DR — A Hermes integration ALREADY EXISTS

`agents/entire-agent-hermes/` is fully implemented and merged ("Implemented
(preview) — sanitized observer hooks + transcript analysis + compact
transcripts" in the root README). History:

- `db13657 feat: add Hermes external agent integration` (from PR/issue #54, closed)
- `d8ee157 fix: harden Hermes observer redaction`
- `c17ea2e fix: require explicit Hermes repository evidence`
- `f67d0b6 hermes: prepare transcripts for Entire`
- #88 (closed) `fix(hermes): prevent cross-repository observer attribution`
- Open issue #98: "Point external_agents setup at settings.local.json" (relates to docs, mentions hermes usage)

So "adding Hermes" is **done**; future work is fixes/extensions, which per
CONTRIBUTING.md still requires an approved issue first.

## 1. Repo layout

```
AGENTS.md            # agent-builder skill entry point (Codex/Cursor/OpenCode)
CONTRIBUTING.md
README.md            # agent table + per-agent enable instructions
.github/workflows/   # ci.yml, lint.yml, license-check.yml, protocol-compliance.yml
.claude/skills/entire-external-agent/  # SKILL.md + research.md + write-tests.md + implement.md
agents/entire-agent-<name>/            # one standalone integration per dir
e2e/                 # shared lifecycle harness (Go, build tag e2e)
mise-tasks/          # build / test / lint runner scripts (bash)
mise.toml            # root: Go 1.26.0, golangci-lint 2.11.3, license_finder, tmux, external-agents-tests
tests/  doc/         # doc/first-time-contributors.md, dependency_decisions.yml
```

Registered agents (10): amp, crewai, goose, grok, **hermes**, kilo, kiro,
langgraph, omp, qwen. CI auto-discovers any dir matching
`agents/entire-agent-*` — no workflow edit needed to add one.

### Two integration shapes

**Go shape** (kiro, amp, goose, grok, hermes, kilo, omp, qwen):

```
agents/entire-agent-<name>/
  .gitignore
  AGENT.md        # research doc: verdict, static checks, hook mapping,
                  # session mgmt, transcript format, protocol-subcommand
                  # mapping table, capabilities table, gaps, e2e prerequisites
  README.md       # user-facing: build, enable, safety model, verification
  go.mod (+go.sum)
  mise.toml       # [tasks.build] go build -o entire-agent-<name> ./cmd/...
                  # [tasks.test]  go test ./...
  cmd/entire-agent-<name>/main.go
  internal/<name>/   # agent.go, agent_test.go, transcript.go, compact.go,
                     # hooks.go, config.go, paths.go, types.go + tests
  internal/protocol/ # protocol.go, types.go (JSON-over-stdin/stdout subcommand dispatcher)
  scripts/           # optional verify-*.sh, verify-compliance.sh
  testdata/          # optional fixtures (hermes has compliance.json, transcript.jsonl)
```

**Python shape** (crewai, langgraph — NON-GO integrations are explicitly allowed):

```
agents/entire-agent-<name>/
  AGENT.md, README.md
  mise.toml               # [tasks.build] creates .venv, pip installs
                          # `entire-adapter==0.2.2`, runs build_launcher.py
                          # [tasks.test] unittest + protocol smoke (info/detect/parse-hook)
  build_launcher.py       # emits the entire-agent-<name> executable wrapper
  protocol_wrapper.py     # implements the protocol surface in Python
  test_*.py               # unittest files
  e2e_<name>_fixture.py   # optional fixture for lifecycle tests
```

Both shapes produce a binary named exactly `entire-agent-<name>` inside the
agent dir; mise-tasks/build copies it to repo-root `bin/` on full builds.

## 2. CI workflows (all auto-discover `agents/entire-agent-*`)

- **ci.yml** — `discover-agents` job builds a matrix; per agent: `mise run test <dir>`
  then `mise run build <dir>` via mise-action. Plus a Windows job
  (`test-windows-paths`) only for the manually-listed Go agents
  `[amp, kiro, kilo, grok, qwen]` (session-path portability tests).
- **protocol-compliance.yml** — builds each agent, then runs the shared suite
  `entireio/external-agents-tests@main` against `agents/<dir>/<binary>`.
  Hermes has special-casing: installs Entire CLI v0.9.0 (pinned sha256) for
  hook registration, sets `HERMES_HOME` to a runner-temp profile, and passes
  `testdata/compliance.json` as fixtures-path.
- **lint.yml** — repo-wide `gofmt -l .` check + per-agent golangci-lint.
- **license-check.yml** — reusable workflow from `entireio/shared`, uses
  license_finder + `.allowed-licenses`.

The generic runner scripts (`mise-tasks/build`, `mise-tasks/test`) prefer
`[tasks.build]` / `[tasks.test]` from the agent's `mise.toml`; they fall back
to Go defaults (`go build -o <name> ./cmd/<name>`, `go test ./...`) only if
`go.mod` exists. **CONTRIBUTING.md: "make sure your `agents/entire-agent-<name>/mise.toml`
defines `build` and `test` tasks … the mise tasks are the contract for anything
non-standard."** A non-Go agent without mise tasks fails discovery.

## 3. CONTRIBUTING.md — adding a new integration

Process (new agents are "not a first-PR shape"):
1. **Open an issue first** and wait for maintainer approval (brand-new agent =
   long-running commitment, expect multiple PRs).
2. Use the shipped skill `.claude/skills/entire-external-agent/`
   (SKILL.md full pipeline; research.md → write-tests.md → implement.md),
   auto-discovered by Claude Code (`/entire-external-agent`), Codex/Cursor/OpenCode
   via AGENTS.md / .cursor/rules / .opencode plugins.
3. Three test layers: protocol compliance (external repo
   `entireio/external-agents-tests`, run in CI), lifecycle e2e (`e2e/`,
   `E2E_AGENT=<name> mise run test:e2e`), unit tests (`mise run test`).
4. PR checklist: approved issue referenced, `mise run fmt` clean,
   golangci-lint clean, tests pass, tests included, commit subject prefixed
   `<agent>:` for single-agent changes, Entire checkpoint trailers on commits,
   respond to **every** Copilot review comment (unaddressed = no maintainer review).
5. Protocol surface: JSON output of subcommands must stay compatible with
   `entireio/cli/docs/architecture/external-agent-protocol.md`; compliance
   coverage updated in the same PR cycle.

e2e registration: add `e2e/agents/<name>.go` implementing the `Agent`
interface (Name/Binary/EntireAgent/PromptPattern/TimeoutMultiplier/RunPrompt/
StartSession/Bootstrap/IsTransientError), `ExternalAgent` (`IsExternalAgent()
true`), and `func init() { Register(&X{}); RegisterGate("<name>", N) }`.
Optional dedicated e2e test file (e.g. `e2e/hermes_protocol_test.go`).

## 4. AGENT.md template (structure, from kiro + hermes examples)

`AGENT.md` is the research output of phase 1 (research.md skill), sections:

1. Title: `# <Agent> - External Agent Research`
2. `## Verdict: COMPATIBLE` + paragraph justification
3. `## Static Checks` table: Binary present / Help available / Version info /
   Hook keywords / Session keywords / Config directory / Documentation (PASS|DOCS/CODE + notes)
4. `## Binary` — name, version, install, non-interactive + resume commands
5. `## Hook Mechanism` — config file path/format, native-hook → protocol-event
   mapping table (SessionStart / TurnStart / TurnEnd), payload shape, failure behavior
6. `## Session Management` — session-ID resolution order, caches, session dir
   (`.entire/tmp/...`), file format (JSONL required — Entire slices by LINE offset)
7. `## Transcript` — stored format, per-record schema Entire's compactor needs
   (top-level `type`/`role` + `message` wrapper), back-compat notes
8. `## Protocol Mapping` table — every subcommand: `info`, `detect`,
   `get-session-id`, `get-session-dir`, `resolve-session-file`, `read-session`,
   `write-session`, `read-transcript`, `chunk-transcript`,
   `reassemble-transcript`, `format-resume-command` (all Required);
   `parse-hook`, `install-hooks`, `uninstall-hooks`, `are-hooks-installed`
   (if hooks); `get-transcript-position`, `extract-modified-files`,
   `extract-prompts`, `extract-summary` (if transcript analyzer)
9. `## Selected Capabilities` table: hooks / transcript_analyzer /
   transcript_preparer / token_calculator / compact_transcript / text_generator /
   hook_response_writer / subagent_aware_extractor — declared true/false + justification
10. `## Gaps & Limitations` (hermes adds `## Safety Invariants`, `## Captured Payloads`)
11. `## E2E Test Prerequisites` — binaries+versions, env overrides, prompt
    pattern, timeout multiplier, bootstrap, transient-error strings

## 5. Hermes integration specifics (already merged)

- Go module; embedded **Python observer plugin** (`internal/hermes/plugin/
  __init__.py` + `plugin.yaml`) installed into `$HERMES_HOME/plugins/entire-observer/`.
- Mandatory explicit `HERMES_HOME`; never touches default `~/.hermes` profile or `state.db`.
- Hook mapping: `on_session_start`→SessionStart, `pre_llm_call`→TurnStart,
  `on_session_end`→TurnEnd; `pre_tool_call`/`post_tool_call`/`post_llm_call`
  observer-only (repo attribution + sanitized transcript).
- Sanitized repo-keyed JSONL under `$HERMES_HOME/entire/transcripts`; allowlist
  + Hermes `redact_sensitive_text` + fallback redaction; no secrets/tool args.
- Capabilities: hooks=T, transcript_analyzer=T, transcript_preparer=T,
  compact_transcript=T; token_calculator/text_generator/hook_response_writer/
  subagent_aware_extractor=F.
- CI: protocol-compliance.yml special-cases it (Entire v0.9.0 install, temp
  HERMES_HOME, `testdata/compliance.json` fixtures). e2e gate:
  `RegisterGate("hermes", 1)`, requires disposable `HERMES_HOME=$(mktemp -d)`.
- Verification scripts: `scripts/verify-hermes.sh` (refuses paths under real
  ~/.hermes), `scripts/verify-compliance.sh` (`mise run verify`).

## 6. Required files for a NEW integration PR (any language)

Minimum per-dir set (Go example):
- `agents/entire-agent-<name>/mise.toml` with `[tasks.build]` and `[tasks.test]`
  (mandatory; only Go dirs may omit them via go.mod fallback)
- Binary produced named `entire-agent-<name>` from within the dir (CI matrix uses
  `agents/<dir>/entire-agent-<name>` as binary path)
- `AGENT.md` (research doc, structure above) + `README.md` (build/enable/usage)
- Code implementing the external-agent-protocol subcommands (Go: `cmd/…/main.go`
  + `internal/protocol` + `internal/<name>`; Python: build_launcher.py +
  protocol_wrapper.py à la crewai) + unit tests at the same layer
- `.gitignore` (Go: built binary)
- e2e registration in `e2e/agents/<name>.go` (Register + optional
  RegisterGate/ExternalAgent) + optional `e2e/<name>_protocol_test.go`
- Root README table row + enable snippet; protocol-compliance.yml special
  casing only if the agent needs env/setup to pass the shared suite (like hermes)
- Non-Go allowed: **yes** — crewai and langgraph are pure-Python mise-task
  integrations (bridge to the PyPI `entire-adapter` package), fully in CI.
- License check applies to deps (`.allowed-licenses` via license_finder).
- Go agents must be gofmt + golangci-lint clean; Windows path portability is
  expected for session-path code (see `fix: contain session paths across
  external agents`, PR #91) though only some agents are in the Windows matrix.
