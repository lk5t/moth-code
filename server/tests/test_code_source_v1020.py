"""1.0.20: GitHub code rows keep their language and path (Parquet needs pyarrow, a MOTH Cloud dependency)."""
from moth.datafactory import catalog
from moth.datafactory.parse import train_records


def test_code_rows_keep_language_and_path(tmp_path):
    import pyarrow as pa
    import pyarrow.parquet as pq

    p = tmp_path / "code.parquet"
    pq.write_table(pa.table({"code": ["fn main() {\n    println!(\"hello from rust\");\n}\n", "x"],
                             "language": ["Rust", "C"], "path": ["src/main.rs", "a.c"]}), p)
    src = catalog.source("github-code-clean")
    recs = list(train_records(src, src["files"][0], p))
    assert len(recs) == 1 and recs[0]["text"].startswith("// src/main.rs (Rust)") and recs[0]["domain"] == "code"
