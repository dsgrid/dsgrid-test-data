from dsgrid.utils.spark import init_spark


def main():
    spark = init_spark()
    ld = spark.read.csv("datasets/test_efs_comstock/load_data.csv", inferSchema=True, header=True)
    lk = spark.read.json("datasets/test_efs_comstock/load_data_lookup.json")
    df = ld.join(lk, on="id", how="right").drop("id")
    ids = ["timestamp", "geography", "sector", "subsector"]
    value_columns = ["com_cooling", "com_fans"]
    variable_column = "metric"
    value_column = "value"
    df = df.unpivot(ids, value_columns, variable_column, value_column)
    df.coalesce(1).write.mode("overwrite").parquet("datasets/test_efs_comstock2/load_data.parquet")
    print("Created one-table datasets/test_efs_comstock2/load_data.parquet")


if __name__ == "__main__":
    main()
