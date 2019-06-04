import arviz
from matplotlib import pyplot as plt
import numpy as np
import os
import pandas as pd
from python_modules import enzymekat_data

RELATIVE_PATHS = {
    'toml_file': '../data/in/yeast_data.toml',
    'plots_folder': '../data/out',
    'csv_output': '../data/out/model_output_yeast.csv'
}

def plot_marginals(infd, variable, credible_interval=0, bins=30, png_location=None):
    plt.close('all')
    axes = arviz.plot_posterior(
        infd,
        kind='hist',
        var_names=[variable],
        credible_interval=credible_interval,
        bins=bins
    )
    if png_location is not None:
        plt.savefig(png_location)
    return axes
        

def plot_pairs(infd, var_names, coords=None, log_transform=True, png_location=None):
    plt.close('all')
    axes = arviz.plot_pair(infd, var_names, coords, divergences=True)
    if log_transform:
        for ax in axes.ravel():
            if ax.get_xticks()[1] >= 0:
                ax.semilogx()
            if ax.get_yticks()[1] >= 0:
                ax.semilogy()
    if png_location is not None:
        plt.savefig(png_location)
    return axes


def plot_pairs_for_reaction(infd, reaction, png_location=None):
    var_names = ['kinetic_parameters', 'thermodynamic_parameters']
    all_coords = infd.posterior.coords
    kp_names = list(filter(lambda i: reaction in i, all_coords['kinetic_parameter_names'].to_series()))
    tp_names = list(filter(lambda i: reaction in i, all_coords['thermodynamic_parameter_names'].to_series()))
    coords = {'kinetic_parameter_names': kp_names, 'thermodynamic_parameter_names': tp_names}
    axes = plot_pairs(infd, var_names, coords, log_transform=True, png_location=png_location)
    return axes


if __name__ == '__main__':

    here = os.path.dirname(os.path.abspath(__file__))
    toml_file = os.path.join(here, RELATIVE_PATHS['toml_file'])
    plots_folder = os.path.join(here, RELATIVE_PATHS['plots_folder'])
    csv_output = os.path.join(here, RELATIVE_PATHS['csv_output'])
    png_template = os.path.join(plots_folder, '{}.png')

    # load input data from toml file
    data = enzymekat_data.from_toml(toml_file)
    kinetic_parameter_names = (
        data.kinetic_parameters['reaction']
        .str.cat(data.kinetic_parameters['name'], sep='_')
        .tolist()
    )
    thermodynamic_parameter_names = data.thermodynamic_parameters['reaction'].tolist()
    metabolite_names = data.ode_metabolites['name'].tolist()
    measured_metabolite_names = data.ode_metabolites.dropna(subset=['measured_value'])['name'].tolist()
    flux_names = data.reactions['name'].tolist()

    # construct arviz InferenceData object
    infd = arviz.from_cmdstan(
        [csv_output],
        coords={
            'kinetic_parameter_names': kinetic_parameter_names,
            'thermodynamic_parameter_names': thermodynamic_parameter_names,
            'metabolite_names': metabolite_names,
            'measured_metabolite_names': measured_metabolite_names,
            'flux_names': flux_names
        },
        dims={
            'kinetic_parameters': ['kinetic_parameter_names'],
            'thermodynamic_parameters': ['thermodynamic_parameter_names'],
            'metabolite_concentration_hat': ['metabolite_names'],
            'measurement_pred': ['measured_metabolite_names'],
            'flux': ['flux_names']
        }
    )

    # Diagnostics
    n_samples = int(len(infd.sample_stats['diverging'].to_series()))
    n_diverging = int(infd.sample_stats['diverging'].to_series().sum())
    summary = arviz.summary(infd)
    if n_diverging > 0:
        print(f"Uh oh! {n_diverging} out of {n_samples} samples diverged.")
    print("Variables with the highest and lowest r_hat statistics:")
    print(pd.concat([summary.sort_values('r_hat', ascending=False).head(5),
                     summary.sort_values('r_hat', ascending=True).head(5)]))

    # Pair plots
    plot_pairs_for_reaction(
        infd,
        'ENO',
        png_location=png_template.format('pair_ENO')
    )
    for var_name in ['thermodynamic_parameters', 'measurement_pred', 'flux']:
        png_name = f'pair_{var_name}'
        plot_pairs(
            infd,
            var_names=[var_name],
            coords=None,
            png_location=png_template.format(png_name)
        )
    print('Pair plots done')

    # Posterior histograms
    for var_name in ['kinetic_parameters', 'measurement_pred', 'thermodynamic_parameters']:
        first_word = var_name.split('_')[0]
        png_name = f'posterior_{first_word}'
        plot_marginals(
            infd,
            var_name,
            png_location=png_template.format(png_name)
        )
    print('Histograms done')
