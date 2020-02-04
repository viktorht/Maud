real[] ode_func(real t, real[] m, real[] p, real[] xr, int[] xi){
  real metabolites[{{N_mic}}];
  vector[{{N_flux}}] fluxes;
  metabolites[{ {{-balanced_mic_ix|join(',')-}} }] = m;
  metabolites[{ {{-unbalanced_mic_ix|join(',')-}} }] = to_array_1d(p[1:{{N_unbalanced}}]);
  fluxes = get_fluxes(metabolites, p);
  return {
    {%- for ode in ode_stoic %}
    {{ode}}{{"," if not loop.last}}
    {%- endfor %}
  };
}
