import pandas as pd

def one_index_factorize(values, **kwargs):
    labels, uniques = pd.factorize(values)
    labels += 1
    return labels, uniques
