# Aider source patches

Patches applied to `Aider-AI/aider` for native (non-Docker) execution against a local Ollama instance.
None modify Aider's scaffold, prompts, retry logic, or edit-parsing. See `docs/benchmark-baseline-aider.md` Appendix A for full context.

## Reproducing the benchmark setup

```bash
# from benchmarks/baseline_aider/
git clone https://github.com/Aider-AI/aider.git aider-src
git clone https://github.com/Aider-AI/polyglot-benchmark.git

# pin to the commit these patches were built against
cd aider-src
git checkout "$(cat ../aider-patches/aider-src-base-commit.txt)"
git apply ../aider-patches/001-benchmark-cap-and-paths.patch
git apply ../aider-patches/002-npm-test-env-var.patch
cd ..

# set up isolated Python 3.12 venv
python3.12 -m venv venv
./venv/bin/pip install --upgrade pip setuptools wheel
./venv/bin/pip install aider-chat typer pandas lox python-dotenv GitPython importlib_resources matplotlib imgcat

# preinstall shared node_modules
mkdir -p npm-install
cp polyglot-benchmark/javascript/exercises/practice/alphametics/package.json npm-install/
(cd npm-install && npm install)

# build sampling and phase trees
python3 sample_exercises.py
python3 build_phase_trees.py

# run
./run_baseline.sh
```

## Patch summary

### 001-benchmark-cap-and-paths.patch

- Adds a `PerExerciseTimeout(BaseException)` + SIGALRM-based wall-clock cap inside `run_test()` with default 3600s (overridable via `AIDER_PER_EXERCISE_CAP_SECONDS`). On fire, writes a clean failed `.aider.results.json` with `exceeded_wall_cap: true`.
- Changes `TEST_COMMANDS[".js"]` and `TEST_COMMANDS[".cpp"]` in `run_unit_tests()` from hardcoded Docker paths (`/aider/benchmark/npm-test.sh`) to paths resolved relative to `benchmark.py`'s own directory.

### 002-npm-test-env-var.patch

- Replaces hardcoded `/npm-install/` in `npm-test.sh` with an `NPM_INSTALL` env var (default `/npm-install` for Docker compatibility).
