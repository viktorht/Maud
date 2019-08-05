import pandas as pd
import toml
from typing import Dict, List
from functools import reduce


def expand_series_of_dicts(s):
    """get a dataframe from a series whose values are dictionaries"""
    return pd.DataFrame.from_records(s.values, index=s.index)



class EnzymeKatData():
    """Object with all the data that is needed to fit an enzymeKat model, namely:

      - Information about the experimental setup (measurement accuracy, time to
        steady state)
      - Information about kinetic parameters
      - Information about ode metabolites

    """
    def __init__(self,
                 constants: Dict,
                 experiments: Dict,
                 reactions: Dict,
                 unbalanced_mets: Dict):
        self.constants = constants
        self.experiments = experiments
        self.reactions = reactions
        self.unbalanced_metabolite = unbalanced_mets
        self.stoichiometry = self.get_stoichiometry()
        self.metabolite_codes = self.get_metabolite_codes()
        self.reaction_codes = self.get_reaction_codes()
        self.flux_measurements, self.concentration_measurements = self.get_measurements()
        self.known_reals = self.get_known_reals()
        self.parameters = self.get_parameters()

    def get_stoichiometry(self):
        S = (
            pd.DataFrame.from_records(self.reactions)
            .set_index('name')
            ['stoichiometry']
            .pipe(expand_series_of_dicts)
            .fillna(0)
            .astype(int)
        )
        S.index.name = 'reaction'
        S.columns.name = 'metabolite'
        return S

    def get_metabolite_codes(self):
        S = self.get_stoichiometry()
        return dict(zip(S.columns, range(1, len(S.columns) + 1)))

    def get_reaction_codes(self):
        S = self.get_stoichiometry()
        return dict(zip(S.index, range(1, len(S.index) + 1)))

    def get_measurements(self):
        metabolite_codes = self.get_metabolite_codes()
        reaction_codes = self.get_reaction_codes()
        measurements = pd.io.json.json_normalize(
            self.experiments,
            'measurements',
            meta=['label'],
            meta_prefix='experiment_'
        )
        measurements['experiment_code'] = measurements['experiment_label'].factorize()[0] + 1
        flux_measurements, conc_measurements = (
            measurements
            .query(f"type == '{t}'")
            .dropna(how='all', axis=1)
            .copy()
            .rename(columns={'label': t + '_label'})
            for t in ['flux', 'metabolite']
        )
        flux_measurements['reaction_code'] = flux_measurements['flux_label'].map(reaction_codes.get)
        conc_measurements['metabolite_code'] = conc_measurements['metabolite_label'].map(metabolite_codes.get)
        return flux_measurements, conc_measurements

    def get_known_reals(self):
        out = {}
        for e in self.experiments:
            conditions = {k: v for k, v in e.items() if type(v) in [float, int]}
            out[e['label']] = {**conditions, **self.constants}
        return pd.DataFrame.from_dict(out).assign(stan_code=lambda df: range(1, len(df) + 1))

    def get_parameters(self):
        reactions = self.reactions
        for r in reactions:  # json_normalize doesn't work with missing record path
            if 'parameters' not in r.keys():
                r['parameters'] = []
        pars = (
            pd.io.json.json_normalize(reactions,
                                      record_path='parameters',
                                      meta='name')
            .rename(columns={'name': 'reaction', 'label': 'parameter'})
            .assign(
                is_kinetic=lambda df: df['type'].eq('kinetic').astype(int),
                is_allosteric=lambda df: df['type'].eq('allosteric').astype(int),
                stan_code=lambda df: range(1, len(df) + 1)
            ))
        label_cols = (
            ['reaction', 'parameter', 'metabolite']
            if 'metabolite' in pars.columns
            else ['reaction', 'parameter']
        )
        pars['label'] = pars[label_cols].apply(lambda row: '_'.join(row.dropna().astype(str)), axis=1)
        return pars


def from_toml(path):
    t = toml.load(path)
    return EnzymeKatData(
        constants=t['constants'],
        experiments=t['experiment'],
        reactions=t['reaction'],
        unbalanced_mets=t['unbalanced_metabolites']
    )


def join_string_values(df):
    return df.apply(lambda x: '_'.join(x.dropna().astype(str)), axis=1)
