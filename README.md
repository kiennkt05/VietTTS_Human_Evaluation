# VietTTS — Human Annotation Workspace

An operational web app for **real human annotation of Vietnamese TTS**, replacing the earlier 10-example interactive walkthrough. **Light theme is the default**; a dark-theme toggle is available. The workspace starts with **no fictitious samples or labels**.

The app uses Python's standard library only (no pip dependencies), an SQLite database, locally uploaded audio files, account-based access, and a shared web URL for annotators.

## Quick start — Windows, Linux, macOS

1. Clone or extract this repository into a writable folder and install **Python 3.10 or later**. Check with `python --version` on Windows or `python3 --version` on Linux/macOS. No pip install is needed.
2. Start the server on this computer:

   | OS | Local only | Trusted LAN |
   | --- | --- | --- |
   | Windows | Double-click `start_windows.bat` (or `start_windows_local_only.bat`) | Double-click `start_windows_lan.bat` |
   | Linux | `./start_local.sh` | `./start_lan.sh` |
   | macOS | Double-click `start_macos.command` or run `./start_local.sh` | Double-click `start_macos_lan.command` or run `./start_lan.sh` |

   On Linux/macOS, `sh start_local.sh` and `sh start_lan.sh` also work if executable permissions were lost when extracting a ZIP. On Windows, the scripts find either `python` or the `py -3` launcher. Each launcher starts in the repository folder. To use another port from a terminal, append `--port PORT` to the command.
3. On first launch, save the automatically generated **admin password** printed in the terminal. Open **http://localhost:8765** in a browser and sign in as `admin`. Subsequent launches reuse the same database and do not print the password.
4. For other annotators on the same trusted network, stop the local-only server and use the LAN launcher. Find the host machine's LAN IPv4 address (for example, with `ipconfig` on Windows or network settings on Linux/macOS) and share `http://YOUR_LAN_IP:8765`. Allow the port through the host firewall only for the trusted network. Do **not** expose this plain HTTP service to the public internet.

**Set an admin password in advance (optional):** before the first launch, set `TTS_ADMIN_PASSWORD` to at least eight characters in the same terminal. In PowerShell: `$env:TTS_ADMIN_PASSWORD="your-strong-password"`; in a POSIX shell: `export TTS_ADMIN_PASSWORD='your-strong-password'`. Then run the appropriate launcher. The password is saved as a salted PBKDF2 hash, not in plaintext.

## Operator workflow

1. Log in as `admin` and open **Bộ dữ liệu**.
2. Upload **real audio** and its **verbatim target text** to create a sample with a unique `sample_id`. Optionally provide a style instruction, reference audio and private source metadata (e.g. model/seed).
3. Create a pair (`pair_id`, `sample_a_id`, `sample_b_id`) from two existing audio samples. Their target texts must match. Pairs with differing style/reference conditions receive a warning; the evaluator page does not show a misleading shared style/reference in that case. A pair has its own phase. If either source sample has a different phase, the operator receives a warning and QC lists the pair for review.
4. Distinguish `pilot` and `main` using the phase selector for each sample/pair.
5. Open **Tài khoản** and create a separate evaluator account per human annotator. Default target: **3 distinct completed human labels per item**. The operator can adjust this target.
6. Have each evaluator log in separately. They select **Single Audio** or **Pairwise** and the `pilot`/`main` phase. They do not see other people's labels or source model/seed/WER/CER.
7. Check **Quality control**, first for Pilot and then main data. QC shows counts, score means and distributions, text accuracy and error-type counts, agreement, Pairwise A/B/Tie counts and rates, preference strength, and outcomes by displayed position and swap state. Phase-mismatched pairs are flagged. These are descriptive counts, **not** a positional-bias test, pass/fail decision, or ground-truth label.
8. Open **Xuất dữ liệu** to export raw human annotations (JSONL and CSV) and source metadata (JSONL). Back up `data/` regularly.

## Evaluator workflow (the five on-screen stages)

**Single Audio**
1. Read the target transcript and any shared style/reference instructions.
2. Play and listen to the actual audio.
3. Select exactly one `no_error`, `has_error`, or `unsure`. For `has_error`, choose one or more of `omission`, `insertion`, `substitution`, `repetition`.
4. Score each axis separately on an **integer 1–5** scale: `pronunciation`, `intonation`, `pacing`, `expressiveness`, `audio_quality`, `naturalness`.
5. Optionally set `confidence` and `note`, review and submit. `naturalness` is an independent rating, **not** a calculated average.

**Pairwise**
1. Read the common target text and shared style/reference (when supplied and aligned).
2. Listen to both **Audio A** and **Audio B** in the order presented.
3. Mark `text_accuracy_a` and `text_accuracy_b` independently (`no_error`, `has_error`, `unsure`).
4. Choose **one** naturalness preference from A+2, A+1, Tie, B+1, B+2. Optionally add `preference_reasons`.
5. Optionally add `confidence` and `note`, review and submit. **No six-axis 1–5 ratings in Pairwise.**

The order of the pair is randomized consistently for each evaluator/pair (derived from a server-side secret). Randomization does not guarantee exact position balance in a small sample. On submission, the server converts the preferences and accuracy judgments to **canonical A/B** and retains `display_swapped` plus `preference_display` for audit. A submitted item can't be overwritten by the evaluator. Evaluator API responses use an opaque per-user task token instead of source sample/pair IDs; original IDs remain in operator exports.

**Invalid / Skipped:** Both are available for either workflow, distinct from a valid Tie and requiring a reason. **Invalid is for unreadable/corrupt audio or incorrect dataset configuration, not for content errors**. Content errors stay as `has_error` labels. Skipped doesn't count toward the target of 3 completed annotations.

Drafts are saved to the server between steps and on edits, allowing page reload or switching workflows. Submission time and an approximate elapsed duration since first opening the item are recorded.

## Files and import format

The Git repository contains application code and documentation only. Local study records, uploaded media, and the server secret live in `data/`, which is excluded from Git. Back up and transfer that folder separately when moving a study between trusted machines; cloning the repository starts with an empty dataset.

- `samples.jsonl`: audio source metadata, target text, phase, optional style/reference and operator-only private metadata.
- `pairs.jsonl`: `pair_id`, canonical `sample_a_id` and `sample_b_id`, phase.
- `single_annotations.jsonl` and `.csv`: **individual** Single Audio records, including username and per-axis scores.
- `pair_annotations.jsonl` and `.csv`: **individual** Pairwise records, including username, canonical preference, text accuracy A/B, `display_swapped`, reasons, confidence and notes.
- The server database is `data/annotations.db`, uploaded audio files are in `data/media/`, and the A/B mapping secret is `data/.server_secret`. All are created automatically on first launch; **back up the entire `data/` folder together**. The server refuses to open an existing database without its secret, because doing so could change the display order for unfinished Pairwise drafts.

For bulk import, the operator's **Manifest JSON** accepts the structure below; replace the empty lists with records from your real dataset. The UI also provides a blank download template.

```json
{
  "samples": [],
  "pairs": []
}
```

The accepted sample fields are `sample_id` (required), `target_text` (required), `audio_url` (required, either a previously uploaded `/media/...` path or an HTTPS URL), `phase` (`pilot` or `main`, default `main`), `style_instruction`, `reference_audio_url`, and `private_metadata` (JSON object hidden from evaluators). The accepted pair fields are `pair_id`, `sample_a_id`, `sample_b_id`, and `phase`. The server validates that A/B have the same target transcript. One manifest import is transactional: a failure prevents half-imported records.

Audio upload accepts `.wav`, `.mp3`, `.m4a`, `.ogg`, `.webm`, `.flac`, `.aac`, `.opus` files up to **60 MB per file**. The server checks a format header for the selected extension; this does not prove that a complete file decodes or that speech matches its transcript. Local `/media/` paths in a manifest must refer to existing uploaded files. Browser playback support may vary by codec. JSON manifest submissions are limited to **4 MB per request**; larger datasets can be imported in batches. JSONL/CSV are **exports**; bulk import is JSON manifest. Annotation CSV exports have stable columns, including when no annotations exist.

## Methodological scope

- Source methodology: **GSRM**, **SpeechJudge**, and **UniSRM**, adapted for the project's two distinct workflows.
- Pilot statistical outputs are descriptive only; the source project documentation does not specify an acceptance threshold or a unique required agreement coefficient.
- Exported data may be used for downstream **TTS benchmarking, pointwise / preference reward-model training, and reranking**, but **the app itself does not train a reward model, run TTS synthesis, or automatically choose a final ground-truth label**.
- Every evaluator's annotations are saved separately. The site is an annotation tool, not a replacement for validation of human ratings or model evaluations.

## Software checks

Run `python -B -m unittest discover -s tests -v` on Windows or `python3 -B -m unittest discover -s tests -v` on Linux/macOS from this folder. The checks use a temporary database and audio fixture; they do not write labels to the project `data/` directory. They cover input validation, draft resume, independent statuses, randomized-display normalization, phase warnings, QC, access restrictions, and exports. GitHub Actions runs these checks on Windows, Linux, and macOS with supported Python versions. A real annotator pilot remains necessary to evaluate the research workflow and rating reliability.

## Security and deployment limitations

The app provides password hashing, HTTP-only session cookies, role-restricted endpoints, and protects uploaded audio behind authentication. Source metadata such as model ID, seed, and WER/CER is not sent in evaluator responses. Use opaque sample and pair IDs in source data, and prefer locally uploaded media when strict blinding matters: external HTTPS URLs and transcript/style text are visible to the evaluator and can themselves reveal provenance.

**This is intended for a controlled project machine or trusted LAN only.** The included Python server is not a hardened public service and does **not** provide TLS/HTTPS, password recovery, account lockout, audit retention controls, or formal privacy compliance. To deploy to internet users, put it behind a properly configured authenticated HTTPS service, add production-grade account management, conduct a security review, and establish data governance. A local manifest with a revealing URL or target text can still expose sensitive information to an evaluator. Do not embed model identities into evaluator-visible filenames, URLs, or text if blinding is required.

## Troubleshooting

- **No items available:** check that the admin created items in the selected `pilot` or `main` phase and that there are fewer than the target number of submitted labels; evaluators never receive the same completed item twice.
- **Audio won't play:** check uploaded file/codec and browser support; if objectively unplayable, select **Invalid** and describe it.
- **Forgot admin password:** this version intentionally has no in-browser reset. Preserve the original first-run password in a password manager. Resetting users by editing the SQLite database directly is unsupported and error-prone.
- **Multiple computers:** all annotators must access the *same running server*, not independent local copies of the folder; otherwise independent SQLite files won't aggregate.
- **Closing the terminal:** shuts down the app. Restart with the appropriate launcher to continue; existing data is preserved.
