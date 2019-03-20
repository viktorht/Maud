import pandas as pd
from python_functions import StanModel_cache
from hardcoded_numbers import (EXAMPLE_SPECIES_INPUT,
                               EXAMPLE_KNOWN_REALS,
                               EXAMPLE_KINETIC_PARAMETER_INPUT)

METABOLITE_MEASUREMENT_FILE = 'data/millard_steady_state_metabolite_measurements.csv'
FLUX_MEASUREMENT_FILE = 'data/millard_steady_state_flux_measurements.csv'
DERIVED_METABOLITE_NAMES = ['PYR', 'eiP', 'hprP', 'NAD', 'AMP', 'BPG', 'eiiaP',
                          'GLCx', 'eiicbP', 'MgADP', 'MgATP', 'MgFDP']
FLUX_NAMES = ['PGI', 'PFK', 'FBA', 'TPI', 'GDH', 'PGK', 'GPM', 'ENO', 'PYK',
              'FBP', 'PPS', 'PTS_0', 'PTS_1', 'PTS_2', 'PTS_3', 'PTS_4',
              'ATP_MAINTENANCE', 'XCH_RMM']
REL_TOL = 1e-13
F_TOL = 1e-6
MAX_STEPS = int(1e9)
LIKELIHOOD = 1


if __name__ == '__main__':
    ode_metabolite_names = list(EXAMPLE_SPECIES_INPUT.keys())
    model = StanModel_cache(file='model.stan')

    metabolites, fluxes = (
        pd.read_csv(handle, sep='\t', index_col=0)
        .set_index(index_col)
        .reindex(names)
        for handle, index_col, names in zip(
                [METABOLITE_MEASUREMENT_FILE, FLUX_MEASUREMENT_FILE],
                ['metabolite', 'flux'],
                [list(EXAMPLE_SPECIES_INPUT) + DERIVED_METABOLITE_NAMES, FLUX_NAMES]
        ))
    fluxes['ix'] = range(1, len(fluxes) + 1)
    metabolites_derived = (metabolites
                        .reindex([i for i in DERIVED_METABOLITE_NAMES if i in metabolites.index])
                        .assign(ix=lambda df: range(1, len(df) + 1)))
    metabolites_ode = (metabolites
                    .reindex([i for i in list(EXAMPLE_SPECIES_INPUT.keys())
                                if i in metabolites.index])
                    .assign(ix=lambda df: range(1, len(df) + 1)))
    metabolites_derived_measured, metabolites_ode_measured, fluxes_measured = (
        df.dropna(subset=['exp value'])
        for df in [metabolites_derived, metabolites_ode, fluxes]
    )
    data = {
        'N_ode': len(metabolites_ode),
        'N_derived': len(metabolites_derived),
        'N_flux': len(fluxes),
        'M_ode': len(metabolites_ode_measured),
        'M_derived': len(metabolites_derived_measured),
        'M_flux': len(fluxes_measured),
        'N_known_real': len(EXAMPLE_KNOWN_REALS.keys()),
        'P': len(EXAMPLE_KINETIC_PARAMETER_INPUT),
        'measurement_ix_flux': fluxes_measured['ix'],
        'measurement_flux': fluxes_measured['exp value'],
        'measurement_ix_ode': metabolites_ode_measured['ix'],
        'measurement_ode': metabolites_ode_measured['exp value'],
        'measurement_ix_derived': metabolites_derived_measured['ix'],
        'measurement_derived': metabolites_derived_measured['exp value'],
        'prior_location': list(EXAMPLE_KINETIC_PARAMETER_INPUT.values()),
        'prior_scale': [i / 5 for i in EXAMPLE_KINETIC_PARAMETER_INPUT.values()],
        'sigma_metabolite': 0.2,
        'sigma_flux': 0.2,
        'known_reals': list(EXAMPLE_KNOWN_REALS.values()),
        'initial_guess': list(EXAMPLE_SPECIES_INPUT.values()),
        'rel_tol': REL_TOL,
        'f_tol': F_TOL,
        'max_steps': MAX_STEPS,
        'LIKELIHOOD': LIKELIHOOD
    }
    fit = model.sampling(
        data=data,
        init=[{'kinetic_parameters': list(EXAMPLE_KINETIC_PARAMETER_INPUT.values())}] * 4
    )