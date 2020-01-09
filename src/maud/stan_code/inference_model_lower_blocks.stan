data {
  // dimensions
  int<lower=1> N_balanced;    // 'Balanced' metabolites must have constant concentration at steady state
  int<lower=1> N_unbalanced;  // 'Unbalanced' metabolites can have changing concentration at steady state
  int<lower=1> N_kinetic_parameters;
  int<lower=1> N_reaction;
  int<lower=1> N_enzyme;
  int<lower=1> N_experiment;
  int<lower=1> N_flux_measurement;
  int<lower=1> N_enzyme_measurement;
  int<lower=1> N_conc_measurement;
  int<lower=1> N_metabolite;  // NB metabolites in multiple compartments only count once here
  // measurements
  int<lower=1,upper=N_experiment> experiment_yconc[N_conc_measurement];
  int<lower=1,upper=N_balanced+N_unbalanced> metabolite_yconc[N_conc_measurement];
  vector[N_conc_measurement] yconc;
  vector<lower=0>[N_conc_measurement] sigma_conc;
  int<lower=1,upper=N_experiment> experiment_yflux[N_flux_measurement];
  int<lower=1,upper=N_reaction> reaction_yflux[N_flux_measurement];
  vector[N_flux_measurement] yflux;
  vector<lower=0>[N_flux_measurement] sigma_flux;
  int<lower=1,upper=N_experiment> experiment_yenz[N_enzyme_measurement];
  int<lower=1,upper=N_enzyme> enzyme_yenz[N_enzyme_measurement];
  vector[N_enzyme_measurement] yenz;
  vector<lower=0>[N_enzyme_measurement] sigma_enz;
  // hardcoded priors
  vector[N_metabolite] prior_loc_formation_energy;
  vector<lower=0>[N_metabolite] prior_scale_formation_energy;
  vector[N_kinetic_parameters] prior_loc_kinetic_parameters;
  vector<lower=0>[N_kinetic_parameters] prior_scale_kinetic_parameters;
  real prior_loc_unbalanced[N_unbalanced, N_experiment];
  real<lower=0> prior_scale_unbalanced[N_unbalanced, N_experiment];
  real prior_loc_enzyme[N_enzyme, N_experiment];
  real<lower=0> prior_scale_enzyme[N_enzyme, N_experiment];
  // network properties
  matrix[N_balanced+N_unbalanced, N_enzyme] stoichiometric_matrix;
  int<lower=1,upper=N_metabolite> compartment_metabolite_index[N_balanced+N_unbalanced];
  // configuration
  vector<lower=0>[N_balanced] as_guess;
  real rtol;
  real ftol;
  int steps;
  int<lower=0,upper=1> LIKELIHOOD;  // set to 0 for priors-only mode
  int<lower=0,upper=1> alg_solver; // set to 1 to use algebra_solver
}
transformed data {
  real xr[0];
  int xi[0];
  real minus_RT = - 0.008314 * 298.15;
}
parameters {
  vector[N_metabolite] formation_energy;
  vector<lower=0>[N_kinetic_parameters] kinetic_parameters;
  vector<lower=0>[N_unbalanced] unbalanced[N_experiment];
  vector<lower=0>[N_enzyme] enzyme_concentration[N_experiment];
}
transformed parameters {
  vector<lower=0>[N_balanced+N_unbalanced] conc[N_experiment];
  vector[N_reaction] flux[N_experiment];
  vector[N_enzyme] delta_g = stoichiometric_matrix' * formation_energy[compartment_metabolite_index];
  real initial_conc[N_unbalanced+N_balanced];
  real initial_time = 0;
  real final_time = 500;
  real d_conc_dt[N_unbalanced+N_balanced];
  for (e in 1:N_experiment){
    vector[N_enzyme] keq = exp(delta_g / minus_RT);
    vector[N_unbalanced+N_enzyme+N_enzyme+N_kinetic_parameters] theta;
    theta[1:N_unbalanced] = unbalanced[e];
    theta[N_unbalanced+1:N_unbalanced+N_enzyme] = enzyme_concentration[e];
    theta[N_unbalanced+N_enzyme+1:N_unbalanced+N_enzyme+N_enzyme] = keq;
    theta[N_unbalanced+N_enzyme+N_enzyme+1:] = kinetic_parameters;
    if (alg_solver == 1){
      conc[e, { {{-balanced_codes|join(',')-}} }] = algebra_solver(steady_state_function, as_guess, theta, xr, xi, rtol, ftol, steps);
      conc[e, { {{-unbalanced_codes|join(',')-}} }] = unbalanced[e];
    }

    else {
    initial_conc[{ {{-balanced_codes|join(',')-}} }] = to_array_1d(as_guess);
    initial_conc[{ {{-unbalanced_codes|join(',')-}} }] = to_array_1d(unbalanced[e]);
    conc[e, ] = to_vector(integrate_ode_bdf(
                                      ode_func,
                                      initial_conc,
                                      initial_time,
                                      rep_array(final_time, 1),
                                      to_array_1d(theta),
                                      xr,
                                      rep_array(0, 1),
                                      1e-8, 1e-12, 1e5)[1,]); 
    }
    d_conc_dt = ode_func(final_time, to_array_1d(conc[e]), to_array_1d(theta), xr, xi);
    flux[e] = get_fluxes(to_array_1d(conc[e]), to_array_1d(theta));
  }
}
model {
  kinetic_parameters ~ lognormal(log(prior_loc_kinetic_parameters), prior_scale_kinetic_parameters);
  formation_energy ~ normal(prior_loc_formation_energy, prior_scale_formation_energy);
  for (e in 1:N_experiment){
    unbalanced[e] ~ lognormal(log(prior_loc_unbalanced[,e]), prior_scale_unbalanced[,e]);
    enzyme_concentration[e] ~ lognormal(log(prior_loc_enzyme[,e]), prior_scale_enzyme[,e]);
  }
  if (LIKELIHOOD == 1){
    for (c in 1:N_conc_measurement){
      target += lognormal_lpdf(yconc[c] | log(conc[experiment_yconc[c], metabolite_yconc[c]]), sigma_conc[c]);
    }
    for (ec in 1:N_enzyme_measurement){
      target += lognormal_lpdf(yenz[ec] | log(enzyme_concentration[experiment_yenz[ec], enzyme_yenz[ec]]), sigma_enz[ec]);
    }
    for (f in 1:N_flux_measurement){
      target += normal_lpdf(yflux[f] | flux[experiment_yflux[f], reaction_yflux[f]], sigma_flux[f]);
    }
  }
}
generated quantities {
  vector[N_conc_measurement] yconc_sim;
  vector[N_enzyme_measurement] yenz_sim;
  vector[N_flux_measurement] yflux_sim;
  for (c in 1:N_conc_measurement){
    yconc_sim[c] = lognormal_rng(log(conc[experiment_yconc[c], metabolite_yconc[c]]), sigma_conc[c]);
  }
  for (ec in 1:N_enzyme_measurement){
    yenz_sim[ec] = lognormal_rng(log(enzyme_concentration[experiment_yenz[ec], enzyme_yenz[ec]]), sigma_enz[ec]);
  }
  for (f in 1:N_flux_measurement){
    yflux_sim[f] = normal_rng(flux[experiment_yflux[f], reaction_yflux[f]], sigma_flux[f]);
  }
}
