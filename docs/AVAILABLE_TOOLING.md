# AVAILABLE TOOLING — what already exists on this machine

Read this **before** writing any new capability. It exists because the project
already had MaaFramework installed, working, and able to drive MuMu for an
unknown length of time while development re-implemented screenshots, template
matching and input by hand — and paid for it with a two-hour battle-button hunt.

Rule: if a task needs screenshots, button/page location, template matching, OCR,
ROI search, tapping, waiting for a page, waiting for a button to disappear,
retrying, or UI recovery, **check this file first**.

- Machine-readable twin: **`knowledge/tooling/tool_registry.json`**
  (per-tool `version / status / capabilities / verified / benchmark / best_for /
  limitations / fallback / last_checked`). Code and expert logic should read that file;
  this page is for humans.
- If `last_checked` is older than 7 days, re-probe before trusting it.
- The MAA-was-installed-but-unused incident is written up at
  **`knowledge/failure_patterns/tooling/TOOLING_MISSELECTION_MAA_UNUSED.md`**.

Every row below was verified on this machine on 2026-09-14. Anything not
verified is marked as such; nothing here is copied from a README.

---

## 1. MaaFramework — INSTALLED, WORKING, IN PRODUCTION USE

| item | value |
|---|---|
| Python binding | `MaaFw==5.12.3` (module `maa`) |
| Agent binaries | `MaaAgentBinary==1.0.1` |
| Location | `E:\无尽冬日智能体\.venv\Lib\site-packages\maa` |
| Import | `import maa` → OK |
| Adapter | `winter_agent_v2/maa_executor.py` (`MaaExecutorAdapter`) |
| Router | `winter_agent_v2/executor_router.py` (`ExecutorRouter`) |
| Routing decisions | `knowledge/execution/backend_routing.json` |
| Config switch | `config/v2.json` → `executor.maa.enabled` |

### Verified capabilities

| capability | API | status |
|---|---|---|
| Connect to MuMu over ADB | `AdbController(adb_path, address, screencap_methods, input_methods, config)` | **verified**, `connected=True` |
| Emulator-native capture | `MaaAdbScreencapMethodEnum.EmulatorExtras` (bit 64), from `Toolkit.find_adb_devices()` | **verified, 8.9 ms mean / 20 samples** |
| Fast input | `post_click` / `post_swipe` / `post_press_key(4)` via EmulatorExtras / Maatouch | verified (used in the action A/B) |
| Template match | `Tasker.post_recognition(JRecognitionType.TemplateMatch, JTemplateMatch(...))` | **verified**, multi-template, multi-threshold, `roi`, `method` (5 = TM_CCOEFF_NORMED), `green_mask` |
| Feature / colour / OCR / NN matching | `JFeatureMatch`, `JColorMatch`, `JOCR`, `JNeuralNetwork*` | API present; **OCR not usable — see §2** |
| Recognition composition | `JAnd(all_of=[...], box_index=)` / `JOr(any_of=[...])` | API present, not yet exercised |
| Read a result | `tasker.post_recognition(...).wait().get()` → `TaskDetail.nodes[0].recognition` → `.hit` / `.box` / `.all_results` / `.best_result` | **verified** |
| In-memory templates | `Resource.override_image(name, np.ndarray)` — no PNG copy, no bundle rebuild | **verified** |
| Recognition debug drawing | `Tasker.set_save_draw(True)` | **verified** (this is what caught the mis-crop class of bug) |
| Pipeline flows | `Resource.override_pipeline(dict)` + `Tasker.post_task(entry, override)` | API present, not yet exercised |
| Standalone action | `Tasker.post_action(JActionType, JActionParam, box=...)` | **verified** (`DoNothing`) |

### Three traps that look like matcher bugs

All three cost real time today and are now handled or gated:

1. `Resource.post_bundle(path)` handed an **ordinary template folder** corrupts the
   resource state. Every later `post_recognition` then fails at ~0.8 ms with
   `Tasker not inited` in the C++ log, which reads exactly like "the template does
   not match". Guarded by `_is_maa_bundle()`.
2. `Tasker.bind()` returning `True` is not enough — check `tasker.inited`
   afterwards. Reported now as `MAA_TASKER_NOT_INITED`.
3. `Toolkit.find_adb_devices(adb_path)` can return **no device**, silently losing
   the `extras.mumu` block and with it the fast capture channel: 8.9 ms becomes
   ~178 ms with no error anywhere. The adapter tries the call both with and
   without the path and records what it got in `adapter.negotiated`.
4. **A template threshold does not carry over from a hash distance.** The legacy
   semantic for `BTN_OPEN_INTEL_WILD_HUD` carries a relaxed tolerance because the
   control's blue fill animates; a MAA node using the default threshold 0.7 missed
   it in production at a correlation of 0.448. Two rules follow:
   - a node may only be promoted on **≥3 independent live positives and ≥3
     negatives** (`tools/maa_migrate.py` now reports `corpus_sufficient` and
     prints `PROMOTION BLOCKED` otherwise) — one frame cannot reveal animation;
   - for an animated control, prefer re-cropping or a two-signal page model over
     lowering the threshold toward the negative band.

---

## 2. OCR — the project's RapidOCR, NOT MAA's

MaaFramework's OCR needs an onnx model bundle (`det.onnx`, `rec.onnx`,
`keys.txt`). **There is none on this machine** — a filesystem search found no
such files, and `post_ocr_model` on the MAA resource was never satisfied. MAA
recognition therefore reports `OCR_MODEL_MISSING` instead of returning an empty
list that would look like "no text on screen".

The project's working OCR is:

| item | value |
|---|---|
| Backend | `rapidocr-onnxruntime==1.4.4` |
| Wrapper | `winter_agent_v2/ocr.py` (`OCRService`, `RapidOCRBackend`, `ResilientOCRBackend`) |
| Constraint | HUD numbers must be read from a **dedicated ROI**, never full-screen (a full-screen pass misses the stamina gauge entirely; the ROI reads it at 0.999) |

---

## 3. Device layer

| tool | value / status |
|---|---|
| ADB binary | `D:\Program Files\Netease\MuMu Player 12\nx_main\adb.exe` |
| Serial | `127.0.0.1:7555` |
| Device | 720×1280, foreground package `com.gof.china` |
| ADB capture | `exec-out screencap -p` — **verified, 324.1 ms mean / 20 samples** |
| ADB input | `shell input tap` — works, but MAA's native channel is preferred |

MuMu is **not** started by default:

```
"D:/Program Files/Netease/MuMu Player 12/nx_main/MuMuManager.exe" control -v 0 launch -pkg com.gof.china
"D:/Program Files/Netease/MuMu Player 12/nx_main/adb.exe" connect 127.0.0.1:7555
```

---

## 4. Vision / numeric libraries

| library | version | used by |
|---|---|---|
| `opencv-python` | 5.0.0.93 | `matchers.py` (`match_ccoeff`, TM_CCOEFF_NORMED multi-scale) |
| `numpy` | 2.5.2 | everywhere; also MAA's frame format (`ndarray`, RGB, `(1280, 720, 3)`) |
| `pillow` | 12.3.0 | frame I/O, crops, annotated evidence |
| `onnxruntime` | 1.19.2 | RapidOCR |

Python: **use the project venv** `E:\无尽冬日智能体\.venv\Scripts\python.exe`
(has PIL + RapidOCR). The managed Python 3.13 has **no PIL**.

---

## 5. Engineering tooling

| tool | status |
|---|---|
| git | repo at `E:\无尽冬日智能体`, HEAD recorded in `10_LAST_HANDOFF.md` |
| pytest | project venv; full suite needs `--basetemp="E:/无尽冬日智能体/tools/_pt_tmp"` (default temp cleanup trips the bulk-delete guard and kills the run) |
| wiring check | `tools/check_wiring.py` — execution-level, must print `problems: 0` |
| MAA measurement | `tools/maa_migrate.py nodes` (corpus precision/recall), `tools/maa_live_case.py state\|capture-ab\|action-ab\|battle` |
| Executor audit | `tools/executor_audit.py` → `docs/EXECUTOR_REALITY_AUDIT.md` |
| Browser automation | not used in this project |
| External projects | `knowledge/external/projects.json` — 0 integrated so far |

---

## 6. Environment traps (this machine)

| trap | consequence / countermeasure |
|---|---|
| Bash has **no coreutils** (`ls/cat/head/tail/sleep/wc/date` → not found) | run everything through Python, redirect to `out.txt`, then Read it |
| PowerShell stdout is **not returned** | never rely on PowerShell output |
| Long foreground commands get **SIGTERM** | run anything over ~5 s with the background flag |
| MaaFramework writes C++ logs to **stderr** | redirect stderr separately, or set `stdout_level` |
| An external editor **flushes a stale buffer** over files being edited here | after every edit: grep the change, run `tools/check_wiring.py`, and commit. Today this silently reverted a fix mid-session and made a correct matcher look broken |

---

## 7. What NOT to rebuild

Already solved, do not hand-roll again:

- frame capture (use `MaaExecutorAdapter.capture()` / `.screenshot()`)
- tapping / swiping / key events (MAA controller)
- ROI-scoped template matching (MAA `roi`) — and MAA searches the full frame when
  the position is unknown, which is exactly what the legacy fixed-ROI path cannot do
- recognition result visualisation (`set_save_draw`, `save_annotated`)
- wait-for-page / wait-for-disappearance loops (`MaaExecutorAdapter.wait_page` /
  `wait_disappear`)
- retry/settle choreography around a UI flow

Still genuinely ours to build: Goal, Strategy, WorldState, ResourceBank, event
planning, Knowledge, Experience, Verifier, and the **game knowledge** — templates,
page models and their evidence. MaaFramework supplies the engine; it ships no
Whiteout Survival resources.
