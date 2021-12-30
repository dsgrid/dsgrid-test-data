"""Generate an EFS ComStock dataset with LOCAL time, 
copied and modified into LOCAL time from the EFS ComStock dataset
"""

import pandas as pd
from pathlib import Path
import os

root_path = Path(__file__).parents[1]
efs_dataset_path = root_path / "datasets" / "test_efs_comstock"
efs_utc_dataset_path = root_path / "datasets" / "test_efs_comstock_utc"

if not os.path.exists(efs_utc_dataset_path):
    os.makedirs(efs_utc_dataset_path)

load_data = pd.read_csv(efs_dataset_path / "load_data.csv")
load_data_lookup = pd.read_json(
    efs_dataset_path/ "load_data_lookup.json", lines=True, dtype={"geography": str})

df = pd.merge(load_data, load_data_lookup, on=["id"], how="left")

df.timestamp = pd.DatetimeIndex(df.timestamp)

def apply_local_standard_time_and_convert_to_utc(row):
    if row.geography.startswith("36"): # NY
        return row.timestamp.tz_localize(None).tz_localize("Etc/GMT+5").tz_convert("UTC")
    elif row.geography.startswith("48"): # TX
        return row.timestamp.tz_localize(None).tz_localize("Etc/GMT+6").tz_convert("UTC")
    elif row.geography.startswith("08"): # CO
        return row.timestamp.tz_localize(None).tz_localize("Etc/GMT+7").tz_convert("UTC")
    elif row.geography.startswith("06"): # CA
        return row.timestamp.tz_localize(None).tz_localize("Etc/GMT+8").tz_convert("UTC")
    else:
        raise ValueError(f"row geography {row.geography} is not in (08, 06, 36, 48)")

df["timestamp"] = df.apply(apply_local_standard_time_and_convert_to_utc, axis=1)

load_data_lookup.to_json(
    efs_utc_dataset_path / "load_data_lookup.json")
df[["id", "timestamp", "cooling", "fans"]].to_csv(
    efs_utc_dataset_path / "load_data.csv", index=False)

print(df.timestamp.min(), df.timestamp.max())