# Study C prediction (model simulation, not data)

`world_model.py` replaces Unity/PhysX with a small stochastic model, and `predict.py` runs the real Study C
control code (`kernel.run_trial`, completion rules, error injection, FSM, budgets) against it. The model was
calibrated on the earlier v8 three-goal trials:

- PICK failure 2.7% (30 of 1,110), PLACE failure 0.1% (1 of 1,000);
- primitive durations N(8.55, 2.0) s for PICK and N(6.95, 1.5) s for PLACE, so that a three-goal trial without
  faults takes about 53.5 s;
- 1% of accepted placements are reported INVALID by the watchdog although the scorer counts them as satisfied;
- 1% transient UNKNOWN reports for an object already in the same container after a PLACE.

Each replicate draws its own parameters around these values (`sample_params` in `predict.py`) to represent model
uncertainty. The world has no contact coupling between objects.

```bash
python predict.py --replicates 1 25 --out replicates
python summarize.py --src replicates   # writes predicted_metrics_v3.csv, predicted_success_rates_v3.csv, predicted_tests_v3.json
python compare_with_real.py      # needs ../results/formal_02 from the data archive
```

The Study D, E and F predictions (`../../v11_belief/prediction_*`) reuse this world model.
