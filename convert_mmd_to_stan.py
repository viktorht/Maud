import re

INPUT_FILE = "Ecoli glycolisis.mmd"
OUTPUT_FILE = "data/steady_state_autogen.stan"


def remove_non_numeric_bits(s, return_type=float):
    """Remove non-numeric bits from a string"""
    regex = "[-+]?[.]?[\d]+(?:,\d\d\d)*[\.]?\d*(?:[eE][-+]?\d+)?"
    finds = re.findall(regex, s)
    if return_type == float:
        return float(finds[0])
    elif return_type == str:
        return finds[0]
    elif return_type == list:
        return finds
    else:
        raise ValueError('unsupported return type: ' + str(return_type))
    
def get_all_metabolites(input_file):
    with open(input_file, 'r') as f:
        for l in f:
            if 'concentration of metabolite' in l:
                yield re.findall("concentration of metabolite '(.*?)'", l)[0]



def get_ode_metabolites(input_file):
    with open(input_file, 'r') as f:
        for l in f:
            if l[:4] == 'init':
                met = l.split(' ')[1]
                yield met
            

def get_conserved_totals(input_file):
    with open(input_file, 'r') as f:
        for l in f:
            if 'conserved total' in l:
                ct = remove_non_numeric_bits(l.split(' ')[2])
                yield ct


def get_named_quantity(input_file, quantity_type):
    out = dict()
    with open(input_file, 'r') as f:
        for l in f:
            if quantity_type in l:
                split_line = l.split('=')
                name = split_line[0].strip()
                volume = remove_non_numeric_bits(split_line[1])
                out[name] = volume
    return out


def get_derived_quantities(input_file):
    out = dict()
    on = False
    with open(input_file, 'r') as f:
        for l in f:
            if l == ' \n':
                on = False
            if on:
                quantity = l.split(' ')[0]
                expression = re.findall("\= (.*?);", l)[0].replace('\t', '') + ';'
                # turn square bracket indexes into subscripts
                expression = re.sub(r"\[([^{}]+)\]", r"_\1", expression)
                out[quantity] = expression
            if l == '{Assignment Model Entities: }\n':
                on = True
    return out


def get_kinetic_functions(input_file):
    out = dict()
    with open(input_file, 'r') as f:
        for l in f:
            if 'kinetic function' in l:
                reaction = re.findall("reaction '(.*?)'", l)[0]
                expression = l.split(' ')[2].replace('\t', '')
                out[reaction] = expression
    return out


def get_odes(input_file):
    out = dict()
    with open(input_file, 'r') as f:
        for l in f:
            if l[:4] == 'd/dt':
                reaction = re.findall('d/dt\((.*?)\)', l)[0]
                expression = (l.split(' ')[2]
                              .replace('\t', '')
                              .replace('FunctionFor', '')
                              .replace(';', ','))
                out[reaction] = expression
    return out


def build_derived_quantity_function(conserved_totals,
                                    compartments,
                                    ode_metabolites,
                                    derived_quantity_expressions):
    first_block = """real[] get_derived_quantities(vector ode_metabolites,
                              real[] global_quantities,
                              real[] conserved_totals){"""
    conserved_total_lines = [
        f"  real ct_{i} = conserved_totals[{i+1}];"
        for i, _ in enumerate(conserved_totals)
    ]
    compartment_lines = [
        f"  real {compartment} = {compartment};"
        for compartment in compartments.values()
    ]
    ode_metabolite_lines = [
        f"  real {metabolite} = ode_metabolites[{i+1}];"
        for i, metabolite in enumerate(ode_metabolites)
    ]
    derivation_lines = [
        f"  real {quantity} = {expression}"
        for quantity, expression in derived_quantity_expressions.items()
    ]
    return_line = f"  return {{{', '.join(derived_quantity_expressions.keys())}}};"
    close_braces_line = "}"
    return '\n'.join([first_block,
                      *compartment_lines,
                      *conserved_total_lines,
                      *ode_metabolite_lines,
                      *derivation_lines,
                      return_line,
                      close_braces_line])


def build_kinetics_function(conserved_totals,
                            compartments,
                            kinetic_functions,
                            ode_metabolites,
                            derived_quantity_expressions,
                            global_quantities):
    first_block = """real[] get_kinetics(vector ode_metabolites,
                    vector kinetic_parameters,
                    real[] global_quantities,
                    real[] conserved_totals){"""

    conserved_total_lines = [
        f"  real ct_{i} = conserved_totals[{i+1}];"
        for i, _ in enumerate(conserved_totals)
    ]
    compartment_lines = [
        f"  real {compartment} = {compartment};"
        for compartment in compartments.values()
    ]
    ode_metabolite_lines = [
        f"  real {metabolite} = ode_metabolites[{i+1}];"
        for i, metabolite in enumerate(ode_metabolites)
    ]
    kinetic_parameter_lines = [
        f"  real {parameter} = kinetic_parameters[{i+1}]"
        for i, parameter in enumerate(kinetic_parameters)
    ]
    derived_quantity_calculation_line = (
        f"  real derived_quantities[{len(derived_quantity_expressions.keys())}] ="
        "get_derived_quantities(ode_metabolites, global_quantities, conserved_totals);"
    )
    derived_quantity_unpack_lines = [
        f"  real {quantity} = derived_quantities[{i+1}]"
        for i, quantity in enumerate(derived_quantity_expressions.keys())
    ]
    kinetic_expression_lines = [
        f"  real {parameter} = {expression}"
        for parameter, expression in kinetic_functions.items()
    ]
    return_line = f"  return [{', '.join(kinetic_functions.keys())}]';"
    close_braces_line = "}"
    return '\n'.join([first_block,
                      *compartment_lines,
                      *conserved_total_lines,
                      *ode_metabolite_lines,
                      *kinetic_parameter_lines,
                      derived_quantity_calculation_line,
                      *derived_quantity_unpack_lines,
                      *kinetic_expression_lines,
                      return_line,
                      close_braces_line])


def build_ode_function(odes):
    definition_line = "vector get_odes(vector fluxes){"
    flux_unpack_lines = [
        f"  real {flux} = fluxes[{i+1}];"
        for i, flux in enumerate(odes.keys())
    ]
    return_line_open = "  return ["
    return_body_lines = [
        f"    {expression}  // {flux}"
        for flux, expression in odes.items()
    ]
    return_close_line = "  ]';"
    close_braces_line = "}"
    return '\n'.join([definition_line,
                      *flux_unpack_lines,
                      return_line_open,
                      *return_body_lines,
                      return_close_line,
                      close_braces_line])


def build_steady_state_function():
    return (
    """vector steady_state_equation(vector ode_metabolites, vector kinetic_parameters, real[] known_reals, int[] known ints){
    return get_odes(get_kinetics(ode_metabolites, kinetic_parameters, known_reals));"""
    )
            

if __name__ == '__main__':
    # parse input
    metabolites = get_all_metabolites(INPUT_FILE)
    ode_metabolites = get_ode_metabolites(INPUT_FILE)
    conserved_totals = get_conserved_totals(INPUT_FILE)
    compartments = get_named_quantity(INPUT_FILE, 'compartment')
    kinetic_parameters = get_named_quantity(INPUT_FILE, 'kinetic parameter')
    global_quantities = get_named_quantity(INPUT_FILE, 'global quantity')
    derived_quantity_expressions = get_derived_quantities(INPUT_FILE)
    kinetic_functions = get_kinetic_functions(INPUT_FILE)
    odes = get_odes(INPUT_FILE)

    derived_quantity_function = build_derived_quantity_function(
        conserved_totals,
        compartments,
        ode_metabolites,
        derived_quantity_expressions
    )
    kinetics_function = build_kinetics_function(
        conserved_totals,
        compartments,
        kinetic_functions,
        ode_metabolites,
        derived_quantity_expressions,
        global_quantities
    )
    ode_function = build_ode_function(odes)
    steady_state_function = build_steady_state_function()

    out = '\n\n'.join([derived_quantity_function,
                       kinetics_function,
                       ode_function,
                       steady_state_function])
    output_file = open(OUTPUT_FILE, "w")
    output_file.write(out)
    output_file.close()
    print(out)


