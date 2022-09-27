"""Generate a filtered EFS ComStock dataset consistent with a dsgrid project."""

import os
from pathlib import Path

import click

import dsgrid.utils.files
from dsgrid.utils.spark import init_spark, read_dataframe


@click.command()
@click.argument("project_dir", type=click.Path(exists=True))
@click.argument("src-data-path", type=click.Path(exists=True))
@click.argument("output-dir")
def generate_efs_comstock(project_dir, src_data_path, output_dir):
    """Generate a filtered EFS ComStock dataset consistent with a dsgrid project."""
    spark = init_spark("test")
    project_dir = Path(project_dir)

    dataset_dir = project_dir / "dsgrid_project" / "datasets" / "modeled" / "comstock"
    dataset_filename = dataset_dir / "dataset.toml"
    dataset_id = dsgrid.utils.files.load_data(dataset_filename)["dataset_id"]

    counties_filename = project_dir / "dsgrid_project" / "dimensions" / "comstock_counties.csv"
    counties = read_dataframe(counties_filename, cache=True)

    end_uses_filename = project_dir / "dsgrid_project" / "dimensions" / "enduses.csv"
    end_uses = read_dataframe(end_uses_filename, cache=True)
    end_use_columns = [x.id for x in end_uses.select("id").distinct().collect()]

    dataset_dimensions_filename = dataset_dir / "dimensions.toml"
    dataset_data = dsgrid.utils.files.load_data(dataset_dimensions_filename)
    end_time = None
    timezone = None
    for dimension in dataset_data["dimensions"]:
        if dimension["type"] == "time":
            assert len(dimension["ranges"]) == 1
            end_time = dimension["ranges"][0]["end"]
            timezone = dimension["timezone"]
    assert end_time is not None
    if timezone == "EasternStandard":
        spark.conf.set("spark.sql.session.timeZone", "EST")
    else:
        raise ValueError(f"timezone={timezone} is not supported")

    load_data = spark.read.parquet(str(Path(src_data_path) / "load_data.parquet"))
    load_data_lookup = spark.read.parquet(str(Path(src_data_path) / "load_data_lookup.parquet"))

    new_ldl = counties.join(load_data_lookup, counties.id == load_data_lookup.geography) \
        .select(*load_data_lookup["geography", "subsector", "id"])
    assert new_ldl.columns == load_data_lookup.columns

    ld_columns = ["id", "timestamp"] + end_use_columns
    reduced_ld = load_data.filter(load_data.timestamp <= end_time).select(ld_columns)
    new_ld = reduced_ld.join(new_ldl, reduced_ld.id == new_ldl.id) \
        .drop(new_ldl["id"]) \
        .drop(new_ldl["geography"]) \
        .drop(new_ldl["subsector"]) \
        .repartition(1)

    output_dir = Path(output_dir) / dataset_id
    os.makedirs(output_dir, exist_ok=True)
    filtered_load_data_filename = output_dir / "load_data.csv"
    new_ld.write.csv(str(filtered_load_data_filename), header=True, mode="overwrite")
    print(f"Generated {filtered_load_data_filename}")

    # Use JSON because the spark CSV reader interprets geography IDs as
    # integers instead of strings. We would have to specify the schema manually.
    filtered_load_data_lookup_filename = output_dir / "load_data_lookup.json"
    new_ldl.write.json(str(filtered_load_data_lookup_filename), mode="overwrite")
    print(f"Generated {filtered_load_data_lookup_filename}")


if __name__ == "__main__":
    generate_efs_comstock()
