# Studies

All studies use the same Unity/PhysX tabletop scene, the same pick-and-place controller (a finite-state
machine with verified preconditions, `v7/`), three goals per trial (red cube in bowl, green ball on yellow
plate, yellow cylinder in bowl), and an independent scorer that reads simulator state. The scorer decides
task success and is never an input to the controller. Each trial runs in one of two conditions:

- `no_fault`: no physical disturbance;
- `completed_shift`: one goal that the controller has already completed is physically undone during the trial,
  so a correct rule must revoke it and repair it.

The controller's goal check (the "watchdog") reports CONSISTENT, INVALID or UNKNOWN for each goal. In Studies
C–F its reports are corrupted by injected errors with a known rate and structure:

- `false_invalid`: a satisfied goal is reported INVALID;
- `false_consistent`: an unsatisfied goal is reported CONSISTENT;
- `independent` errors are drawn afresh at every report; `persistent` errors follow a two-state Markov chain
  (stay probability s = 0.8), so the same wrong report tends to repeat.

Every study fixes its manifest (layouts, schedule, endpoints, tests) and freezes the code by SHA-256 before the
first formal trial. Layout seeds of each study are new and disjoint from all earlier seeds. Trials are sealed one
by one (intent file before, seal after); a started trial is never re-run. Infrastructure failures are excluded
by registered rules and drop the whole seed pair from paired tests.

## Completion rules

| name in code | name in paper | behaviour |
|---|---|---|
| `commit_only` | commit-only | a placed goal stays completed regardless of later reports |
| `revocable` | revocable | revoke on the first report that is not CONSISTENT; readmit only by placement |
| `reactive` | memoryless | completion equals the current report |
| `belief`, `belief_a02/a10/a30` | belief rule | Bayesian completion belief with assumed error rates α̂ = β̂ = 0.02/0.10/0.30 |
| `debounce2` | evidence-gated revocation (n* = 2) | revoke after two consecutive reports that are not CONSISTENT; readmit only by placement |

## Study C (`v10_studyC`, protocol `AR-completion-noise-v1`)

3 rules (commit-only, revocable, memoryless) × 7 error levels (none; false_invalid or false_consistent at
2%, 5%, 10%; independent) × 2 conditions × 20 seeds = 840 trials.

Primary endpoints (revocable vs memoryless at 10%, Holm within 4): task success under false-consistent errors
(exact McNemar test paired by seed) and redundant re-picks of satisfied objects under false-invalid errors
(exact sign test), in each condition.

Amendment A1 (2026-10-29). The first formal run (`formal_01`) halted on trial 44. Before any further trial the
following changes were registered and the run was restarted as `formal_02` with the same manifest:

- S9: the completed-object displacement is applied only to an object that the scorer confirms is completed
  (an apparatus gate; the scorer remains invisible to the controller);
- S10: an RPC timeout caused by the trial wall-time budget counts as a budget stop, not an infrastructure fault;
- S11: the controller never dispatches to a target outside the tabletop workspace;
- S12: an action that never returns is a scored execution failure, not an infrastructure halt;
- at most three infrastructure exclusions are allowed; a fourth halts the run; Unity is restarted after an
  action timeout or an exclusion.

`formal_01` is excluded from all analyses. `make_kernel.py` regenerates `kernel.py` from the unmodified
`v7/ablation_runner.py` by the asserted substitutions S1–S12 recorded in `kernel_derivation.json`.

## Pilot (`v11_belief`, protocol `AR-belief-pilot-v1`)

60 development trials of the belief rule on five new layouts, run before Study D to check go/no-go criteria.
Excluded from all inference.

## Study D (`v11_belief`, protocol `AR-belief-D-v1`)

3 rules (belief with α̂ = 0.10, revocable, memoryless) × 2 conditions × 9 error levels × 20 seeds = 1,080 trials.
Error levels: none; false_invalid and false_consistent at 10% and 20%, each independent or persistent.

Primary (Holm within 4): belief vs the rule that each error type defeats (revocable under false-invalid,
memoryless under false-consistent) at the assumed rate 0.10 with independent errors, in each condition.
Key secondary: the same contrasts where the belief rule's assumptions fail (persistent errors, rate 0.20).

## Study E (`v11_belief`, protocol `AR-belief-E-v1`)

4 rules (belief with α̂ = 0.02, 0.10, 0.30; evidence-gated revocation with n* = 2) × 6 cells × 20 seeds = 480 trials.
Cells: false_invalid 20% (independent, persistent) × both conditions, and false_consistent 20% (independent,
persistent) × completed_shift.

Questions: does the assumed error rate set the number of reports needed to revoke, trading false revocations
against missed repairs as Proposition 3 predicts; and is the belief rule's benefit reproduced by a fixed
two-report rule. Primary tests are exact two-sided sign-flip permutation tests on per-seed success totals, Holm
corrected. The design was revised before freezing after a prediction-based power check.

## Study F (`v11_belief`, protocol `AR-egr-F-v1`)

4 rules (evidence-gated revocation, revocable, memoryless, belief α̂ = 0.10) × 8 cells × 20 seeds = 640 trials.
Cells: {false_invalid, false_consistent} at 20% × {independent, persistent} × both conditions. Kernel, rules and
audit are the frozen Study E files, used unchanged.

Primary (Holm within 2, exact two-sided sign-flip permutation test on per-seed totals over four cells):
H1 evidence-gated vs revocable under false-invalid reports; H2 evidence-gated vs memoryless under
false-consistent reports. Secondary: evidence-gated vs belief α̂ = 0.10 under each error type.

Amendment A0 (before the first trial). The offline self-test regenerated `f_runner.py` and `f_manager.py` in place;
on Windows the generator wrote CRLF line endings, which changed their digests and stopped the precheck. The
generator was changed to write LF bytes on every OS, the test now regenerates into a temporary folder, and the
study was re-frozen. No trial had been run.

The rule tested in Study F was chosen after Studies C–E. Study F therefore confirms its performance on new
layouts; it does not show that the choice was made in advance.

## Predictions

Before each formal run, the real control code was run against a stochastic stand-in for the simulator
(`v10_studyC/prediction/world_model.py`) to predict success counts and test outcomes. These are model
simulations, not data. `predict*.py` writes replicates; `summarize*.py` turns them into the tables
`predicted_success_*.csv` and `predicted_tests_*.json`; `compare_with_real.py` compares the Study C prediction
with the observed run.

## Post-hoc analyses (`v11_belief/analysis_cascade`)

Not pre-registered. `cascade_analysis.py` counts false revocations and the re-picks that follow them;
`prop3_transient.py` checks Proposition 3 per exposure with the post-placement transient;
`sensitivity_model.py` varies the trial budget and the hazard parameter in the model world.

## VLM calibration (`v12_vlm_calibration`)

Not a registered study. 20 trials of evidence-gated revocation without injected errors on 10 new layouts;
after every goal check the main and side camera images are captured with the scorer's per-goal ground truth.
`qwen3-vl-plus` is asked, for each frame, goal and view, whether the goal holds. `analyze_vlm.py` estimates
the error rates, their persistence across consecutive frames, the agreement between views, and the
false-revocation probability that Proposition 3 implies for each n*.
