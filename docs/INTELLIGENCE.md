# MOTH Intelligence (0.5.1)

0.5.1 adds the systems that decide *how* MOTH answers and *what* it learns from. Everything here runs on
MOTH Cloud with real storage and is controlled from MOTH Code (Settings → Intelligence & privacy, and
Owner Dashboard → Intelligence).

## Intelligence Router

Every chat request is classified by what it needs (conversation, knowledge, writing, reasoning, maths,
code). The router ranks the available providers by their **benchmarked** score for that capability, then
by measured latency, and tries them in order; a provider that fails is skipped and its failure counted.
Providers:

| Provider | When it is used |
| --- | --- |
| MOTH (native) | The deployed MOTH model on this server. Scores come from its capability benchmarks. |
| External (OpenAI-compatible) | **Off by default.** Only when the Owner configures one *and* turns on `external_ai_enabled`, and only for users who allowed external models. |

If no model can answer, the error says why in plain words ("No MOTH model is deployed on this server
yet", "MOTH Cloud inference is turned off by the Owner", …). Answers stream token by token
(`POST /v1/chat`, newline-delimited JSON events: `start`, `delta`, optional `replace`, `done`).

## Knowledge Engine

* Shared knowledge is added by the Owner; private knowledge belongs to one user and is never visible
  to anyone else (searches, citations and deletions are scoped to the owner of each document).
* A document's identity is its source (or title). New text under the same source creates a new
  version and supersedes the old one (kept for history); identical text is never stored twice.
* Text is chunked (~900 characters) and ranked with BM25. Answers cite the sources they were given
  (`[1]`, `[2]`), shown under the answer in MOTH Code.

## Feedback learning (with consent)

Users rate answers and say what went wrong. **The prompt and answer are stored only if the user turned
on "Help improve MOTH"** (off by default); otherwise only the rating, category and model are kept.
Recurring weaknesses are computed per capability. Only Owner-approved feedback from consenting users
becomes training data (corrected answers and well-rated answers), added to the next corpus build as its
own source.

## Smart Dataset Library and Data Factory

Approved datasets (all allow training a commercially offered model; attribution and share-alike terms
are recorded in every build's `ATTRIBUTION.md`):

| Dataset | Capability | License | Files used |
| --- | --- | --- | --- |
| TinyStories (Eldan & Li) | language | CDLA-Sharing-1.0 | `TinyStoriesV2-GPT4-valid.txt`, `TinyStories-valid.txt` (42 MB) |
| Databricks Dolly 15k | conversation, writing, knowledge | CC-BY-SA-3.0 | full (13 MB) |
| OpenAssistant oasst1 | conversation | Apache-2.0 | ready trees, English, best-ranked paths (34 MB) |
| Simple English Wikipedia 2023-11-01 | knowledge | CC-BY-SA-3.0 | full (157 MB), capped to a balanced share |
| GSM8K | maths | MIT | train (test held out for benchmarks) |
| AI2 ARC | reasoning | CC-BY-SA-4.0 | Easy + Challenge train (ARC-Easy test held out) |
| MBPP | code | CC-BY-4.0 | train/validation/prompt (test held out) |
| Python standard library | code | PSF-2.0 | local, no download |

Every file is pinned to an exact upstream revision, size and SHA-256 and is verified before use;
downloads resume, happen once and are reused. Newer upstream revisions are detected ("Check for dataset
updates") and used only after the Owner approves them, with their own checksums.

A build: normalise text → scrub e-mail addresses, phone numbers and keys → quality-score (measurable
signals; separate rules for prose, conversations and code) → remove benchmark overlap (13-word
decontamination against the held-out benchmark prompts and tests) → remove exact and near duplicates
(MinHash over word 5-grams, Jaccard ≥ 0.8) across all sources → write per-domain files, a held-out slice
per domain and a manifest (pinned sources, every filter's counts, content hash). The same pins and
configuration produce the same corpus (tested). Each domain is tokenized with the model lineage's
tokenizer and registered as an approved training dataset.

First real build (this repository's foundation corpus): 35.2M training tokens — knowledge 18.1M,
language 9.9M, code 2.5M, conversation 2.4M, maths 1.0M, writing 0.9M, reasoning 0.4M; 2.6k
benchmark-overlapping and ~400 duplicate records removed.

## Curriculum

Stages build on each other (never from scratch): **foundation** (language and knowledge) →
**conversation** → **skills** (maths, reasoning, code) → **balanced**. A stage ends when its token
budget is spent or held-out loss plateaus (< 1% over three promotions). Mixture weights follow stage
priorities, are shifted toward measured weaknesses (up to 2.5×), cap repetition of small datasets
(at most 4 passes) and keep a replay share for every learned domain to limit forgetting.

## Weakness Detection

Capability benchmarks run on held-out data only (never trained on):

| Suite | Measures |
| --- | --- |
| Maths | GSM8K test, final number exact match |
| Reasoning | ARC-Easy test, multiple choice by log-likelihood (25% = chance) |
| Code | MBPP test, generated code **executed** against its tests (pass@1) in a limited subprocess |
| Instruction following | held-out conversation prompts answered with a proper ending, no degeneration |
| Held-out loss | per domain (language, knowledge, conversation, writing, maths, reasoning, code) |
| Safety | clearly harmful requests refused by the serving pipeline |

Weakness = distance from the next target relative to chance, raised for regressions against the parent
model and for recurring negative feedback. The ranking drives the curriculum and the recommendations
shown to the Owner. Capabilities without measurements are listed as "not measured", never estimated.

## Safety baseline

MOTH Cloud refuses requests that clearly seek serious harm (weapons, malware, hard drugs, violence) with
a small rule set on by default (`safety_baseline` flag; the Owner can turn it off). The desktop app's
local policy is unchanged.
