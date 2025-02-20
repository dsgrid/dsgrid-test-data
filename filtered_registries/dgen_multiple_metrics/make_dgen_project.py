import copy
import fileinput
import shutil
import sys
from pathlib import Path
from typing import Sequence

import rich_click as click
import duckdb
from chronify.utils.path_utils import check_overwrite

from dsgrid.utils.files import dump_data, load_data


def make_dgen_project(
    src_repo_path: Path,
    dgen_src_data_path: Path,
    dst_repo_path: Path,
    dgen_dst_profiles_data_path: Path,
    dgen_dst_capacities_data_path: Path,
    overwrite: bool = False,
) -> None:
    if not src_repo_path.exists():
        raise FileNotFoundError(f"Source repo path {src_repo_path} does not exist.")
    if not dgen_src_data_path.exists():
        raise FileNotFoundError(f"dGen data path {dgen_src_data_path} does not exist.")

    check_overwrite(dst_repo_path, overwrite)
    check_overwrite(dgen_dst_profiles_data_path, overwrite)
    check_overwrite(dgen_dst_capacities_data_path, overwrite)
    dgen_dst_profiles_data_path.mkdir()
    dgen_dst_capacities_data_path.mkdir()

    copy_files(src_repo_path, dst_repo_path)
    counties = ("06073",)
    model_years = ("2030",)
    fix_project(dst_repo_path, counties, model_years)
    tracts_table = fix_dataset_configs_geo(dst_repo_path)
    model_year_table = fix_dataset_configs_model_year(dst_repo_path)
    fix_dgen_profiles(dst_repo_path)
    make_dgen_capacities(dst_repo_path)
    fix_dataset_mapping_configs(dst_repo_path)
    fix_dataset_data(
        tracts_table,
        model_year_table,
        dgen_src_data_path,
        dgen_dst_profiles_data_path,
        dgen_dst_capacities_data_path,
    )


def copy_files(src_repo_path: Path, dst_repo_path: Path) -> None:
    dst_repo_path.mkdir()
    (dst_repo_path / "datasets" / "modeled").mkdir(parents=True)
    shutil.copytree(src_repo_path / "project", dst_repo_path / "project")
    shutil.copytree(
        src_repo_path / "datasets" / "modeled" / "dgen",
        dst_repo_path / "datasets" / "modeled" / "dgen_profiles",
    )
    shutil.rmtree(dst_repo_path / "project" / "scripts")


def fix_project(
    dst_repo_path: Path, counties: tuple[str, ...], model_years: tuple[str, ...]
) -> None:
    project_config_file = dst_repo_path / "project" / "project.json5"
    project_config = load_data(project_config_file)
    for dataset in project_config["datasets"]:
        if dataset["dataset_id"] == "decarb_2023_dgen":
            project_config["datasets"] = [
                dataset,
                copy.deepcopy(dataset),
            ]
            project_config["datasets"][0]["required_dimensions"]["single_dimensional"][
                "metric"
            ]["base"] = ["dpv_profiles"]
            project_config["datasets"][1]["dataset_id"] = "decarb_2023_dgen_capacities"
            project_config["datasets"][1]["required_dimensions"]["single_dimensional"][
                "metric"
            ]["base"] = ["dpv_capacity"]
            break

    project_config["dimensions"]["base_dimensions"] += [
        {
            "type": "metric",
            "class": "Stock",
            "name": "DECARB 2023 DPV Profiles",
            "display_name": "DPV Profiles",
            "description": "DECARB 2023 DPV Profiles",
            "file": "dimensions/profiles.csv",
            "module": "dsgrid.dimension.standard",
        },
        {
            "type": "metric",
            "class": "Stock",
            "name": "DECARB 2023 DPV Capacity",
            "display_name": "DPV Capacity",
            "description": "DECARB 2023 DPV Capacity",
            "file": "dimensions/capacity.csv",
            "module": "dsgrid.dimension.standard",
        },
    ]
    project_config["dimensions"]["supplemental_dimensions"].clear()
    project_config["dimensions"]["subset_dimensions"].clear()
    dump_data(project_config, project_config_file, indent=2)

    counties_file = dst_repo_path / "project" / "dimensions" / "counties.csv"
    filter_csv_file(counties_file, counties)
    model_years_file = dst_repo_path / "project" / "dimensions" / "model_years.csv"
    filter_csv_file(model_years_file, model_years)
    profiles_file = dst_repo_path / "project" / "dimensions" / "profiles.csv"
    profiles_file.write_text(
        "id,name,unit\ndpv_profiles,DPV Profiles,h\n", encoding="utf-8"
    )
    capacities_file = dst_repo_path / "project" / "dimensions" / "capacity.csv"
    capacities_file.write_text(
        "id,name,unit\ndpv_capacity,DPV Capacity,kw\n", encoding="utf-8"
    )


def fix_dataset_configs_geo(repo_path: Path) -> str:
    counties_file = repo_path / "project" / "dimensions" / "counties.csv"
    tracts_file = (
        repo_path
        / "datasets"
        / "modeled"
        / "dgen_profiles"
        / "dimensions"
        / "geography.csv"
    )
    mapping_file = (
        repo_path
        / "datasets"
        / "modeled"
        / "dgen_profiles"
        / "dimension_mappings"
        / "tract_to_county.csv"
    )
    county_dtypes = {
        "id": duckdb.typing.VARCHAR,
        "name": duckdb.typing.VARCHAR,
        "state": duckdb.typing.VARCHAR,
        "time_zone": duckdb.typing.VARCHAR,
    }
    rel_counties = duckdb.read_csv(str(counties_file), dtype=county_dtypes)  # noqa
    mapping_dtypes = {
        "from_id": duckdb.typing.VARCHAR,
        "to_id": duckdb.typing.VARCHAR,
    }
    rel_mapping = duckdb.read_csv(str(mapping_file), dtype=mapping_dtypes)  # noqa

    duckdb.sql("CREATE TABLE counties AS SELECT * FROM rel_counties")
    duckdb.sql("CREATE TABLE mapping AS SELECT * FROM rel_mapping")

    table_name = "filtered_tracts"
    duckdb.sql(
        f"""
        CREATE TABLE {table_name} AS
        SELECT mapping.from_id as id
        FROM mapping
        JOIN counties ON mapping.to_id = counties.id
    """
    )
    tracts_to_keep = (
        duckdb.sql("SELECT * FROM filtered_tracts").to_arrow_table()["id"].to_pylist()
    )
    filter_csv_file(tracts_file, tracts_to_keep)
    filter_csv_file(mapping_file, tracts_to_keep)
    return table_name


def fix_dataset_configs_model_year(repo_path: Path) -> str:
    project_model_years_file = repo_path / "project" / "dimensions" / "model_years.csv"
    dataset_model_years_file = (
        repo_path
        / "datasets"
        / "modeled"
        / "dgen_profiles"
        / "dimensions"
        / "model_years.csv"
    )
    mapping_file = (
        repo_path
        / "datasets"
        / "modeled"
        / "dgen_profiles"
        / "dimension_mappings"
        / "model_year_to_model_year.csv"
    )
    model_year_dtypes = {
        "id": duckdb.typing.VARCHAR,
        "name": duckdb.typing.VARCHAR,
    }
    rel_model_years = duckdb.read_csv(  # noqa
        str(project_model_years_file), dtype=model_year_dtypes
    )
    mapping_dtypes = {
        "from_id": duckdb.typing.VARCHAR,
        "to_id": duckdb.typing.VARCHAR,
    }
    rel_mapping = duckdb.read_csv(str(mapping_file), dtype=mapping_dtypes)  # noqa

    duckdb.sql("CREATE TABLE model_years AS SELECT * FROM rel_model_years")
    duckdb.sql("CREATE TABLE mapping_my AS SELECT * FROM rel_mapping")

    table_name = "filtered_model_years"
    duckdb.sql(
        f"""
        CREATE TABLE {table_name} AS (
            SELECT mapping_my.from_id as id
            FROM mapping_my
            JOIN model_years ON mapping_my.to_id = model_years.id
        )
    """
    )
    model_years_to_keep = (
        duckdb.sql("SELECT * FROM filtered_model_years")
        .to_arrow_table()["id"]
        .to_pylist()
    )
    filter_csv_file(dataset_model_years_file, model_years_to_keep)
    filter_csv_file(mapping_file, model_years_to_keep)
    return table_name


def fix_dataset_mapping_configs(dst_repo_path) -> None:
    mapping_file = (
        dst_repo_path
        / "datasets"
        / "modeled"
        / "dgen_capacities"
        / "dimension_mappings.json5"
    )
    data = load_data(mapping_file)
    data["mappings"].append(
        {
            "description": "Mapping from DPV capacity to DPV capacity",
            "dimension_type": "metric",
            "file": "dimension_mappings/capacity_to_capacity.csv",
            "mapping_type": "one_to_one",
            "from_dimension_name": "DECARB 2023 DPV Capacity",
        }
    )
    dump_data(data, mapping_file, indent=2)
    Path(
        dst_repo_path
        / "datasets"
        / "modeled"
        / "dgen_capacities"
        / "dimension_mappings"
        / "capacity_to_capacity.csv"
    ).write_text("from_id,to_id\ncapacity,dpv_capacity\n", encoding="utf-8")


def fix_dgen_profiles(dst_repo_path: Path) -> None:
    dataset_config_file = (
        dst_repo_path / "datasets" / "modeled" / "dgen_profiles" / "dataset.json5"
    )
    dataset_config = load_data(dataset_config_file)
    found_metric = False
    for i, dim in enumerate(dataset_config["dimensions"]):
        if dim["type"] == "metric":
            dataset_config["dimensions"][i] = {
                "type": "metric",
                "name": "DPV profiles",
                "display_name": "DPV profiles",
                "file": "dimensions/profiles.csv",
                "module": "dsgrid.dimension.standard",
                "class": "Stock",
                "description": "dGen DPV hourly profiles",
            }
            found_metric = True
            break

    assert found_metric
    dump_data(dataset_config, dataset_config_file, indent=2)
    profiles_file = (
        dst_repo_path
        / "datasets"
        / "modeled"
        / "dgen_profiles"
        / "dimensions"
        / "profiles.csv"
    )
    # This intentionally uses the same record ID as the project so that no mapping is needed.
    profiles_file.write_text(
        "id,name,unit\ndpv_profiles,dpv_profiles,h\n", encoding="utf-8"
    )


def make_dgen_capacities(dst_repo_path: Path) -> None:
    profiles_path = dst_repo_path / "datasets" / "modeled" / "dgen_profiles"
    capacities_path = dst_repo_path / "datasets" / "modeled" / "dgen_capacities"
    shutil.copytree(profiles_path, capacities_path)
    dataset_config_file = (
        dst_repo_path / "datasets" / "modeled" / "dgen_capacities" / "dataset.json5"
    )
    dataset_config = load_data(dataset_config_file)
    dataset_config["dataset_id"] = "decarb_2023_dgen_capacities"
    dataset_config["trivial_dimensions"].append("metric")
    dataset_config["data_schema"] = {
        "table_format": {
            "format_type": "unpivoted",
        },
        "data_schema_type": "one_table",
    }
    found_metric = False
    found_time = False
    for i, dim in enumerate(dataset_config["dimensions"]):
        if dim["type"] == "time":
            dataset_config["dimensions"][i] = {
                "type": "time",
                "time_type": "annual",
                "class": "Time",
                "name": "dGen annual capacity time",
                "display_name": "Time annual",
                "description": "dGen annual capacity time",
                "str_format": "%Y",
                "measurement_type": "total",
                "ranges": [
                    {
                        "start": "2030",
                        "end": "2030",
                    },
                ],
            }
            found_time = True
        elif dim["type"] == "metric":
            dataset_config["dimensions"][i] = {
                "type": "metric",
                "name": "DPV capacity",
                "display_name": "DPV capacity",
                "file": "dimensions/capacity.csv",
                "module": "dsgrid.dimension.standard",
                "class": "Stock",
                "description": "dGen DPV capacity in kW",
            }
            found_metric = True
    assert found_metric
    assert found_time
    dump_data(dataset_config, dataset_config_file, indent=2)
    capacities_file = (
        dst_repo_path
        / "datasets"
        / "modeled"
        / "dgen_capacities"
        / "dimensions"
        / "capacity.csv"
    )
    # This intentionally uses a different record ID than the project for mapping.
    capacities_file.write_text("id,name,unit\ncapacity,capacity,kw\n", encoding="utf-8")


def fix_dataset_data(
    tracts_table_name: str,
    model_year_table_name: str,
    dgen_src_data_path: Path,
    dgen_dst_data_path: Path,
    dgen_dst_capacities_data_path: Path,
) -> None:
    duckdb.sql(
        f"""
        CREATE TABLE load_data_lookup AS (
            SELECT *
            FROM read_parquet('{dgen_src_data_path}/load_data_lookup.parquet/**/*.parquet')
        )
    """
    )
    duckdb.sql(
        f"""
        CREATE TABLE load_data AS (
            SELECT timestamp, id, electricity_dpv as dpv_profiles
            FROM read_parquet('{dgen_src_data_path}/load_data.parquet/**/*.parquet')
        )
    """
    )
    duckdb.sql(
        f"""
        CREATE TABLE load_data_lookup_filtered AS (
            SELECT load_data_lookup.*
            FROM load_data_lookup
            JOIN {tracts_table_name} ON load_data_lookup.geography = {tracts_table_name}.id
            JOIN {model_year_table_name} ON load_data_lookup.model_year = {model_year_table_name}.id
        )
    """
    )
    duckdb.sql(
        """
        CREATE TABLE load_data_filtered AS (
            WITH load_data_ids AS (
                SELECT DISTINCT id AS id FROM load_data_lookup_filtered
            )
            SELECT load_data.*
            FROM load_data
            JOIN load_data_ids ON load_data.id = load_data_ids.id
        )
    """
    )
    new_lookup_file = dgen_dst_data_path / "load_data_lookup.parquet"
    new_load_data_file = dgen_dst_data_path / "load_data.parquet"
    duckdb.sql(
        f"COPY load_data_lookup_filtered TO '{new_lookup_file}' (FORMAT PARQUET, COMPRESSION snappy)"
    )
    duckdb.sql(
        f"COPY load_data_filtered TO '{new_load_data_file}' (FORMAT PARQUET, COMPRESSION snappy)"
    )

    duckdb.sql(
        """
        CREATE TABLE dgen_capacities AS (
            SELECT geography, sector, subsector, model_year
            ,model_year AS time_year
            ,scaling_factor AS value
            FROM load_data_lookup_filtered
        )
    """
    )
    duckdb.sql(
        f"""
        COPY dgen_capacities
        TO '{dgen_dst_capacities_data_path}/load_data.parquet'
        (FORMAT PARQUET, COMPRESSION snappy)
    """
    )

    print(f"Wrote filtered load_data_lookup to {new_lookup_file}")
    print(f"Wrote filtered load_data to {new_load_data_file}")
    print(f"Wrote dgen_capacities to {dgen_dst_capacities_data_path}")


def filter_csv_file(filename: Path, ids: Sequence[str]) -> None:
    with fileinput.input(files=[filename], inplace=True) as f:
        for i, line in enumerate(f):
            if i == 0:
                print(line, end="")
            else:
                for id_ in ids:
                    if line.startswith(f"{id_},"):
                        print(line, end="")
                        break

    print(f"Filtered {filename}")


@click.command()
@click.option(
    "-s",
    "--src-repo-path",
    type=Path,
    required=True,
    help="Path to the source dsgrid-project-IEF repository.",
    callback=lambda *x: Path(x[2]),
)
@click.option(
    "-f",
    "--dgen-data-src-path",
    type=Path,
    required=True,
    help="Path to the source dGen data.",
    callback=lambda *x: Path(x[2]),
)
@click.option(
    "-d",
    "--dst-repo-path",
    type=Path,
    required=True,
    help="Path to the destination project repository.",
    callback=lambda *x: Path(x[2]),
)
@click.option(
    "-o",
    "--dgen-data-profiles-dst-path",
    type=Path,
    required=True,
    help="Path to the destination dGen profiles data.",
    callback=lambda *x: Path(x[2]),
)
@click.option(
    "-c",
    "--dgen-data-capacities-dst-path",
    type=Path,
    required=True,
    help="Path to the destination dGen capacities data.",
    callback=lambda *x: Path(x[2]),
)
@click.option(
    "--overwrite",
    is_flag=True,
    default=False,
    help="Overwrite the destination directories if they exist.",
)
def cli(
    src_repo_path: Path,
    dst_repo_path: Path,
    dgen_data_src_path: Path,
    dgen_data_profiles_dst_path: Path,
    dgen_data_capacities_dst_path: Path,
    overwrite: bool,
) -> None:
    """Create a dsgrid project for dGen data."""
    make_dgen_project(
        src_repo_path,
        dgen_data_src_path,
        dst_repo_path,
        dgen_data_profiles_dst_path,
        dgen_data_capacities_dst_path,
        overwrite=overwrite,
    )


if __name__ == "__main__":
    cli()
