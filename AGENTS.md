# Instructions for Codex in VietTTS Human Evaluation Workspace

Before changes, read `CODEX_HANDOFF_TTS.md` and `README.md` for the research requirements and current implementation. Treat `CODEX_HANDOFF_TTS.md` as the project's consolidated requirements and `README.md` as the implementation guide. If there is a conflict between documented requirements and implementation, explicitly report it; do not silently change the experimental label schema.

Maintain the two separate workflows: Single Audio = one text-accuracy state + optional content-error types + six independent integer 1–5 quality ratings; Pairwise = independent A/B text-accuracy states + one five-level relative naturalness preference + optional reasons. Tie differs from invalid/skipped. Keep original A/B IDs and randomized-display mapping. Preserve independent annotations from three separate users per item, pilot/main split, and evaluator blinding. Don't treat misread audio as invalid or naturalness as an automatic average.

Default light UI, Vietnamese annotator labels, local/LAN deployment only unless production hardening is explicitly requested. Never seed production data with example/fake human labels. Run checks/tests before reporting any change complete. Avoid claims of empirical validation without a real human study.
