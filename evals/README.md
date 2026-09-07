# Retrieval evaluation

`retrieval_v1.jsonl` is the original 30-case baseline. `retrieval_v2.jsonl` is
a deterministic 300-case expansion with 240 answerable and 60 no-answer cases,
split into 180 tuning, 60 validation, and 60 frozen test cases.

Regenerate v2 after reviewing its intent phrases:

```powershell
python -m evals.build_retrieval_v2
```

Run the three live strategies with bounded concurrency:

```powershell
python -m evals.retrieval_eval `
  --dataset evals/datasets/retrieval_v2.jsonl `
  --execute-live `
  --strategies vector_only hybrid hybrid_rerank `
  --concurrency 5 `
  --output evals/reports/retrieval-v2.json
```

Reports expose both `raw_metrics` (retrieval/ranking quality before confidence
policy) and `accepted_metrics` (documents retained after low-confidence
rejection). Do not compare one metric family with the other.

V2 is a synthetic benchmark intended to broaden deterministic regression
coverage. Its cases are explicitly tagged and must not be treated as a
replacement for independently reviewed, anonymized production queries.

## Long-document comparison (separate synthetic benchmark)

`evals/corpus/long_v1/manifest.json` lists six expanded fictional handbooks
covering all 18 seed articles. `datasets/retrieval_long_v1.jsonl` contains 36
source/evidence-labelled questions and must use the new entrypoint, not the
title-based v1/v2 runner above:

```powershell
python -m evals.long_document_eval --action preview
python -m evals.long_document_eval --action bm25 --variant whole
python -m evals.long_document_eval --action bm25 --variant chunked
```

These commands are fully offline. Live import/evaluation requires both
`--execute-live` and a dedicated `LONG_DOCUMENT_EVAL_DATABASE_URL`; there is
no fallback to the app database. Keep whole/chunked variants in separate empty
databases. Source-level and stable evidence-level metrics are comparable;
chunk-level recall changes denominator when splitting changes.

See [the long-document evaluation guide](../docs/long-document-evaluation-guide.md)
for corpus review limitations, metric definitions, safe migration/import,
live comparison, and threshold calibration prerequisites.
