# Results

| Model | Neutral pass rate | Hinted pass rate | Gap (hinted - neutral) |
|---|---|---|---|
| openrouter:cohere/north-mini-code:free | 22/40 (55%) | 31/40 (78%) | +22 pp |
| openrouter:nvidia/nemotron-3-super-120b-a12b:free | 29/40 (72%) | 33/40 (82%) | +10 pp |
| openrouter:nvidia/nemotron-3-ultra-550b-a55b:free | 30/40 (75%) | 29/40 (72%) | -3 pp |
| openrouter:nvidia/nemotron-3.5-lightning:free | 24/40 (60%) | 24/40 (60%) | +0 pp |
| openrouter:openai/gpt-4.1 | 16/40 (40%) | 39/40 (98%) | +57 pp |
| openrouter:poolside/laguna-s-2.1:free | 12/40 (30%) | 28/40 (70%) | +40 pp |
| openrouter:poolside/laguna-xs-2.1:free | 21/40 (52%) | 26/40 (65%) | +12 pp |

Samples per (task, condition): N=5; temperature=1.0; run date 2026-08-13T13:18:34+00:00.
Environment: Python 3.14.3, fastapi-loopguard 0.6.1, threshold 50 ms.
Judge self-check error rate: 0/16.

## Per-task breakdown (passed/n)

| Task | openrouter:cohere/north-mini-code:free neutral | openrouter:cohere/north-mini-code:free hinted | openrouter:nvidia/nemotron-3-super-120b-a12b:free neutral | openrouter:nvidia/nemotron-3-super-120b-a12b:free hinted | openrouter:nvidia/nemotron-3-ultra-550b-a55b:free neutral | openrouter:nvidia/nemotron-3-ultra-550b-a55b:free hinted | openrouter:nvidia/nemotron-3.5-lightning:free neutral | openrouter:nvidia/nemotron-3.5-lightning:free hinted | openrouter:openai/gpt-4.1 neutral | openrouter:openai/gpt-4.1 hinted | openrouter:poolside/laguna-s-2.1:free neutral | openrouter:poolside/laguna-s-2.1:free hinted | openrouter:poolside/laguna-xs-2.1:free neutral | openrouter:poolside/laguna-xs-2.1:free hinted |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| 01-user-lookup | 5/5 | 5/5 | 5/5 | 5/5 | 5/5 | 5/5 | 4/5 | 4/5 | 5/5 | 5/5 | 5/5 | 5/5 | 5/5 | 5/5 |
| 02-price-fanout | 5/5 | 5/5 | 5/5 | 4/5 | 5/5 | 5/5 | 5/5 | 4/5 | 2/5 | 4/5 | 3/5 | 4/5 | 5/5 | 5/5 |
| 03-report-export | 2/5 | 4/5 | 5/5 | 5/5 | 3/5 | 3/5 | 5/5 | 3/5 | 0/5 | 5/5 | 1/5 | 4/5 | 4/5 | 3/5 |
| 04-image-thumbnail | 0/5 | 5/5 | 0/5 | 5/5 | 0/5 | 4/5 | 0/5 | 4/5 | 0/5 | 5/5 | 0/5 | 5/5 | 0/5 | 5/5 |
| 05-audit-log | 3/5 | 4/5 | 4/5 | 4/5 | 4/5 | 2/5 | 0/5 | 1/5 | 5/5 | 5/5 | 1/5 | 1/5 | 1/5 | 1/5 |
| 06-document-save | 2/5 | 1/5 | 4/5 | 4/5 | 4/5 | 5/5 | 5/5 | 3/5 | 0/5 | 5/5 | 0/5 | 3/5 | 1/5 | 2/5 |
| 07-legacy-billing | 1/5 | 3/5 | 2/5 | 1/5 | 5/5 | 2/5 | 0/5 | 0/5 | 4/5 | 5/5 | 1/5 | 3/5 | 2/5 | 2/5 |
| 08-order-pipeline | 4/5 | 4/5 | 4/5 | 5/5 | 4/5 | 3/5 | 5/5 | 5/5 | 0/5 | 5/5 | 1/5 | 3/5 | 3/5 | 3/5 |
