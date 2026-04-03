Use this repository as the continuation point for the Ubuntu runtime-validation pass.

Context:

- The repository has already been statically aligned against `nudiscribe_build_plan.txt`.
- Backend Phases 1 to 5 are implemented in code.
- Phase 5 still needs real runtime verification on Ubuntu inside the correct venv with the installed speech libraries and model assets.
- `BUILD_PLAN_ALIGNMENT.md` contains the current plan-to-code mapping.
- `UBUNTU_HANDOFF_README.md` contains the current state, next steps, likely failure points, and definition of done.
- `backend/app/product_smoke_test.py` is the main validation entrypoint.

Your task:

1. Read `UBUNTU_HANDOFF_README.md`, `BUILD_PLAN_ALIGNMENT.md`, `.env.example`, `backend/app/runtime_validation.py`, `backend/app/product_smoke_test.py`, and `backend/app/tts_router.py`.
2. Activate and use the real Ubuntu venv for this project.
3. Run the static validation:
   `python backend/app/product_smoke_test.py --self-check --run-command-probes`
4. Compile the important backend files with `python -m py_compile`.
5. Start the backend from `backend/` with:
   `uvicorn app.main:app --reload`
6. Run the live smoke test:
   `python backend/app/product_smoke_test.py --base-url http://127.0.0.1:8000`
7. If you have a usable WAV file, also run:
   `python backend/app/product_smoke_test.py --base-url http://127.0.0.1:8000 --audio-file /absolute/path/to/sample.wav`
8. If anything fails, patch the smallest concrete runtime issue, rerun the relevant validation, and continue until Phase 5 is fully verified.
9. After successful validation, update `UBUNTU_HANDOFF_README.md` with:
   - what passed
   - what failed and was fixed
   - exact commands executed
   - any remaining known risks
10. Only after Phase 5 is fully verified, begin Phase 6 planning and implementation for persistence.

Constraints:

- Do not redesign the API shape unless a concrete runtime bug requires it.
- Keep AI4Bharat as the primary Hindi/Kannada TTS path.
- Do not count tone fallback as full TTS success.
- Only use `--allow-tone-fallback` for temporary debugging, never for the final validation result.
- Prefer direct, minimal fixes over architectural refactors.
