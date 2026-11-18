"""1.0.19: security and multi-language code sources, each pinned to an exact upstream revision with the size
and SHA-256 of every file. Only openly licensed data; licence and attribution travel with every model.

* CVE/CWE descriptions (CC0) and MITRE ATT&CK tactics and techniques (MIT): what vulnerabilities and
  attack techniques are, how severe they are and which weakness class they belong to. They count as
  "code" (MOTH is a coding and security-testing AI), so they share the largest part of every mix.
* Cybersecurity instruction tuning (Apache-2.0): security questions answered in depth (defence, analysis,
  testing methodology), as conversations.
* Natural-language-to-bash (MIT): everyday shell tasks.
* github-code-clean (Apache-2.0 dataset of permissively licensed files): real code in ~30 languages, so
  MOTH is not a Python-only model.
"""

SOURCES = [
    {"id": "cve-cwe", "name": "CVE and CWE descriptions (1999-2025)", "domain": "code",
     "repo": "stasvinokur/cve-and-cwe-dataset-1999-2025", "revision": "f19a95aa845d7b6d05b0f372ba6201bb4dfe4813",
     "format": "cve_csv", "license": "CC0-1.0", "license_url": "https://creativecommons.org/publicdomain/zero/1.0/",
     "attribution": "CVE and CWE dataset 1999-2025 by stasvinokur (CC0); CVE content from the CVE Program",
     "description": "Every published vulnerability: what it is, its severity (CVSS) and its weakness class (CWE).",
     "files": [{"path": "CVE_CWE_2025.csv", "size": 102599759, "role": "train",
                "sha256": "010d53e2c818a0aae578c99d00a327b221aa2a6fcfcbe7db1a5f775df2e16891"}]},
    {"id": "mitre-attack", "name": "MITRE ATT&CK tactics and techniques", "domain": "code",
     "repo": "sarahwei/cyber_MITRE_attack_tactics-and-techniques", "revision": "7b2278adf23c4519ca8c9297cff6659da5a71695",
     "format": "csv_qa", "fields": ("question", "answer"), "license": "MIT", "license_url": "https://opensource.org/license/mit",
     "attribution": "cyber_MITRE_attack_tactics-and-techniques by sarahwei (MIT); based on MITRE ATT&CK",
     "description": "Questions and answers on the ATT&CK framework: tactics, techniques, detection and mitigation.",
     "files": [{"path": "MITRE-attack-tactics-and-techniques.csv", "size": 1287452, "role": "train",
                "sha256": "9a8929bd376faafc78d9ca808325a19327e9cd0863035517d95f0cdb68847a36"}]},
    {"id": "cybersec-instruct", "name": "Cybersecurity instruction tuning", "domain": "code",
     "repo": "Trendyol/Trendyol-Cybersecurity-Instruction-Tuning-Dataset",
     "revision": "357544e7576607d88eaeac9b0adb07e9fd8bb2bb", "format": "qa_jsonl", "fields": ("user", "assistant"),
     "license": "Apache-2.0", "license_url": "https://www.apache.org/licenses/LICENSE-2.0",
     "attribution": "Trendyol Cybersecurity Instruction Tuning Dataset by Trendyol (Apache-2.0)",
     "description": "Security questions answered in depth: defence, analysis, hardening and testing methodology.",
     "files": [{"path": "CyberSec-Dataset_escaped.jsonl", "size": 195018595, "role": "train",
                "sha256": "2b08b09c41da22c94507ae7a2e9cbbe6d653e8b0c798ef817e96539b18c78268"}]},
    {"id": "bash-commands", "name": "Natural language to bash", "domain": "code",
     "repo": "aelhalili/bash-commands-dataset", "revision": "67a539a9c6358574fe4f22e126cba3421fff4645",
     "format": "qa_json", "fields": ("prompt", "response"), "license": "MIT",
     "license_url": "https://opensource.org/license/mit",
     "attribution": "bash-commands-dataset by aelhalili (MIT)",
     "description": "Everyday tasks in plain English with the shell command that does them.",
     "files": [{"path": "dataset.json", "size": 91529, "role": "train",
                "sha256": "ba4ab8b447787b4f59f5fa484b72a557fbfb79ecafa54662dfeb8393e2811604"}]},
    {"id": "github-code-clean", "name": "GitHub code, permissively licensed (~30 languages)", "domain": "code",
     "repo": "codeparrot/github-code-clean", "revision": "c48d40f9e70f0196f8236901ee35807f7d6c44c0",
     "format": "parquet_code", "license": "Apache-2.0", "license_url": "https://www.apache.org/licenses/LICENSE-2.0",
     "attribution": "github-code-clean by CodeParrot (Apache-2.0 dataset; each file keeps its own permissive licence)",
     "description": "Real source files in C, C++, Go, Rust, Java, JavaScript, TypeScript, PHP, Ruby, shell, SQL and more.",
     "sharded": True,
     "files": [{"path": "data/train-00000-of-00880.parquet", "size": 355122552, "role": "train",
                "sha256": "c05e4cad93aac3f978a2385f8c055a10d247b107afd8bf9cb8c762f8403bdc0f"},
               {"path": "data/train-00001-of-00880.parquet", "size": 361424967, "role": "train",
                "sha256": "2e1b2e8bc5823fd68a80a036f1a5db894aa89bd491992bda2dfd96c41187025f"}]},
]
