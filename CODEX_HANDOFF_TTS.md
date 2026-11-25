# Codex handoff — Vietnamese TTS Human Evaluation Workspace

**Status:** Project handoff distilled from the ChatGPT discussion, not a verbatim chat transcript.
**Last updated:** 2026-11-22.
**Primary goal:** Maintain and extend a real, human-facing, multi-annotator web application for Vietnamese text-to-speech (TTS) quality assessment. **The application is no longer a 10-example demonstration**.

## 0. Where to begin

1. Read this file **in full**, then `README.md` and `AGENTS.md`.
2. Inspect `server.py`, `index.html`, the Windows launch scripts and `manifest_template.json`.
3. Verify the current implementation against the specifications below. Do not assume a feature exists solely because it was discussed in ChatGPT or is described in README.
4. Run the app locally and test workflows end to end, including input validation, saved drafts, phase separation, per-annotator isolation, canonical A/B normalization and exported data integrity.
5. Report: what works, what is partially implemented, what is missing, bugs/risks with reproducible steps, and a prioritized next-action plan. **Do not silently replace the defined labels or redesign the methodology.**

## 1. Project history and final user intent

The chat progressed through the following stages:

1. The user provided a Vietnamese design report for a human TTS annotation label set based on **GSRM**, **SpeechJudge**, **UniSRM**.
2. The user requested workflow diagrams, and challenged which process steps were actually supported by the report; extra gates / loops / numerical QC thresholds not specified by the report must not be presented as established facts.
3. The user asked for full-text verification of all three papers and a traceability table for every label. A previous assistant reported specific paper-derived correspondences (see §8), but independent source re-checks remain appropriate for scholarly claims.
4. The user requested >=10 fully concrete examples covering all steps, with explicit input and output at each stage rather than abstract “if A / if B” branches.
5. The user requested presentation slides, then an interactive web walkthrough, then **Light Mode**.
6. **Final overriding requirement:** Convert the demo into an **operational human evaluator website** that implements every step from the design report. Evaluators must work with real user-supplied audio and target texts. Fictional example samples and demonstration results must not appear as production records.
7. A Python/SQLite local/LAN web app was produced (current files here). That implementation is an initial version and should be independently audited; it is not equivalent to a human-study validation or public-internet security review.

**Priority ordering:** Actual evaluation capability and methodological fidelity > demo visuals. Default UI theme must remain **light**, with optional dark mode. The evaluator language should be Vietnamese and terminology consistent. Do not mix the Single and Pairwise scoring forms.

## 2. Inputs, blinding, and users

### Single Audio item
- One target Vietnamese transcript and **one actual TTS audio file**.
- Optional style instruction and reference recording when available.
- Do **not** show the evaluated model, seed, WER/CER, or other annotators’ judgments to an evaluator.

### Pairwise item
- One shared target transcript, **two actual TTS audio files** A and B.
- Shared style/reference instructions only when these are genuinely equivalent; matching target text is required.
- Randomize the displayed order of A/B to mitigate positional bias. Retain original IDs and the mapping.

### Annotation identity and task assignment
- A separate `username` per human annotator; operator/admin is a distinct role.
- Target **3 independent completed labels per item** by default, preserving each individual record prior to any aggregation.
- Divide items into `pilot` and `main` phases. Prevent duplicate completed submission by one annotator for the same item; allow independent evaluators to annotate the same item.
- Save submission timestamps and time spent, plus notes and confidence where present.

## 3. Exact Single Audio label specification

### 3.1 Text accuracy
Exactly one:
- `no_error` — content correctly and fully spoken;
- `has_error` — a recognizable content error;
- `unsure` — annotator cannot confidently determine correctness.

When `has_error`, select **at least one** error type:
- `omission`: missing syllable/word/phrase, e.g., omission of “sẽ”;
- `insertion`: extra content not present in target transcript;
- `substitution`: wrong word, name, number, changing content (e.g., 120 -> 102);
- `repetition`: unintended repeated word/phrase.

**Important:** `repetition` as a distinct category is a **project-specific extension**; SpeechJudge groups repetition with insertion. Errors in pauses without lexical changes are prosody/pacing errors, not automatically text errors. Valid regional accents are not automatically text errors.

### 3.2 Six independent integer quality ratings, each 1–5
- `pronunciation`: syllables, consonants/vowels, tone, clarity, swallowed/distorted speech;
- `intonation`: pitch shape, sentence type, meaning-related emphasis;
- `pacing`: speaking rate, rhythm, breaks/pauses, continuity;
- `expressiveness`: appropriateness of emotion/style, not simply maximum emotion;
- `audio_quality`: hiss, noise, clipping, glitches, distortion, cuts/artifacts;
- `naturalness`: overall human likeness, assessed **independently**; do not automatically average the other five axes.

Anchors: 1 very poor, 2 poor, 3 average with recognizable issues, 4 good with minor issues, 5 very good with few or no meaningful defects. Each axis should also have UI-specific descriptions for at least 1/3/5. Appropriate neutral delivery can be rated highly for expressiveness.

### 3.3 Optional and exceptional statuses
- `confidence`: `low` / `medium` / `high`;
- `note`: free text;
- `invalid`: a broken/unplayable item or incorrect data configuration makes valid annotation impossible; **a misread TTS audio is NOT automatically invalid**;
- `skipped`: evaluator elects not to rate; store reason. Invalid and skipped must never be treated as completed scored records.

## 4. Exact Pairwise label specification

### 4.1 Content checks performed separately
For displayed A and displayed B, independently choose `no_error`, `has_error`, or `unsure` (`text_accuracy_a` / `text_accuracy_b`, normalized to canonical original A/B on persistence). Unlike Single, no need to assign four error-type chips for each audio unless a later explicitly authorized design revision adds them.

### 4.2 Five-level relative naturalness preference
Exactly one rating:
- `+2` — displayed A much better;
- `+1` — displayed A slightly better;
- `0` — Tie / no confident noticeable difference;
- `-1` — displayed B slightly better;
- `-2` — displayed B much better.

Compare clarity/sonic quality, intonation, pacing, pronunciation, emphasis and expression; keep content correctness as a **separate attribute**. A small lexical error need not automatically determine naturalness winner, although severe speech errors may affect perceived naturalness. Do **not** collect the six Single 1–5 scores within the Pairwise form.

Optional `preference_reasons` (multi-select): `intonation`, `pacing`, `pronunciation`, `expressiveness`, `audio_quality`, `other`; also optional `confidence`, `note`. These are explanations for the comparative choice, not numeric axes.

`Tie`, `invalid`, `skipped` are distinct states; invalid/skipped require reasons.

### 4.3 Canonical A/B storage
- Store `pair_id`, original `sample_a_id` and `sample_b_id`, and `display_swapped`.
- Randomize display order per annotator/pair; the source of truth is original A/B.
- If swapped, `canonical_preference = -display_preference`, and the content-accuracy A/B answers must also be mapped back to their original sample IDs.
- Preserve `preference_display` as optional audit data alongside canonical `preference`.
- Example: Original S01-A is displayed as B; original S01-B is displayed as A. Evaluator chooses displayed A+2 => canonical preference is `-2`.

## 5. Collection, Pilot, QC, exports

**Pilot** (before broad collection): gather trial annotations; inspect score distributions by Single dimension; annotator agreement; Pairwise Tie counts, A/B win rates, preference strengths. The original report does **not** specify pilot size, formula, QC pass thresholds or mandatory rounds of guideline revision. Do not invent these as approved criteria. Report descriptive statistics separately from a QC decision made by researchers.

**Main collection**: keep independent submitted records. Preserve confidence, free notes, username, status, timestamps/duration. Use a default target of 3 independent completed annotations per item; do not automatically manufacture a “gold” label.

**Exports**:
- `samples.jsonl`: sample metadata with source audio link, target transcript, optional style/reference, phase and operator-private provenance;
- `pairs.jsonl`: pair IDs, original A/B sample IDs, phase;
- `single_annotations.jsonl` plus `.csv`;
- `pair_annotations.jsonl` plus `.csv`.

All source IDs needed for joining annotations to items must be preserved. Model identifiers, seed and WER/CER may be stored only as operator-private metadata; do not show these on evaluator forms or in evaluator-facing API payloads.

**QC**: Report distributions per score axis, content status distribution/consensus, agreement statistics if defined, tie frequency and A/B wins and preference strength. Flag data-quality risks; do not discard valid misread-audio cases. Pay attention to positional bias and agreement across 3 independent annotators. There is no automatic universal accept/reject threshold defined by the supplied report.

## 6. Downstream interpretation

The annotation app's job is data capture and quality control. **It need not train or host a speech reward model** unless separately requested.
- Single data supports a Vietnamese TTS benchmark and pointwise / multidimensional reward-model training.
- Pairwise data supports preference or comparative reward modeling and human preference evaluation.
- Aggregated benchmark can be produced independently of model training.
- Reward models may support reranking or later DPO/RLHF, only after validating that a model does not systematically favor natural but text-incorrect audio.

Concrete caution from the earlier simulation (NOT real data): the target “Xin lỗi vì sự bất tiện này. Chúng tôi sẽ khắc phục sớm nhất.” had one rendition reading all content and another missing “sớm nhất” despite sounding more natural. Such an audio may have stronger naturalness preference, but still carries an `omission` risk. Do not conflate naturalness and text accuracy.

## 7. Implemented initial application and operational constraints

**Current implementation files** (inspect; do not assume exhaustive correctness):
- `server.py` — Python stdlib HTTP API and SQLite storage;
- `index.html` — light-default web UI with operator and evaluator workflows;
- `README.md` — launch, schema, and user guide;
- `manifest_template.json` — `{"samples":[],"pairs":[]}`;
- `start_windows.bat`, `start_windows_lan.bat`, `start_windows_local_only.bat`, `start_windows_python.bat`, `start_local.sh`, `start_lan.sh`, `start_macos.command`, `start_macos_lan.command`.

**Running:** Python >=3.10. On Windows, run `start_windows.bat`; on Linux, `./start_local.sh`; on macOS, `./start_local.sh` or `start_macos.command`. Save the first-run `admin` password and open `http://localhost:8765`. For trusted LAN access only, use the corresponding `start_windows_lan.bat`, `./start_lan.sh`, or `start_macos_lan.command` and share `http://<LAN-IP>:8765`; restrict firewall access to the trusted network. The runtime creates `data/annotations.db` and `data/media/` (back up the whole `data/` folder). Do not expose plain HTTP publicly.

**Admin UI:** upload actual audio; create sample IDs, transcript, optional style/reference/private metadata; construct Pairwise items; set pilot/main; create annotator users; inspect QC; export JSONL/CSV. Bulk import is through a JSON manifest (not direct CSV/JSONL import). Import sample requires `sample_id`, `target_text`, `audio_url`; pair requires `pair_id`, `sample_a_id`, `sample_b_id`. Audio URL may be an uploaded `/media/` resource or HTTPS URL. Only use shared style/reference when aligned.

**Evaluator UI:** actual audio players, task queue, structured text-accuracy and quality/preference forms, auto-saved drafts, reasons for invalid/skipped, review/submit. Completed submissions cannot be overwritten by evaluator. Admin and annotator data visibility must be checked.

**README-stated limits:** audio upload up to 60 MB per file, JSON import up to 4 MB per request, allowed `.wav`, `.mp3`, `.m4a`, `.ogg`, `.webm`, `.flac`, `.aac`, `.opus`; codec playback depends on browser. Authentication and role restrictions are local/LAN-oriented, not internet-hardened. No TLS, password recovery, account lockout, formal compliance or production-scale deployment assurances. The app starts with **no demonstration dataset**.

**Past assistant's reported testing** (reproduce independently): separate evaluator accounts; upload audio; per-annotator independent submissions; A/B normalization; persistence; exports; browser appearance. These past reports are **not independent proof** of all features, security or usability.

## 8. Paper attribution: what is and is not adopted

Primary reading links:
- **GSRM:** https://arxiv.org/pdf/2602.13891
- **SpeechJudge:** https://arxiv.org/pdf/2511.07931
- **UniSRM:** https://aclanthology.org/2026.acl-long.2150.pdf

Previous ChatGPT paper comparison reported:
- **GSRM:** pointwise dimensions, including intonation, pacing, expressive intensity/correctness, human-likeness, and categorical mispronunciation. A 1–5 multi-dimension scale is relevant; the app's six dimensions are **adapted**, not verbatim. The project's `expressiveness` corresponds more to appropriateness than intensity.
- **SpeechJudge:** Pairwise independent content checks and five-level naturalness preference (A+2/A+1/Tie/B+1/B+2); omission/insertion/substitution. The project adds separate `repetition` although SpeechJudge grouped repetitions with insertion. Pilot and annotator disagreement were discussed in the paper analysis.
- **UniSRM:** reference-aware human A/B verification, randomized order / position bias mitigation, independent annotators, and use of a seven-criterion, 1–5 single-audio QualiSpeech dataset for another task. Human Task 1 is not the same as model-produced 0–10 per-axis scores; its verification did **not** use SpeechJudge's five-level Tie preference scale.

**Do not assert without verifying full text** that confidence, note, skipped, exact `display_swapped` field, or project JSONL schema were used identically in these papers. These are project-specific metadata and interface decisions unless independently shown otherwise. When preparing scholarly citations, cite exact sections/pages and preserve distinctions among GSRM, SpeechJudge, UniSRM and borrowed datasets.

## 9. Explicit non-goals and open questions

- The earlier **10 samples / 20 fictional audio descriptions / 30 simulated Pairwise votes** were for educational walkthroughs only. They are **not research data** and must never be added as real annotations by default.
- The older PPTX and `tts_interactive_walkthrough_light.html` are teaching artifacts, **not** the operational source of truth.
- No requirements for automatic reward model training, synthetic-audio generation, subjective rating aggregation formula, minimum pilot size, exact agreement statistic, pass/fail QC gates, production SSO, or public hosting were established by the original report. Any such feature needs an explicit project decision.
- Obtain genuine audio and authorized annotator access before conducting a human study. Distinguish tested code behavior from validated human-study results.

## 10. Suggested first Codex message

> Read `AGENTS.md`, `CODEX_HANDOFF_TTS.md`, and `README.md` completely, then audit `server.py` and `index.html` against the documented Single Audio and Pairwise human-annotation workflows. Check pilot/main assignment, real audio upload/playback, validation, draft persistence, independent annotator submissions, `invalid`/`skipped`, randomized A/B display with canonical output mapping, metadata blinding, QC and exports. Run targeted tests, identify gaps with exact file references, and propose the minimum fixes. Do not replace the label schema or populate fictional examples. Begin by reporting your audit findings; modify code only after I give a concrete change request.

## 11. Implementation update — 2026-11-22

After the requested audit, the user authorized completion of the application. The documented Single and Pairwise label schemas above remain unchanged. The browser CSP now permits the page's hashed inline script and styles; evaluator API requests use opaque per-user task tokens, while canonical source IDs remain in the database and operator exports. Source input validation rejects null IDs/transcripts, nonexistent local media paths, and files whose headers do not match the selected audio extension. This header check is not full media decoding. QC now exposes content counts, canonical A/B wins, displayed-position counts, and phase-mismatch warnings without an automatic pass/fail decision. Annotation CSV headers are stable even for empty exports. The server requires `data/.server_secret` alongside an existing database so unfinished Pairwise drafts retain their A/B display mapping. Back up the whole `data/` folder.

Run the isolated standard-library regression suite with `python -B -m unittest discover -s tests -v`. A headless Chrome pass also completed Single Audio and Pairwise Tie submission through the normal UI with test-only temporary data. These checks establish software behavior only; a real human pilot and study are still required for empirical validation.

## 12. Current protocol change — 2026-11-25

The project owner narrowed active collection to **Single Audio only**, superseding the historical Pairwise and six-score instructions above. Each completed Single Audio item requires one `text_accuracy` (`no_error`, `has_error`, `unsure`), one or more content-error types when `has_error`, and five independent integer 1–5 scores: `pronunciation`, `intonation`, `pacing`, `audio_quality`, `naturalness`. `expressiveness` is no longer collected. `naturalness` is judged independently in context, not calculated from the other four scores. Optional `confidence` and `note`, and `invalid`/`skipped` with reasons, remain. The user supplied detailed 1–5 Vietnamese anchors for each criterion; the app guide presents them in full and the scoring page highlights 1/3/5.

The app guide now explains the whole system according to the signed-in role: admin manages samples, accounts, QC and exports; evaluator follows the five-stage Single Audio flow. The former “Quy tắc dữ liệu và bảo mật nhãn” guide section was removed. Pairwise creation, annotation, QC and export are no longer active. The owner authorized removal of previously submitted labels and historical pairs from the live local database; existing real audio samples and accounts remain. This is a protocol reset, not empirical validation. The owner's wording about “five other criteria” and a high expressiveness score conflicts with the five-field list; the implemented schema follows the explicit five fields and describes naturalness relative to the **four** other fields.

## 13. Evaluator interaction update — 2026-11-25

The owner further simplified the active Single Audio UI to three stages: content accuracy, five sequential quality-rating substeps, and confirmation. Audio and target transcript appear together at the top; the reference-audio player is removed from the evaluator view, and the API no longer returns its URL to evaluators. The evaluator header, progress sidebar copy, and login-page workspace tag were removed. Content choices display as numbered 1/2/3; error types display as lettered a/b/c/d with hover/focus explanations. Keyboard controls select content/ratings with those keys, move forward/back through valid stages and substeps with arrows, use Tab for ordinary focus traversal, and toggle playback with Space outside text fields. Right arrow opens the next item only after submission; submitted labels remain immutable. The prior five-stage directions in historical sections above are superseded by this three-stage UI.

## 14. Compact evaluator layout — 2026-11-25

The three-stage progress controls, compact five-substep navigation and keyboard reminder now occupy a right-side panel on desktop, leaving the audio and transcript in the main column. Style instructions remain in source metadata but are not shown to evaluators or returned by the evaluator queue API. Accuracy choices use a horizontal row on wide screens, and confirmation divides review and optional fields into two columns. Each rating substep shows five selectable rows in descending order, 5 to 1, with the full project-provided description for that exact score beside its number. Optional confidence choices are numbered 1/2/3 and selectable with those keys on confirmation. Enter submits a completed form from confirmation when required fields are present; text fields and other action buttons retain their native Enter behavior. The main grid item is anchored to the top of its parent container; child controls retain their previous internal alignment. The layout collapses to a single column on narrower screens. These presentation changes leave the Single Audio label schema and stored data unchanged.

## 15. Standard sample manifest — 2026-11-25

The admin download button now serves the repository's `manifest_template.json` as its single source of truth. The template contains one unfilled Single Audio sample with all supported source fields: required `sample_id`, `target_text`, `audio_url`, and an explicit `phase` choice, plus optional style instruction, reference audio URL, and private metadata. The blank template cannot be imported until real values are supplied; it contains no audio or human annotation data. The admin-only download route and transactional import do not create Pairwise items or labels.
