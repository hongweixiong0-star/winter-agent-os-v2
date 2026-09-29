# WorkBuddy / Codex Skill Inventory

Last checked: 2026-09-26 (Windows user `xhw`, project `E:\无尽冬日智能体`).

This inventory separates an Agent Skill (instructions for an assistant) from a
standalone executable and from a capability called by the V2 game runtime.
Having a `SKILL.md` on disk does not prove that another assistant loaded it or
that AUTO can execute it.

## Discovery evidence

- WorkBuddy's active skill-list cache is
  `C:\Users\xhw\.workbuddy\.skill-list-cache.json`. Its current scope records
  55 catalog entries and lists the three user-installed game-development skills
  below with `disable=false` and `disableModelInvocation=false`.
- The running desktop executable is `E:\work Buddy国内\WorkBuddy\WorkBuddy.exe`,
  file/product version `5.6.2`.
- WorkBuddy's packaged built-in skill root is under
  `E:\work Buddy国内\WorkBuddy\resources\app.asar.unpacked\resources\plugins\workbuddy-builtin\skills`.
  The cache also lists enabled marketplace/plugin and connector skills. Most
  are unrelated to Winter Agent V2 and are intentionally not reproduced here.
- Project-local WorkBuddy method Skills are present under
  `.workbuddy/skills/`, but do not appear in the active user skill-list cache;
  their files are available to inspect, while WorkBuddy runtime loading is not
  proven by the cache.
- `.codebuddy/skills/mumu-control` is a separate local copy. Its existence does
  not establish that WorkBuddy or Codex loads it.
- Codex's current available-skill catalog exposes the project skill
  `.agents/skills/maa-pipeline-generate/SKILL.md` as
  `maa-pipeline-generate`. No WorkBuddy credential, session, or configuration
  files were copied into Codex.

## Relevant installed skills

| Skill | Tool / install path | Source and contents | WorkBuddy | Codex | V2 AUTO |
|---|---|---|---|---|---|
| `maa-pipeline-generate` | WorkBuddy: `C:\Users\xhw\.workbuddy\skills\maa-pipeline-generate`; project/Codex copy: `.agents/skills/maa-pipeline-generate` | Both contain `SKILL.md`, `scripts/generate_node.py`, `scripts/generate_sweep.py`, and `scripts/project_paths.py`. WorkBuddy copy is listed as enabled user setting. Upstream source URL is not declared in the installed files. | Listed enabled | Available as project Skill | Its `generate_node.py` is imported and called in-process by `winter_agent_v2.pipeline_autogen.PipelineAutoGen`; actual device capture and persistent routing remain owned by V2. |
| `mumu-control` | WorkBuddy: `C:\Users\xhw\.workbuddy\skills\mumu-control`; CodeBuddy: `.codebuddy/skills/mumu-control` | `SKILL.md`, `requirements.txt`, and scripts for screenshot, tap, swipe, text input, key event, and UI scan. WorkBuddy cache lists the user copy as enabled; CodeBuddy copy is separate. | Listed enabled | Files readable; not in Codex available-skill catalog | Not called by AUTO. Its independent input scripts must not be run alongside the V2 device lease. |
| `skills-security-check` | `C:\Users\xhw\.workbuddy\skills\skills-security-check` | `SKILL.md`, icon, marketplace metadata. WorkBuddy cache lists enabled marketplace installation, version 1.0.0. | Listed enabled | Files readable; no Codex skill registration | Not called by V2 runtime. |
| `agent-browser` | `C:\Users\xhw\.workbuddy\plugins\marketplaces\codebuddy-plugins-official\plugins\agent-browser` | `SKILL.md`, version 1.3.0; browser automation, not game-device control. | Listed enabled plugin | Files readable; not a current Codex available skill | Not used by V2. |
| `playwright-cli` | `C:\Users\xhw\.workbuddy\plugins\marketplaces\codebuddy-plugins-official\plugins\playwright-cli\skills\playwright-cli` | `SKILL.md`; browser CLI instructions. | Listed enabled | Files readable; not a current Codex available skill | Not used by V2. |
| `find-skills` | `C:\Users\xhw\.workbuddy\plugins\marketplaces\codebuddy-plugins-official\plugins\find-skills\skills\find-skills` | `SKILL.md`; Skill discovery. | Listed enabled | Files readable; not a current Codex available skill | Not used by V2. |
| `github` | `C:\Users\xhw\.workbuddy\plugins\marketplaces\workbuddy-connector-plugins-official\connectors\github\skills\github` | Connector Skill, present in WorkBuddy's current skill cache. | Listed enabled connector | No corresponding Codex Skill/tool loaded here | Not used by V2. |
| `skill-creator` | WorkBuddy packaged built-in root (see Discovery evidence) | WorkBuddy cache lists the built-in Skill. | Listed enabled, model invocation enabled | Not a current Codex available skill | Not used by V2. |
| `marketplace-skill-installer` | WorkBuddy packaged built-in root (see Discovery evidence) | WorkBuddy cache lists the built-in installer Skill. | Listed enabled | Not a current Codex available skill | Not used by V2. |
| `controlled-ab-replay` | `.workbuddy/skills/controlled-ab-replay` | Project-authored `SKILL.md`; offline controlled replay methodology. | Present in project directory; active loading not proven | Readable and reusable manually; not listed in Codex's available-skill catalog | Not called by AUTO. |
| `frame-evidence-joins` | `.workbuddy/skills/frame-evidence-joins` | Project-authored `SKILL.md`; joins screenshots/frames to episode ownership. | Present in project directory; active loading not proven | Readable and reusable manually; not listed in Codex's available-skill catalog | Not called by AUTO. |
| `guard-emitter-coverage` | `.workbuddy/skills/guard-emitter-coverage` | Project-authored `SKILL.md`; decision/guard coverage review. | Present in project directory; active loading not proven | Readable and reusable manually; not listed in Codex's available-skill catalog | Not called by AUTO. |
| `live-directed-verification` | `.workbuddy/skills/live-directed-verification` | Project-authored `SKILL.md`; bounded real-device verification. | Present in project directory; active loading not proven | Readable and reusable manually; not listed in Codex's available-skill catalog | Not called by AUTO. |
| `reader-blind-spot-triage` | `.workbuddy/skills/reader-blind-spot-triage` | Project-authored `SKILL.md`; diagnoses frame-reader false negatives. | Present in project directory; active loading not proven | Readable and reusable manually; not listed in Codex's available-skill catalog | Not called by AUTO. |
| `skill-install-gate` | `.workbuddy/skills/skill-install-gate` | Project-authored `SKILL.md`; describes WorkBuddy's skill install procedure. | Present in project directory; active loading not proven | Readable and reusable manually; not listed in Codex's available-skill catalog | Not called by AUTO. |

## `maa-pipeline-generate` verified capabilities

- The installed component is an Agent Skill plus two Python scripts. The
  single-node script exposes a working `--help` CLI. It generates **OCR text
  nodes only** (`recognition`, `expected`, `roi`, `action`, `post_delay`,
  `timeout`) and supports Click, DoNothing, LongPress, Swipe, ClickKey, and
  InputText actions. It does not generate TemplateMatch/ColorMatch/Custom
  recognition, a complete multi-step task, or verified `next` edges.
- The Skill documentation describes MaaMCP device/OCR and Pipeline tools, but
  `maa_mcp` is absent from this project's `.venv`. Directly launching that
  standalone flow against the device is therefore unavailable here and would
  create a second device controller anyway. Codex does not need a duplicate
  install: it can use this Skill's instructions and scripts.
- V2's adapter calls the installed script's actual `main()` in-process, feeding
  it the OCR box and score from V2's current leased frame. It replaces only the
  script's device, OCR, path-resolution, and file-merge callbacks; `main()` still
  performs argument handling, ROI calculation, node construction, and the
  generator's merge stage. V2 then atomically writes its own node artifact and
  updates the existing routing table, so no second device owner or external
  Skill registry is introduced.
- The external script emits an auditable OCR candidate. Because this host's MAA
  bundle lacks its OCR model files, a V2-native TemplateMatch crop is currently
  the active recognition route where a template can be made. Runtime generation
  does not currently ask Qwen to invent an unknown semantic; it requires an
  existing semantic ID and declared Chinese label, and is triggered by an
  unresolved recognition target. A failure is bounded to one attempt per
  semantic per run and does not stop AUTO.
- Evidence `dataset/raw/autogen/20260925_220840_runtime_auto_closed_loop.json`
  records a runtime-generated alliance-technology node, a subsequent MAA action,
  and a passing verifier (`HOME` to `ALLIANCE/TECHNOLOGY`). This proves one
  controlled runtime generation-and-execution loop; it does not prove that V2
  can autonomously author arbitrary new Skills or discover undeclared controls.

## Boundaries and next implementation work

- Installed WorkBuddy Skills are not themselves callable from V2. Only the
  explicit V2 adapter above is part of the runtime.
- The six project `.workbuddy/skills` files are useful development methods and
  can be read by Codex when needed; copying them to another root would create
  duplicate inventories without making AUTO execute them.
- Runtime generation uses one captured leased-device frame. It must pass that
  exact frame through node derivation so the OCR evidence, crop, and generated
  template cannot silently refer to different captures.
- Next coverage work should classify goal steps as shared navigation/action,
  state observation, or truly distinct recognition/action nodes, then repair
  missing AUTO routes and explore only genuinely unknown UI on the test role.
