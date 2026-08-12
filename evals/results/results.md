# Results

| Model | Neutral pass rate | Hinted pass rate | Gap (hinted - neutral) |
|---|---|---|---|
| openrouter:nvidia/nemotron-3.5-lightning:free | 24/40 (60%) | 24/40 (60%) | +0 pp |
| openrouter:openai/gpt-4.1 | 16/40 (40%) | 39/40 (98%) | +57 pp |

Samples per (task, condition): N=5; temperature=1.0; run date 2026-08-12T15:42:15+00:00.
Environment: Python 3.14.3, fastapi-loopguard 0.6.1, threshold 50 ms.
Judge self-check error rate: 0/16.

## Per-task breakdown (passed/n)

| Task | openrouter:nvidia/nemotron-3.5-lightning:free neutral | openrouter:nvidia/nemotron-3.5-lightning:free hinted | openrouter:openai/gpt-4.1 neutral | openrouter:openai/gpt-4.1 hinted |
|---|---|---|---|---|
| 01-user-lookup | 4/5 | 4/5 | 5/5 | 5/5 |
| 02-price-fanout | 5/5 | 4/5 | 2/5 | 4/5 |
| 03-report-export | 5/5 | 3/5 | 0/5 | 5/5 |
| 04-image-thumbnail | 0/5 | 4/5 | 0/5 | 5/5 |
| 05-audit-log | 0/5 | 1/5 | 5/5 | 5/5 |
| 06-document-save | 5/5 | 3/5 | 0/5 | 5/5 |
| 07-legacy-billing | 0/5 | 0/5 | 4/5 | 5/5 |
| 08-order-pipeline | 5/5 | 5/5 | 0/5 | 5/5 |
