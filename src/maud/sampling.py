# Copyright (C) 2019 Novo Nordisk Foundation Center for Biosustainability,
# Technical University of Denmark.
#
# This program is free software: you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation, either version 3 of the License, or
# (at your option) any later version.
#
# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU General Public License for more details.
#
# You should have received a copy of the GNU General Public License
# along with this program.  If not, see <https://www.gnu.org/licenses/>.

"""Code for sampling from a posterior distribution."""

import os
from copy import deepcopy
from itertools import product
from typing import Dict

import cmdstanpy
import numpy as np
import pandas as pd

from maud import io
from maud.data_model import KineticModel, MaudInput


HERE = os.path.dirname(os.path.abspath(__file__))
INCLUDE_PATH = ""
DEFAULT_PRIOR_LOC_UNBALANCED = 0.1
DEFAULT_PRIOR_SCALE_UNBALANCED = 2.0
DEFAULT_PRIOR_LOC_ENZYME = 0.1
DEFAULT_PRIOR_SCALE_ENZYME = 2.0
STAN_PROGRAM_RELATIVE_PATH = "inference_model.stan"


def get_full_stoichiometry(
    kinetic_model: KineticModel,
    enzyme_codes: Dict[str, int],
    metabolite_codes: Dict[str, int],
    reaction_codes: Dict[str, int],
    drain_codes: Dict[str, int],
):
    """Get full stoichiometric matrix for each isoenzyme.

    :param kinetic_model: A Kinetic Model object
    :param enzyme_codes: the codified enzyme codes
    :param metabolite_codes: the codified metabolite codes
    """
    S_enz = pd.DataFrame(0, index=enzyme_codes, columns=metabolite_codes)
    if drain_codes is not None:
        S_drain = pd.DataFrame(0, index=drain_codes, columns=metabolite_codes)
        S_complete = pd.DataFrame(
            0, index={**enzyme_codes, **drain_codes}, columns=metabolite_codes
        )
    else:
        S_complete = pd.DataFrame(0, index={**enzyme_codes}, columns=metabolite_codes)
    S_enz_to_flux_map = pd.DataFrame(0, index=reaction_codes, columns=enzyme_codes)
    for rxn_id, rxn in kinetic_model.reactions.items():
        for enz_id, _ in rxn.enzymes.items():
            for met, stoic in rxn.stoichiometry.items():
                S_enz_to_flux_map.loc[rxn_id, enz_id] = 1
                S_enz.loc[enz_id, met] = stoic
                S_complete.loc[enz_id, met] = stoic
    if any(drain_codes):
        for drain_id, drain in kinetic_model.drains.items():
            for met, stoic in drain.stoichiometry.items():
                S_drain.loc[drain_id, met] = stoic
                S_complete.loc[drain_id, met] = stoic
    else:
        S_drain = pd.DataFrame()
    return S_enz, S_enz_to_flux_map, S_complete, S_drain


def get_knockout_matrix(mi: MaudInput):
    """Get binary experiment, enzyme matrix, 1 if enyzme knocked out, 0 if not.

    :param mi: a MaudInput object
    """
    experiment_codes = mi.stan_codes.experiment_codes
    enzyme_codes = mi.stan_codes.enzyme_codes
    enzyme_knockout_matrix = pd.DataFrame(
        0, index=np.arange(len(experiment_codes)), columns=np.arange(len(enzyme_codes))
    )
    for exp in mi.experiments.experiments:
        if exp.knockouts:
            for enz in exp.knockouts:
                enzyme_knockout_matrix.loc[
                    experiment_codes[exp.id] - 1, enzyme_codes[enz] - 1
                ] = 1
    return enzyme_knockout_matrix


def get_drain_priors(mi: MaudInput):
    """Return an experiment x drain matrix of location and scale priors for drains."""
    drain_codes = mi.stan_codes.drain_codes
    experiment_codes = mi.stan_codes.experiment_codes
    drain_loc_prior = pd.DataFrame(index=experiment_codes, columns=drain_codes)
    drain_scale_prior = pd.DataFrame(index=experiment_codes, columns=drain_codes)
    for p in mi.priors.drain_priors:
        drain_loc_prior.loc[p.experiment_id, p.drain_id] = p.location
        drain_scale_prior.loc[p.experiment_id, p.drain_id] = p.scale
    return drain_loc_prior, drain_scale_prior


def get_km_lookup(km_priors, mic_codes, enzyme_codes):
    """Get a mics x enzymes matrix of km indexes. 0 means null."""
    out = pd.DataFrame(0, index=mic_codes.values(), columns=enzyme_codes.values())
    for i, row in km_priors.iterrows():
        mic_code = mic_codes[row["mic_id"]]
        enzyme_code = enzyme_codes[row["enzyme_id"]]
        out.loc[mic_code, enzyme_code] = i + 1
    return out


def sample(
    data_path: str,
    rel_tol: float,
    abs_tol: float,
    max_num_steps: int,
    likelihood: int,
    n_samples: int,
    n_warmup: int,
    n_chains: int,
    n_cores: int,
    timepoint: float,
    output_dir: str,
    threads_per_chain: int,
    save_warmup: bool,
) -> cmdstanpy.CmdStanMCMC:
    """Sample from a posterior distribution.

    :param data_path: A path to a toml file containing input data
    :param rel_tol: Sets ODE solver's rel_tol control parameter
    :param abs_tol: Sets ODE solver's abs_tol control parameter
    :param max_num_steps: Sets ODE solver's max_num_steps control parameter
    :param likelihood: Set to zero if you don't want the model to include information
    from experimental data.
    :param n_samples: Number of post-warmup samples
    :param n_warmup: Number of warmup samples
    :param n_chains: Number of MCMC chains to run
    :param n_cores: Number of cores to try and use
    :param time_step: Amount of time for the ode solver to simulate in order to compare
    initial state with evolved state
    :param: output_dir: Directory to save output
    :param: threads_per_chain: Number of threads per chain (default is 1)
    :param: save_warmup: whether to save warmup draws (default is True)
    """
    if threads_per_chain != 1:
        os.environ["STAN_NUM_THREADS"] = str(threads_per_chain)
    model_name = os.path.splitext(os.path.basename(data_path))[0]
    input_filepath = os.path.join(output_dir, f"input_data_{model_name}.json")
    init_filepath = os.path.join(output_dir, f"initial_values_{model_name}.json")
    mi = io.load_maud_input_from_toml(data_path)
    input_data = get_input_data(
        mi, abs_tol, rel_tol, max_num_steps, likelihood, timepoint
    )
    inits = get_initial_conditions(input_data, mi)
    cmdstanpy.utils.jsondump(input_filepath, input_data)
    cmdstanpy.utils.jsondump(init_filepath, inits)
    stan_program_filepath = os.path.join(HERE, STAN_PROGRAM_RELATIVE_PATH)
    include_path = os.path.join(HERE, INCLUDE_PATH)
    cpp_options = {"STAN_THREADS": True} if threads_per_chain != 1 else None
    model = cmdstanpy.CmdStanModel(
        stan_file=stan_program_filepath,
        stanc_options={"include_paths": [include_path]},
        cpp_options=cpp_options,
    )
    return model.sample(
        data=input_filepath,
        chains=n_chains,
        parallel_chains=n_cores,
        iter_sampling=n_samples,
        output_dir=output_dir,
        iter_warmup=n_warmup,
        max_treedepth=11,
        save_warmup=save_warmup,
        inits=init_filepath,
        show_progress=True,
        step_size=0.025,
        adapt_delta=0.99,
    )


def simulate_once(
    data_path: str,
    rel_tol: float,
    abs_tol: float,
    max_num_steps: float,
    timepoint: float,
    output_dir: str,
) -> cmdstanpy.CmdStanMCMC:
    """Sample from a posterior distribution.

    :param data_path: A path to a toml file containing input data
    :param rel_tol: Sets ODE solver's rel_tol control parameter
    :param abs_tol: Sets ODE solver's abs_tol control parameter
    :param max_num_steps: Sets ODE solver's max_num_steps control parameter
    from experimental data.
    initial state with evolved state
    :param: output_dir: Directory to save output
    """
    model_name = os.path.splitext(os.path.basename(data_path))[0]
    input_filepath = os.path.join(output_dir, f"input_data_{model_name}.json")
    init_filepath = os.path.join(output_dir, f"initial_values_{model_name}.json")
    mi = io.load_maud_input_from_toml(data_path)
    input_data = get_input_data(mi, abs_tol, rel_tol, max_num_steps, 1, timepoint)
    inits = get_initial_conditions(input_data, mi)
    cmdstanpy.utils.jsondump(input_filepath, input_data)
    cmdstanpy.utils.jsondump(init_filepath, inits)
    stan_program_filepath = os.path.join(HERE, STAN_PROGRAM_RELATIVE_PATH)
    include_path = os.path.join(HERE, INCLUDE_PATH)
    model = cmdstanpy.CmdStanModel(
        stan_file=stan_program_filepath, stanc_options={"include_paths": [include_path]}
    )
    return model.sample(
        data=input_filepath,
        chains=1,
        iter_sampling=1,
        output_dir=output_dir,
        inits=init_filepath,
        show_progress=True,
        fixed_param=True,
    )


def get_input_data(
    mi: MaudInput,
    abs_tol: float,
    rel_tol: float,
    max_num_steps: int,
    likelihood: int,
    timepoint: float,
) -> dict:
    """Put a MaudInput and some config numbers into a Stan-friendly dictionary.

    :param mi: a MaudInput object
    :param abs_tol: Sets ODE solver's abs_tol control parameter
    :param rel_tol: Sets ODE solver's rel_tol control parameter
    :param max_num_steps: Sets ODE solver's max_num_steps control parameter
    :param likelihood: Set to zero if you don't want the model to include information
    """
    metabolites = mi.kinetic_model.metabolites
    mics = mi.kinetic_model.mics
    reactions = mi.kinetic_model.reactions
    reaction_codes = mi.stan_codes.reaction_codes
    drain_codes = mi.stan_codes.drain_codes
    enzyme_codes = mi.stan_codes.enzyme_codes
    experiment_codes = mi.stan_codes.experiment_codes
    met_codes = mi.stan_codes.metabolite_codes
    mic_codes = mi.stan_codes.mic_codes
    balanced_mic_codes = mi.stan_codes.balanced_mic_codes
    unbalanced_mic_codes = mi.stan_codes.unbalanced_mic_codes
    mic_to_met = {
        mic_codes[mic.id]: met_codes[mic.metabolite_id] for mic in mics.values()
    }
    enzymes = {k: v for r in reactions.values() for k, v in r.enzymes.items()}
    water_stoichiometry = [
        r.water_stoichiometry for r in reactions.values() for e in r.enzymes.items()
    ]
    (enzyme_stoic, stoic_map_to_flux, full_stoic, drain_stoic) = get_full_stoichiometry(
        mi.kinetic_model, enzyme_codes, mic_codes, reaction_codes, drain_codes
    )
    subunits = (
        pd.DataFrame(
            {
                "enzyme_id": [e.id for e in enzymes.values()],
                "subunits": [e.subunits for e in enzymes.values()],
                "index": [enzyme_codes[e.id] for e in enzymes.values()],
            }
        )
        .sort_values(by="index")
        .reset_index(drop=True)
    )

    # priors
    prior_loc_drain, prior_scale_drain = get_drain_priors(mi)
    prior_dfs = {
        prior_type: pd.DataFrame(map(lambda p: p.__dict__, priors))
        for prior_type, priors in mi.priors.__dict__.items()
    }
    prior_dfs["formation_energy_priors"] = (
        prior_dfs["formation_energy_priors"]
        .assign(stan_code=lambda df: df["metabolite_id"].map(met_codes))
        .sort_values("stan_code")
    )
    n_modifier = {}
    for df_name, param_type in zip(
        [
            "inhibition_constant_priors",
            "tense_dissociation_constant_priors",
            "relaxed_dissociation_constant_priors",
        ],
        ["ki", "diss_t", "diss_r"],
    ):
        df = prior_dfs[df_name]
        df["mic_code"] = df["mic_id"].map(mic_codes)
        df["enzyme_code"] = df["enzyme_id"].map(enzyme_codes)
        df.sort_values("enzyme_code", inplace=True)
        n_modifier[param_type] = (
            df.groupby("enzyme_code")
            .size()
            .reindex(enzyme_codes.values())
            .fillna(0)
            .astype(int)
            .tolist()
        )
    prior_loc_unb = pd.DataFrame(
        DEFAULT_PRIOR_LOC_UNBALANCED,
        index=experiment_codes,
        columns=unbalanced_mic_codes,
    )
    prior_scale_unb = pd.DataFrame(
        DEFAULT_PRIOR_SCALE_UNBALANCED,
        index=experiment_codes,
        columns=unbalanced_mic_codes,
    )
    prior_loc_enzyme = pd.DataFrame(
        DEFAULT_PRIOR_LOC_ENZYME, index=experiment_codes, columns=enzyme_codes
    )
    prior_scale_enzyme = pd.DataFrame(
        DEFAULT_PRIOR_SCALE_ENZYME, index=experiment_codes, columns=enzyme_codes
    )
    conc_init = pd.DataFrame(
        0.01, index=experiment_codes.values(), columns=mic_codes.values()
    )
    enz_conc_init = pd.DataFrame(
        DEFAULT_PRIOR_LOC_ENZYME, index=experiment_codes.values(), columns=enzyme_codes.values()
        )
    # measurements
    mic_measurements, reaction_measurements, enzyme_measurements = (
        pd.DataFrame(
            [
                [exp.id, meas.target_id, meas.value, meas.uncertainty]
                for exp in mi.experiments.experiments
                for meas in exp.measurements[measurement_type].values()
            ],
            columns=["experiment_id", "target_id", "value", "uncertainty"],
        )
        for measurement_type in ["metabolite", "reaction", "enzyme"]
    )
    for _i, row in mic_measurements.iterrows():
        if row["target_id"] in balanced_mic_codes.keys():
            row_ix = experiment_codes[row["experiment_id"]]
            column_ix = mic_codes[row["target_id"]]
            conc_init.loc[row_ix, column_ix] = row["value"]
    for _i, row in enzyme_measurements.iterrows():
        row_ix = experiment_codes[row["experiment_id"]]
        column_ix = enzyme_codes[row["target_id"]]
        enz_conc_init.loc[row_ix, column_ix] = row["value"]
    for prior_unb in mi.priors.unbalanced_metabolite_priors:
        mic_id = mic_codes[prior_unb.mic_id]
        exp_id = experiment_codes[prior_unb.experiment_id]
        conc_init.loc[exp_id, mic_id] = prior_unb.location
    for prior_enz in mi.priors.enzyme_concentration_priors:
        enz_id = enzyme_codes[prior_enz.enzyme_id]
        exp_id = experiment_codes[prior_enz.experiment_id]
        enz_conc_init.loc[exp_id, enz_id] = prior_enz.location
    knockout_matrix = get_knockout_matrix(mi=mi)
    km_lookup = get_km_lookup(prior_dfs["km_priors"], mic_codes, enzyme_codes)
    for prior_unb in mi.priors.unbalanced_metabolite_priors:
        mic_id = prior_unb.mic_id
        exp_id = prior_unb.experiment_id
        prior_loc_unb.loc[exp_id, mic_id] = prior_unb.location
        prior_scale_unb.loc[exp_id, mic_id] = prior_unb.scale
    for prior_enz in mi.priors.enzyme_concentration_priors:
        enz_id = prior_enz.enzyme_id
        exp_id = prior_enz.experiment_id
        prior_loc_enzyme.loc[exp_id, enz_id] = prior_enz.location
        prior_scale_enzyme.loc[exp_id, enz_id] = prior_enz.scale
    return {
        "N_mic": len(mics),
        "N_unbalanced": len(unbalanced_mic_codes),
        "N_metabolite": len(metabolites),
        "N_km": len(prior_dfs["km_priors"]),
        "N_reaction": len(reactions),
        "N_enzyme": len(enzymes),
        "N_experiment": len(mi.experiments.experiments),
        "N_flux_measurement": len(reaction_measurements),
        "N_enzyme_measurement": len(enzyme_measurements),
        "N_conc_measurement": len(mic_measurements),
        "N_competitive_inhibitor": len(prior_dfs["inhibition_constant_priors"]),
        "N_allosteric_inhibitor": len(prior_dfs["tense_dissociation_constant_priors"]),
        "N_allosteric_activator": len(
            prior_dfs["relaxed_dissociation_constant_priors"]
        ),
        "N_allosteric_enzyme": len(prior_dfs["transfer_constant_priors"]),
        "N_drain": len(drain_codes) if drain_codes is not None else 0,
        "unbalanced_mic_ix": list(unbalanced_mic_codes.values()),
        "balanced_mic_ix": list(balanced_mic_codes.values()),
        "experiment_yconc": (
            mic_measurements["experiment_id"].map(experiment_codes).values
        ),
        "mic_ix_yconc": mic_measurements["target_id"].map(mic_codes).values,
        "yconc": mic_measurements["value"].values,
        "sigma_conc": mic_measurements["uncertainty"].values,
        "experiment_yflux": (
            reaction_measurements["experiment_id"].map(experiment_codes).values
        ),
        "reaction_yflux": (
            reaction_measurements["target_id"].map(reaction_codes).values
        ),
        "yflux": reaction_measurements["value"].values,
        "sigma_flux": reaction_measurements["uncertainty"].values,
        "experiment_yenz": (
            enzyme_measurements["experiment_id"].map(experiment_codes).values
        ),
        "enzyme_yenz": (enzyme_measurements["target_id"].map(enzyme_codes).values),
        "yenz": enzyme_measurements["value"].values,
        "sigma_enz": enzyme_measurements["uncertainty"].values,
        "prior_loc_formation_energy": prior_dfs["formation_energy_priors"][
            "location"
        ].values,
        "prior_scale_formation_energy": prior_dfs["formation_energy_priors"][
            "scale"
        ].values,
        "prior_loc_kcat": prior_dfs["kcat_priors"]["location"].values,
        "prior_scale_kcat": prior_dfs["kcat_priors"]["scale"].values,
        "prior_loc_km": prior_dfs["km_priors"]["location"].values,
        "prior_scale_km": prior_dfs["km_priors"]["scale"].values,
        "prior_loc_ki": prior_dfs["inhibition_constant_priors"]["location"].values,
        "prior_scale_ki": prior_dfs["inhibition_constant_priors"]["scale"].values,
        "prior_loc_diss_t": prior_dfs["tense_dissociation_constant_priors"][
            "location"
        ].values,
        "prior_scale_diss_t": prior_dfs["tense_dissociation_constant_priors"][
            "scale"
        ].values,
        "prior_loc_diss_r": prior_dfs["relaxed_dissociation_constant_priors"][
            "location"
        ].values,
        "prior_scale_diss_r": prior_dfs["relaxed_dissociation_constant_priors"][
            "scale"
        ].values,
        "prior_loc_tc": prior_dfs["transfer_constant_priors"]["location"].values,
        "prior_scale_tc": prior_dfs["transfer_constant_priors"]["scale"].values,
        "prior_loc_unbalanced": prior_loc_unb.values,
        "prior_scale_unbalanced": prior_scale_unb.values,
        "prior_loc_enzyme": prior_loc_enzyme.values,
        "prior_scale_enzyme": prior_scale_enzyme.values,
        "prior_loc_drain": prior_loc_drain.values.tolist(),
        "prior_scale_drain": prior_scale_drain.values.tolist(),
        "S_enz": enzyme_stoic.T.values,
        "S_drain": drain_stoic.T.values.tolist(),
        "S_full": full_stoic.T.values,
        "water_stoichiometry": water_stoichiometry,
        "mic_to_met": list(mic_to_met.values()),
        "S_to_flux_map": stoic_map_to_flux.values,
        "is_knockout": knockout_matrix.values,
        "km_lookup": km_lookup.values,
        "n_ci": n_modifier["ki"],
        "n_ai": n_modifier["diss_t"],
        "n_aa": n_modifier["diss_r"],
        "ci_ix": prior_dfs["inhibition_constant_priors"]["mic_code"].values,
        "ai_ix": prior_dfs["tense_dissociation_constant_priors"]["mic_code"].values,
        "aa_ix": prior_dfs["relaxed_dissociation_constant_priors"]["mic_code"].values,
        "subunits": subunits["subunits"].values,
        "conc_init": conc_init.values,
        "init_enzyme": enz_conc_init.values,
        "rel_tol": rel_tol,
        "abs_tol": abs_tol,
        "max_num_steps": max_num_steps,
        "LIKELIHOOD": likelihood,
        "timepoint": timepoint,
    }
def get_initial_conditions(input_data, mi):
    """Specify parameters' initial conditions."""
    return {
        "km": input_data["prior_loc_km"],
        "ki": input_data["prior_loc_ki"],
        "diss_t": input_data["prior_loc_diss_t"],
        "diss_r": input_data["prior_loc_diss_r"],
        "transfer_constant": input_data["prior_loc_tc"],
        "kcat": input_data["prior_loc_kcat"],
        "conc_unbalanced": input_data["prior_loc_unbalanced"],
        "enzyme": input_data["init_enzyme"],
        "formation_energy": input_data["prior_loc_formation_energy"],
        "drain": input_data["prior_loc_drain"],
    }
