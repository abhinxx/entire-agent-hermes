# Hermes Plugin API — source-verified reference

Extracted 2026-10-11 from local source at `~/.hermes/hermes-agent`
(source treated as ground truth over docs; doc quotes only where they agree with code).
All file:line citations are from that checkout.

---

## 1. Plugin package layout & `plugin.yaml` manifest contract

### Layout (directory plugin)

```
~/.hermes/plugins/<name>/
├── plugin.yaml      # manifest (required; plugin.yml also accepted — plugin_validate.py:496-500)
├── __init__.py      # must expose register(ctx)  (plugins_loader.py:510-517)
└── ...              # any supporting modules
```

- `hermes_cli/plugins.py:1-8` (module docstring): "A directory plugin needs a
  `plugin.yaml` manifest and an `__init__.py` exposing `register(ctx)`."
- Load path: `plugins_loader.py:510` `register_fn = getattr(module, "register", None)`;
  missing → `loaded.error = "no register() function"` and load fails (`:513-516`).
  Entry-point plugins declared as `module:function` resolve to the function itself
  and are used directly as `register_fn` (`plugins_loader.py:502-506`).
- Load deadline: import + `register()` must finish within `plugins.load_timeout_seconds`
  (default 10 s, 0 disables, max 600) — `plugins_loader.py:40,105-148`.
- A `plugin.yaml` with nothing loadable beside it (no `__init__.py`, no
  `desktop/plugin.js`, no `plugin.json`, no `provides_locales` + `locales/`) fails
  `hermes plugins validate` ("loadable" check — `plugin_validate.py:549-562`,
  `_LOADABLE_ENTRYPOINTS = ("__init__.py", "desktop/plugin.js", "plugin.json")`).
- There is **no `entry` manifest field**. The full known-field set is
  `plugins_manifest.py:32-39`.

### Discovery sources & precedence

`plugins_discovery.py:189-218` (`collect_directory_manifests`), later wins on key
collision (project > user > bundled, `resolve_manifest_winners` `:221-244`):

| Source | Path | Notes |
|---|---|---|
| Bundled | `<repo>/plugins/` (or `$HERMES_BUNDLED_PLUGINS`) | `plugins.py:69-75`; `memory/`, `context_engine/`, `model-providers/`, `cron_providers/`, `computer_use/` have their own discovery and are skipped by the general scanner (`plugins_discovery.py:207-208`) |
| **User** | `~/.hermes/plugins/<name>/` (`get_hermes_home()/plugins`) | `plugins_discovery.py:209-211` |
| Project | `./.hermes/plugins/` | opt-in via `HERMES_ENABLE_PROJECT_PLUGINS=true` (`plugins_discovery.py:212-217`) |
| pip | `hermes_agent.plugins` entry-point group | `plugins.py:4-6` |

Registry key: flat dir → `name`; category dir `plugins/<cat>/<name>/` → `cat/name`
(`plugins_manifest.py:359-361`; scan_directory docstring `plugins_discovery.py:137-140`).
A user dir overriding a bundled plugin must use the **same directory name** as the
bundled one or it's refused as an impostor (`plugins_discovery.py:231-240`).

### Manifest fields

`PluginManifest` dataclass: `plugins_manifest.py:342-395`. Known fields
(`_KNOWN_MANIFEST_FIELDS`, `plugins_manifest.py:32-39`):

```
name, version, description, author, requires_env, provides_tools, provides_hooks,
kind, hooks, label, optional_env, platforms, external_dependencies,
pip_dependencies, provides_browser_providers, provides_web_providers,
manifest_version, api_version, requires_plugins, python_dependencies, config_schema,
license, homepage, tags, capabilities, emits, listens, hermes, depends,
requires_hermes, python_runtime, provides_locales
```

- **Required by `hermes plugins validate`: `name`, `version`, `description`** —
  `_check_manifest_fields` (`plugin_validate.py:100-111`): missing any of the three
  fails the "manifest fields" check. Everything else optional.
- `kind` (default `standalone`): one of `standalone | backend | exclusive | platform |
  model-provider` (`plugins_manifest.py:27, 354-358`). `standalone` is gated by
  `plugins.enabled`; `backend`/`platform` bundled auto-load, user-installed gated.
- `manifest_version` (v1 default, supported forever; current max = 2,
  `SUPPORTED_MANIFEST_VERSION` `plugins_manifest.py:42`); `api_version` is the
  runtime API generation (None = current).
- `requires_plugins`: advisory deps, `["id"]` or `[{id, version_range}]`
  (`_dependency_entry` `plugins_manifest.py:110-117`); missing → warn but load;
  affects load order only (`resolve_plugin_load_order` `:219+`).
- `python_dependencies`: **validated and surfaced only, never auto-installed**
  (`plugins_manifest.py:378-381`).
- `config_schema`: mapping `key -> {type?, default?, description?, required?}`;
  types in `_CONFIG_SCHEMA_TYPES` (`plugins_manifest.py:44-51`: str/int/float/bool/
  list/dict/secret — `secret` values live in `.env`). Settings live at
  `plugins.entries.<id>.settings`; mismatches warn, never fail (`validate_config_schema` `:187-216`).
- `capabilities`: declaration is **consent metadata, NOT a grant**; live grants are
  `plugins.entries.<id>.granted_capabilities` (`plugins_manifest.py:367-370`).
- `emits` / `listens`: advisory event-bus declarations (`:387-390`).
- Unknown fields: warn (v2+) / debug (v1), plugin still loads (`:173-179`).
- `requires_hermes` e.g. `">=0.19"`; unsatisfied → plugin skipped before import
  (`plugins_manifest.py:362-364`, `plugin_validate.py:114-127`).

### Minimal valid example (docs agree with source)

```yaml
# ~/.hermes/plugins/hello-world/plugin.yaml
name: hello-world
version: "1.0"
description: A minimal example plugin
```

(website/docs/user-guide/features/plugins.md "Minimal working example"; a real
bundled example: `plugins/disk-cleanup/plugin.yaml` adds
`provides_hooks: [pre_tool_call, post_tool_call, on_session_end]`.)

### `hermes plugins validate` contract

`validate_plugin_dir` (`plugin_validate.py:481-541`) runs, in order: manifest parse →
manifest fields (name/version/description) → `requires_hermes` spec → `config_schema` →
`requires_env` → loadable entrypoint → python dependencies (PEP 508) → capabilities
probe → builtin collisions → trusted_inbound → **security scan**
(`tools.plugin_guard.scan_plugin`; `dangerous` verdict fails) → core-override →
desktop surface → language packs → isolation audit. A portable `plugin.json`-only
package is admissible (Agent Plugins v1) but a native `plugin.yaml` always wins when
both exist (`:501-510`).

---

## 2. `register(ctx)` API

`ctx` is a `PluginContext` (`hermes_cli/plugins.py:230`). Key methods (line = `def`):

| Method | plugins.py line | Signature / notes |
|---|---|---|
| `register_hook(hook_name, callback)` | **:933** | → `PluginRegistration`. Unknown hook names **warn but are still stored** (`_track_callback` `:944-955`, validates against `VALID_HOOKS` `:109-204`). Callbacks receive **kwargs**; accept `**kwargs`. |
| `register_middleware(kind, callback)` | :937 | separate `VALID_MIDDLEWARE` registry |
| `register_tool(name=, toolset=, schema=, handler=)` | :456 | overriding a built-in tool needs `plugins.entries.<id>.allow_tool_override` (`PluginToolOverrideError` `:78-79`) |
| `register_command(name, handler, description)` | :647 | `/name` slash command in CLI + gateway |
| `register_cli_command(...)` | :633 | `hermes <plugin> <subcommand>` |
| `dispatch_tool(tool_name, args, **kwargs)` | :674 | invoke a tool with parent-agent context |
| `inject_message(content, role=, session_key=/origin=)` | :603 | |
| `register_system_prompt_section(id, content, *, position="after_memory", max_chars=…)` | :957 | ids 1–128 lowercase `[a-z0-9._-]`; only anchor `after_memory`; max 4000 chars/section, 8000 total, 32 sections |
| `emit(event, payload=None)` / `subscribe(event, callback)` | :984 / :1005 | event bus; emit namespace forced to `<plugin_key>:` (`hermes:` reserved for core) |
| `get_config(key, default)` / `set_config(key, value)` | :266 / :278 | plugin settings (`plugins.entries.<id>.settings`) |
| `state` property (`PluginState`) | :283 | persisted per-plugin state |
| `llm` property | :377 | `ctx.llm.complete(...)` / `complete_structured(...)` |
| `call_mcp(server, tool, arguments, timeout=30)` | :509 | capability-gated, default-off allowlist |
| `has_capability(capability)` | :501 | |
| `has_plugin(plugin_id)` | :250 | runtime probe for `requires_plugins` |
| `plugin_id` property / `profile_name` property | :246 / :394 | |
| `on_unload(callback)` | :409 | cleanup registration |
| `spawn_task(coro, *, name=None)` | :418 | host-owned asyncio task |
| `register_platform(...)` :777, `register_platform_handler` :829, `register_telegram_handler` :846, `register_slack_action_handler` :810 | | gateway adapters |
| `register_context_engine` :686, `register_memory_provider` :723, `register_context_reference` :707, `register_dashboard_auth_provider` :735, `register_approval_transport` :430, `register_auxiliary_task` :853, `register_redaction_patterns` :876, `register_locale` :890 / `register_locale_dir` :915, `register` (providers) :1078, `register_source` (secret sources) :1087 | | |

Registration removal: `PluginRegistration` handles (from
`hermes_cli/plugins_ledger.py`); a failed/abandoned load disposes everything the
plugin registered (`plugins_loader.py:527-540`).

Dispatch: core fires `invoke_hook(name, **kwargs)`
(`hermes_cli/plugins.py:1864` → `_delivery_manager().invoke_hook`; docstring `:1865-1875`:
lazy-discovers first; timeout-bounded hooks = hot-path observers + `pre_tool_call`,
bounded by `plugins.hook_callback_timeout` default 30 s; timed-out `pre_tool_call`
**fails closed** (blocks the tool), other bounded hooks fail open; `subagent_stop`
runs on the caller thread and is never moved to a timeout worker —
`plugins_dispatch.py:53` `_HOOK_CALLER_THREAD_HOOKS = {"subagent_stop"}`).
Every callback additionally receives
`telemetry_schema_version="hermes.observer.v1"` injected via
`kwargs.setdefault` (`plugins_dispatch.py:224,498`). `async def` callbacks are
awaited via `ainvoke_hook` (`plugins.py:1878`). Callback exceptions are logged and
skipped; later callbacks continue.

---

## 3. Exact kwargs per hook (quoted call sites, source ground truth)

Common note: dispatch layer adds `telemetry_schema_version="hermes.observer.v1"`
(see above). Everything below is what the **call site** passes.

### `on_session_start` — `agent/conversation_loop.py:860-863`
```python
_invoke_hook(
    "on_session_start", session_id=agent.session_id, model=agent.model,
    platform=getattr(agent, "platform", None) or "",
)
```
kwargs: `session_id`, `model`, `platform`. Fires on the first turn of a new session,
only when `not agent._persist_disabled` (`:857`); best-effort try/except (`:864-865`).

### `pre_llm_call` — `agent/turn_context.py:804-816` (`_collect_pre_llm_call_context`)
```python
_pre_results = _invoke_hook(
    "pre_llm_call",
    session_id=agent.session_id,
    task_id=effective_task_id,
    turn_id=turn_id,
    user_message=original_user_message,
    conversation_history=list(messages),
    is_first_turn=(not bool(conversation_history)),
    model=agent.model,
    platform=getattr(agent, "platform", None) or "",
    parent_session_id=getattr(agent, "_parent_session_id", None) or "",
    sender_id=getattr(agent, "_user_id", None) or "",
)
```
kwargs: `session_id`, `task_id`, `turn_id`, `user_message`, `conversation_history`,
`is_first_turn`, `model`, `platform`, `parent_session_id`, `sender_id`. Returns are
**consumed**: dict results with `{"context": ...}` (or plain strings) are joined and
injected into the **user message** — never the system prompt (`:797-799`); oversized
per-hook context spills to disk via `tools/hook_output_spill.py` (`:817-826`).
Skipped for `_persist_disabled` forks (`:800-801`).

### `post_llm_call` — `agent/turn_finalizer.py:466-476` (`_apply_output_hooks`)
```python
_invoke_hook_safely(
    "post_llm_call", logger,
    session_id=agent.session_id,
    task_id=effective_task_id,
    turn_id=turn_id,
    user_message=original_user_message,
    assistant_response=final_response,
    conversation_history=list(messages),
    model=agent.model,
    platform=platform,
)
```
kwargs: `session_id`, `task_id`, `turn_id`, `user_message`, `assistant_response`,
`conversation_history`, `model`, `platform`. Observer (return ignored). Once per
turn after the tool loop; gated on `not agent._persist_disabled` (`:465`).
Note: the field is `assistant_response` (docs table agrees).

### `post_tool_call` — `model_tools.py:693-698` (`_emit_post_tool_call_hook`)
```python
invoke_hook(
    "post_tool_call", tool_name=function_name, args=function_args, result=result,
    **_CallIds(task_id, session_id, tool_call_id, turn_id, api_request_id).hook_kwargs(),
    duration_ms=duration_ms, status=status, error_type=error_type, error_message=error_message,
    middleware_trace=list(middleware_trace or []),
)
```
kwargs: `tool_name`, `args`, `result`, `task_id`, `session_id`, `tool_call_id`,
`turn_id`, `api_request_id`, `duration_ms`, `status`, `error_type`, `error_message`,
`middleware_trace` (13 fields). `_CallIds.hook_kwargs()` maps None→`""` — the IDs are
always present, empty-string when unknown (`model_tools.py:645-655`). When `status`
is None, `(status, error_type, error_message)` are derived from the result
(`:691-692`, `_tool_result_observer_fields` `:658`). Gated on `has_hook("post_tool_call")`
(`:689-690` — zero cost when no subscriber) and suppressible via
`suppress_post_tool_call_hook()` contextvar (`:685-686`; used e.g. by
`agent/tool_executor.py:1695`). The tool executor owns the one terminal
post_tool_call per `tool_call_id` (`agent/tool_executor.py:290-293`,
`agent/inline_tool_executors.py:31-48`). Observer; hot-path timeout-bounded.

### `on_session_end` — canonical: `agent/turn_finalizer.py:793-804`
```python
_invoke_hook_safely(
    "on_session_end", logger,
    session_id=agent.session_id,
    task_id=effective_task_id,
    turn_id=turn_id,
    completed=completed,
    failed=failed,
    interrupted=interrupted,
    turn_exit_reason=_turn_exit_reason,
    model=agent.model,
    platform=_platform,
)
```
kwargs: `session_id`, `task_id`, `turn_id`, `completed`, `failed`, `interrupted`,
`turn_exit_reason`, `model`, `platform`. **Fires at each turn finalization** (a turn
= one message), not once per process — see comment `:790-791`: "run_conversation()
runs once per message; CLI/gateway own session-end cleanup." Gated on
`not agent._persist_disabled` (`:792`).
**Reduced legacy variant on interrupted non-interactive runs** —
`hermes_cli/cli_shutdown.py:189-193`:
```python
_invoke_hook(
    "on_session_end", session_id=session_id, completed=False, interrupted=True,
    model=getattr(agent, "model", None), platform=getattr(agent, "platform", None) or "cli",
    reason=reason, **extra,
)
```
→ different shape: adds `reason` (and extras), omits `task_id`/`turn_id`/`failed`/
`turn_exit_reason`. **Always accept `**kwargs` and treat fields as optional.**

### `on_session_reset`
Gateway (`/new`) — `gateway/slash_commands_session.py:214-216`:
```python
_invoke_hook("on_session_reset", session_id=_new_sid, reason="new_session",
             platform=source.platform.value if source.platform else "",
             old_session_id=_old_sid, new_session_id=_new_sid)
```
kwargs: `session_id` (new), `reason="new_session"`, `platform`, `old_session_id`,
`new_session_id`. Fires after the replacement session exists (`:211`).

CLI — `hermes_cli/cli_session_mixin.py:422-438` (`_notify_session_boundary`):
```python
context = {
    "session_id": self.agent.session_id if self.agent else None,
    "platform": getattr(self, "platform", None) or "cli",
    "reason": "new_session" if event_type == "on_session_reset" else "session_boundary"}
...
invoke_hook(event_type, **context)
```
kwargs: `session_id`, `platform`, `reason`. **Payload differs per surface** — the docs
table (hooks.md) records: CLI `session_id, platform, reason`; TUI `session_id,
platform`; gateway adds `reason, old_session_id, new_session_id`.

### `subagent_start` — `tools/delegate_tool.py:329-334`
```python
_invoke_hook(
    "subagent_start", parent_session_id=parent_sid,
    parent_turn_id=getattr(parent_agent, "_current_turn_id", "") or "", parent_subagent_id=parent_subagent_id,
    child_session_id=getattr(child, "session_id", None), child_subagent_id=subagent_id,
    child_role=effective_role, child_goal=goal,
)
```
kwargs: `parent_session_id`, `parent_turn_id`, `parent_subagent_id`,
`child_session_id`, `child_subagent_id`, `child_role`, `child_goal`. Fires when the
child is constructed and about to run (after `spawn_requested` — child may queue;
`:324-325`). Observer, wrapped in `_quiet(...)` so hook failure never breaks spawn.

### `subagent_stop` — `tools/delegate_tool_results.py:365-372`
```python
invoke_hook(
    "subagent_stop", parent_session_id=getattr(parent_agent, "session_id", None),
    parent_turn_id=getattr(parent_agent, "_current_turn_id", "") or "",
    child_session_id=getattr(child, "session_id", None), child_role=child_role,
    child_summary=entry.get("summary"), child_status=entry.get("status"),
    tool_call_history=_subagent_stop_tool_call_history(entry.get("tool_trace")),
    duration_ms=int((entry.get("duration_seconds") or 0) * 1000),
)
```
kwargs: `parent_session_id`, `parent_turn_id`, `child_session_id`, `child_role`,
`child_summary`, `child_status`, `tool_call_history`, `duration_ms` (no
`child_subagent_id` — asymmetric with subagent_start). Once per child result.
`tool_call_history` entries are redacted metadata, e.g.
`{tool_name, tool_input: {argument_keys, targets}, input_bytes, output_bytes, status}`
(synthetic sample in `hermes_cli/hooks.py:172-186`). **Caller-thread contract**: never
moved to a timeout worker (`plugins_dispatch.py:53`).

---

## 4. Do plugin hooks fire in Desktop/TUI chat sessions?

**Yes.** The full plugin-hook surface fires wherever the agent loop runs, because:

1. Desktop/Ink-TUI/dashboard chat all drive the same in-process agent: the TUI
   gateway calls `run_agent.AIAgent.run_conversation(...)`
   (`tui_gateway/methods_prompt.py:1047-1052, 1116-1131`;
   `tui_gateway/prompt_turn.py:811`), and every hook call site above lives inside
   `conversation_loop`/`turn_context`/`turn_finalizer`/`model_tools` — the shared
   loop used by CLI, gateway, TUI gateway and cron alike.
2. `invoke_hook()` **lazy-discovers plugins on first invocation** so processes that
   never explicitly call `discover_plugins()` still fire user-plugin callbacks —
   `hermes_cli/plugins.py:1864-1875` (docstring names "gateway platform events, TUI
   slash workers, query mode, cron" explicitly). TUI gateway also calls
   `discover_plugins()` directly (`tui_gateway/server.py:2013-2014`,
   `tui_gateway/mcp_rpc_helpers.py:16-20`).
3. Docs corroborate (hooks.md): plugin hooks "fire in **both CLI and gateway**
   sessions"; shell hooks table row says shell hooks run in "CLI + Gateway +
   Desktop/TUI/dashboard chat". Desktop/TUI chat goes through the same gateway-side
   agent runner, so plugin hooks land there too. Session-boundary hooks on the TUI
   path are documented as firing with the reduced TUI payload (see §3
   `on_session_reset`).

Caveat: `on_session_end` is **per-turn finalization**, not per-app-exit; hooks are
additionally suppressed for `_persist_disabled` internal forks (e.g. background
review clones) at the `on_session_start` / `pre_llm_call` / `post_llm_call` /
`on_session_end` sites.

## 4b. Shell hooks (how plugins/hooks shell out) — context

For comparison: shell hooks (`agent/shell_hooks.py`) are registered as callbacks on
the same hook manager — "every `invoke_hook()` site dispatches to the scripts"
(`shell_hooks.py:2`). Each firing spawns the script via `subprocess.Popen(shell=False)`,
pipes JSON on stdin (`_serialize_payload`), reads JSON stdout; exit 2 on a
blocking-capable event → block; per-entry `timeout` default 60 s capped 300
(`agent/shell_hooks.py:330-430`, docs "JSON wire protocol"). The stdin envelope is
`{hook_event_name, tool_name, tool_input, session_id, cwd, profile, extra:{...}}`
with all event-specific kwargs under `extra`. Config lives under the top-level
`hooks:` key in profile `config.yaml`, NOT under `plugins:`. A plugin that wants to
shell out can either do it in its own Python callback (own process management) or
tell the user to add a `hooks:` entry.

---

## 5. Enabling plugins & where user plugins live

- **User plugins live at `~/.hermes/plugins/<name>/`** — resolves via
  `get_hermes_home() / "plugins"` (`hermes_cli/plugins_discovery.py:209`), i.e.
  `$HERMES_HOME/plugins/` for profiles (`~/.hermes/profiles/<p>/plugins/`), NOT
  hardcoded `~/.hermes` for non-default profiles.
- **Opt-in allow-list**: `plugins.enabled` (list of registry keys) in
  `~/.hermes/config.yaml`; `plugins.disabled` is a deny-list that **always wins**
  (`plugins_discovery.py:112-131`; docs "Plugins are opt-in": nothing with hooks or
  tools loads until the name is in `plugins.enabled`). Missing `plugins.enabled`
  key = "nothing enabled yet" (`None`); empty list = explicit none.
- Three ways to flip state (docs plugins.md, agrees with
  `hermes_cli/plugins_cmd_toggle.py`, `hermes_cli/subcommands/plugins.py`):
  ```bash
  hermes plugins                    # interactive toggle
  hermes plugins enable <name>      # add to plugins.enabled
  hermes plugins disable <name>     # remove from enabled + add to disabled
  ```
  Dashboard/Desktop toggle writes the same key. `hermes plugins install owner/repo`
  then prompts `Enable 'name' now? [y/N]` (default no; `--enable`/`--no-enable`).
- Exceptions to opt-in: bundled `backend`/`platform`-kind plugins auto-load;
  memory providers activate via `memory.provider` config key, not
  `plugins.enabled` (`plugins_manifest.py:354-358`, docs opt-in section).
- Related config keys (docs, confirmed in `config_defaults.py` / plugins code):
  `plugins.hook_callback_timeout` (default 30, max 600, 0=off),
  `plugins.load_timeout_seconds` (default 10), `plugins.clone_timeout_seconds`
  (install), `plugins.entries.<id>.settings` / `.granted_capabilities` /
  `.allow_tool_override`.
- `hermes plugins validate <dir>` = admission gate (§1).
  `HERMES_PLUGINS_DEBUG=1` = verbose discovery logging (`plugins.py:84-104`).

## Gotchas for plugin authors

1. Always write callbacks as `def cb(..., **kwargs)` — payload shapes differ per
   surface (`on_session_end`, `on_session_reset`) and the dispatch layer injects
   `telemetry_schema_version`.
2. `post_tool_call` ID fields are `""` (empty string), never `None`, when unknown.
3. Blocking hooks: `pre_tool_call` (directives `block`/`approve`/`modify`) and
   `pre_llm_call` (context injection) are the policy surfaces; `post_tool_call`,
   `post_llm_call`, `on_session_*`, `subagent_*` are observers — returns ignored.
4. Slow callbacks on timeout-bounded hooks (hot-path observers + `pre_tool_call`)
   get abandoned at `plugins.hook_callback_timeout`; a timed-out `pre_tool_call`
   **blocks the tool (fail closed)**. Do shell-outs on your own thread/queue, not
   inline.
5. `subagent_stop` runs on the caller thread — a blocking callback there stalls the
   parent directly.
6. `VALID_HOOKS` is the authoritative event list (`hermes_cli/plugins.py:109-204`);
   registering an unknown name logs a warning listing valid names and is still
   stored (so it will never fire — check the warning).
