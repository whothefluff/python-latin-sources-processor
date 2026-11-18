import pandas as pd


def read_csv_with_only_empty_fields_as_missing(path, dtype=None) -> pd.DataFrame:
    """pandas takes a field such as nan, null or NA for a missing value, and an edition can print one as a word"""
    return pd.read_csv(path, dtype=dtype, keep_default_na=False, na_values=[''])
