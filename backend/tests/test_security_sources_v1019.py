"""1.0.19: security and multi-language code sources parse into training records."""
import json

from moth.datafactory import catalog
from moth.datafactory.parse import train_records


def test_cve_rows_become_questions_and_rejected_entries_are_skipped(tmp_path):
    p = tmp_path / "CVE_CWE_2025.csv"
    p.write_text('ID,CVE-ID,CVSS-V4,CVSS-V3,CVSS-V2,SEVERITY,DESCRIPTION,CWE-ID\n'
                 '1,CVE-2021-44228,None,10.0,9.3,CRITICAL,"Apache Log4j2 JNDI features do not protect against '
                 'attacker controlled LDAP endpoints.",CWE-502\n'
                 '2,CVE-2020-0001,None,None,None,None,"** REJECT ** Do not use.",None\n', encoding="utf-8")
    src = catalog.source("cve-cwe")
    recs = list(train_records(src, src["files"][0], p))
    assert len(recs) == 1
    a = recs[0]["messages"][1]["content"]
    assert recs[0]["messages"][0]["content"] == "What is CVE-2021-44228?"
    assert "Log4j2" in a and "CVSS 10.0" in a and "CWE-502" in a and "critical" in a


def test_csv_and_json_question_answer_sources(tmp_path):
    csvp = tmp_path / "m.csv"
    csvp.write_text('question,answer\n"What are ATT&CK tactics?","The adversary\'s goals."\n', encoding="utf-8")
    src = catalog.source("mitre-attack")
    assert list(train_records(src, src["files"][0], csvp))[0]["messages"][1]["content"] == "The adversary's goals."
    jp = tmp_path / "dataset.json"
    jp.write_text(json.dumps([{"prompt": "List files", "response": "ls -la"}]), encoding="utf-8")
    src = catalog.source("bash-commands")
    assert list(train_records(src, src["files"][0], jp))[0]["messages"][1]["content"] == "ls -la"


def test_code_rows_keep_language_and_path(tmp_path):
    import pyarrow as pa
    import pyarrow.parquet as pq

    p = tmp_path / "code.parquet"
    pq.write_table(pa.table({"code": ["fn main() {\n    println!(\"hello from rust\");\n}\n", "x"],
                             "language": ["Rust", "C"], "path": ["src/main.rs", "a.c"]}), p)
    src = catalog.source("github-code-clean")
    recs = list(train_records(src, src["files"][0], p))
    assert len(recs) == 1 and recs[0]["text"].startswith("// src/main.rs (Rust)") and recs[0]["domain"] == "code"


def test_every_new_source_is_pinned_and_licensed():
    for sid in ("cve-cwe", "mitre-attack", "cybersec-instruct", "bash-commands", "github-code-clean"):
        s = catalog.source(sid)
        assert len(s["revision"]) == 40 and s["license"] and s["attribution"]
        assert all(len(f["sha256"]) == 64 and f["size"] > 0 for f in s["files"])
