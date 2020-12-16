"""Test that simple simulation studies give expected output."""

import json
import os
from functools import reduce

import numpy as np
import pytest

from maud.analysis import load_infd
from maud.io import load_maud_input_from_toml
from maud.simulation_study import run_simulation_study


HERE = os.path.dirname(__file__)
DATA_PATH = reduce(os.path.join, [HERE, "..", "data"])
MAUD_PATH = reduce(os.path.join, [HERE, "..", "..", "src", "maud"])
SAMPLE_CONFIG = {
    "chains": 1,
    "iter_warmup": 50,
    "iter_sampling": 50,
    "show_progress": True,
    "max_treedepth": 11,
}
CASES = [
    ("linear.toml", "true_params_linear.json"),
]


@pytest.mark.parametrize("toml_file,truth_file", CASES)
def test_linear(toml_file, truth_file):
    """Test that the linear model works."""

    toml_path = os.path.join(DATA_PATH, toml_file)
    truth_path = os.path.join(DATA_PATH, truth_file)
    stan_path = os.path.join(MAUD_PATH, "inference_model.stan")
    with open(truth_path, "r") as f:
        true_values_in = json.load(f)
    mi_in = load_maud_input_from_toml(toml_path)
    study = run_simulation_study(stan_path, mi_in, true_values_in, SAMPLE_CONFIG)
    infd = load_infd(study.samples.runset.csv_files, study.mi)
    for param_name, param_vals in true_values_in.items():
        if any(param_vals):
            dimnames = [
                d for d in infd.posterior[param_name].dims if d not in ["chain", "draw"]
            ]
            q = (
                infd.posterior[param_name]
                .to_series()
                .unstack(dimnames)
                .quantile([0.025, 0.975])
                .T.assign(true=np.array(param_vals).ravel())
            )
            q.columns = ["low", "high", "true"]
            for i, row in q.iterrows():
                msg = (
                    f"True value for {param_name} outside 95% CI at coord {str(i)}!\n"
                    f"\tTrue value: {str(row['true'])}\n"
                    f"\t2.5% posterior quantile: {str(row['low'])}\n"
                    f"\t97.5% posterior quantile: {str(row['high'])}\n"
                )
                assert row["true"] >= row["low"] and row["true"] <= row["high"], msg
