# Evidence-gated revocation of completion records

Code for the paper *When to Revoke Completion: Evidence-Gated Completion Records for Multi-Step Robot
Manipulation under Unreliable Goal Checks* (manuscript under review).

A multi-step manipulation controller has to decide, after every goal check, whether a goal it has already
completed still holds. If it trusts every negative report, a single false alarm makes it undo finished work;
if it ignores negative reports, it misses goals that were actually undone. The paper compares completion-record
rules under controlled observation errors in a Unity/PhysX pick-and-place simulation and recommends
*evidence-gated revocation*: revoke a completed goal only after n* consecutive reports that are not CONSISTENT,
and readmit it only through a new accepted placement.

This repository contains the controller, the completion rules, the Unity scene scripts, the experiment
runners for four pre-registered studies (C, D, E, F), the model-based predictions, the vision-language-model
(VLM) goal-check calibration, and the scripts that produce the paper's figures and numbers.
The trial data are archived separately (see [Data](#data)).

## Repository layout

```
revision_experiments/
  v7/                     controller core: FSM, contracts, transport (TCP/JSON-RPC to Unity), completion memory
    UnityRevision/        Unity 2020.3 project: scene, C# robot server, scorer, fault injection, batch entry points
  v10_studyC/             Study C: commit-only vs revocable vs memoryless under synthetic watchdog errors
    prediction/           stochastic world model and pre-run predictions for Study C
  v11_belief/             Studies D, E, F: belief rule, evidence-gated revocation, persistent errors
    prediction_D|E|F/     pre-run predictions for Studies D, E and F
    analysis_cascade/     post-hoc analyses (false-revocation cascades, Proposition 3 check, sensitivity model)
  v12_vlm_calibration/    error structure of a VLM goal check (frame capture, queries, analysis)
paper/
  analysis/               figure and number scripts for the paper
docs/
  STUDIES.md              design, hypotheses and amendments of each study
  THIRD_PARTY.md          Unity assets that are required but not redistributed
```

The folder names `v7`, `v10_studyC`, `v11_belief` and `v12_vlm_calibration` are kept from the original
experiment tree because the scripts locate each other through these relative paths.

## Requirements

- Python 3.10 or later. The controller, runners and offline tests use only the standard library;
  the figure scripts need NumPy and Matplotlib (`pip install -r requirements.txt`).
- Unity 2020.3.49f1 (only for running trials in simulation; the offline tests do not need Unity).
- The third-party scene assets listed in [docs/THIRD_PARTY.md](docs/THIRD_PARTY.md).
- For the VLM calibration only: a DashScope API key for `qwen3-vl-plus`.

## Offline tests (no Unity)

Each study ships a self-test that runs the real control code against a stochastic stand-in for the
simulator, replays the frozen analysis on a full-size dry run, and checks the generated scripts.

```bash
cd revision_experiments/v7 && python -m unittest test_completion_memory test_contracts
cd ../v10_studyC && python test_offline.py
cd ../v11_belief && python test_v11.py && python test_d.py && python test_e.py && python test_f.py
cd ../v12_vlm_calibration && python test_capture.py
```

All results printed by these tests come from the model world and are not experimental data.

## Running the studies in Unity

1. Install Unity 2020.3.49f1 and add the assets in [docs/THIRD_PARTY.md](docs/THIRD_PARTY.md) to
   `revision_experiments/v7/UnityRevision/Assets/`. Open the project once in the editor so that it imports.
2. Point the runners at the editor executable:

   ```powershell
   $env:UNITY_EDITOR = "C:\Program Files\Unity\Hub\Editor\2020.3.49f1\Editor\Unity.exe"
   ```

3. Each runner has a `freeze` step that records SHA-256 digests of the code, manifest and schedule before
   the first trial, and refuses to run if any of them changes afterwards. Create your own registration
   first, then run the precheck and the formal run. For Study F:

   ```powershell
   cd revision_experiments\v11_belief
   python f_runner.py freeze
   python f_manager.py --precheck
   python f_manager.py --expected-completed 0
   ```

   `run_studyE.ps1` and `run_studyF.ps1` chain the self-test, precheck and formal run. Study C uses
   `v10_studyC/runner.py` and `v10_studyC/manager.py` in the same way. The manager starts Unity in batch mode,
   runs the trials in segments, and writes sealed per-trial records to `results/` and progress to `execution/`.
   Creating a file named `STOP_AFTER_SEGMENT` in the study folder stops the run cleanly at the next segment
   boundary; the run resumes from the last sealed trial.

The managers keep Windows awake during a run; the studies were run on Windows. The offline tests run on Linux,
macOS and Windows.

## VLM goal-check calibration

```powershell
$env:DASHSCOPE_API_KEY = "<your key>"
cd revision_experiments\v12_vlm_calibration
.\run_vlm_calibration.ps1
```

The key is read from the environment only; it is never printed or written to disk. Frame capture starts Unity
with graphics enabled, because cameras do not render in `-nographics` mode. Answers are cached in
`answers.jsonl`, so an interrupted query step resumes where it stopped. `vlm_error_structure.json` is the
summary reported in the paper.

## Figures and numbers

With the trial data in place (see below):

```bash
cd paper/analysis
python rate_data.py
python fig_studyC.py && python fig_studyD.py && python fig_studyE.py && python fig_rate.py && python fig_timeline.py && python fig_setup.py
python paper_numbers.py
```

The figures are written to `paper/figures/`.

## Data

The sealed trial records of Studies C–F (per-trial event logs, summaries, `trials.csv`, `inference.json`),
the prediction replicates, the captured VLM frames and answers, and the original registration files with their
SHA-256 digests are archived on Zenodo: [10.5281/zenodo.23903834](https://doi.org/10.5281/zenodo.23903834).
Download `evidence-gated-revocation-data.zip` and copy its `revision_experiments/` folder into the repository root;
it places each `results/` folder next to the runner that produced it.

The study protocols were frozen locally before each formal run; they are not entries in a public registry.
The archived registration files record the digests of the exact code that produced the data. The scripts in
this repository differ from those files only in comments, log messages, file names and configuration (paths,
environment variables), not in control logic, error injection or analysis; [docs/STUDIES.md](docs/STUDIES.md) lists the
amendments made during the studies.

## Citation

If you use this code, please cite the paper (citation details will be added on publication).

## License

The code in this repository is released under the MIT License (see [LICENSE](LICENSE)). Third-party assets
are not included and remain under their own licenses.
