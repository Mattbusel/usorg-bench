"""Extract distinct recipient name records from USAspending full contract downloads.

Usage: python extract_fpds.py OUT.parquet ZIP [ZIP ...]

Each input is a USAspending "All Contracts Full" zip (FPDS prime transactions). The
output has one row per distinct (uei, name_raw, dba, address, city, state, zip5,
parent fields, organizational flags) with the first and last action date seen.
Only the columns below are read; every value is kept as a string.
"""
import sys
import zipfile

import pyarrow as pa
import pyarrow.csv as pacsv
import duckdb

COLS = [
    "recipient_uei", "recipient_name", "recipient_name_raw", "recipient_doing_business_as_name",
    "recipient_parent_uei", "recipient_parent_name", "recipient_parent_name_raw",
    "recipient_address_line_1", "recipient_city_name", "recipient_state_code", "recipient_zip_4_code",
    "recipient_country_code", "organizational_type", "sole_proprietorship", "action_date",
]


def batches(zpath):
    with zipfile.ZipFile(zpath) as z:
        for info in z.infolist():
            if not info.filename.endswith(".csv"):
                continue
            with z.open(info) as fh:
                reader = pacsv.open_csv(
                    fh,
                    read_options=pacsv.ReadOptions(block_size=64 << 20),
                    convert_options=pacsv.ConvertOptions(
                        include_columns=COLS, column_types={c: pa.string() for c in COLS}),
                )
                for b in reader:
                    yield info.filename, b


def main():
    out, zips = sys.argv[1], sys.argv[2:]
    con = duckdb.connect()
    con.execute("create table acc as select * from (select " + ", ".join(f"''::varchar as {c}" for c in COLS[:-1])
                + ", ''::varchar as first_seen, ''::varchar as last_seen) where false")
    keycols = ", ".join(COLS[:-1])
    n = 0
    for zp in zips:
        for fname, b in batches(zp):
            tbl = pa.Table.from_batches([b])
            con.register("b", tbl)
            con.execute(f"insert into acc select {keycols}, min(action_date), max(action_date) from b "
                        f"where recipient_uei is not null group by all")
            con.unregister("b")
            n += b.num_rows
            if n % 2_000_000 < b.num_rows:
                con.execute(f"create or replace table acc as select {keycols}, min(first_seen) first_seen, "
                            f"max(last_seen) last_seen from acc group by all")
                print(fname, n, con.execute("select count(*) from acc").fetchall()[0][0], flush=True)
    con.execute(f"create or replace table acc as select {keycols}, min(first_seen) first_seen, max(last_seen) last_seen "
                f"from acc group by all")
    con.execute(f"copy acc to '{out}' (format parquet)")
    print("rows read", n, "distinct", con.execute("select count(*) from acc").fetchall()[0][0])


if __name__ == "__main__":
    main()
