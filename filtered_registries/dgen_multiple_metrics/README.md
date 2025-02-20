# Instructions
This project was created by running the script in this directory.

Pre-requisities:
- Clone the dsgrid-project-IEF repository.
- Download the dGen load data.

```bash
$ cd filtered_registries/dgen_multiple_metrics
```
**Warning**: This example sets the overwrite flag to delete the existing data.

```bash
$ python make_dgen_project.py \
    --src-repo-path ~/repos/dsgrid-project-IEF \
    --dgen-data-src-path ~/dgen-data \
    --dst-repo-path dsgrid-project-IEF \
    --dgen-data-profiles-dst-path dgen_profiles_data \
    --dgen-data-capacities-dst-path dgen_capacities_data \
    --overwrite
```
