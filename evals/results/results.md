# Results

## Headline: blocking verdicts per condition (blocked/measured)

Denominators count only samples whose endpoint actually ran. Samples that failed to import, or were rejected before the endpoint body, were never tested for blocking and are excluded.

| Model | Neutral | Hinted | Unmeasured (neutral/hinted) |
|---|---|---|---|
| openrouter:cohere/north-mini-code:free | 7/32 (22%) | 0/31 (0%) | 8/9 |
| openrouter:nvidia/nemotron-3-super-120b-a12b:free | 5/33 (15%) | 0/33 (0%) | 7/7 |
| openrouter:nvidia/nemotron-3-ultra-550b-a55b:free | 3/38 (8%) | 0/33 (0%) | 2/7 |
| openrouter:nvidia/nemotron-3.5-lightning:free | 1/25 (4%) | 0/23 (0%) | 15/17 |
| openrouter:openai/gpt-4.1 | 21/37 (57%) | 0/40 (0%) | 3/0 |
| openrouter:poolside/laguna-s-2.1:free | 18/38 (47%) | 0/32 (0%) | 2/8 |
| openrouter:poolside/laguna-xs-2.1:free | 5/30 (17%) | 0/30 (0%) | 10/10 |

## Context: overall pass rates (blocking AND functional failures)

These conflate the two failure kinds. Read them next to the table above, not instead of it.

| Model | Neutral pass rate | Hinted pass rate | Gap (hinted - neutral) |
|---|---|---|---|
| openrouter:cohere/north-mini-code:free | 23/40 (57%) | 27/40 (68%) | +10 pp |
| openrouter:nvidia/nemotron-3-super-120b-a12b:free | 26/40 (65%) | 33/40 (82%) | +17 pp |
| openrouter:nvidia/nemotron-3-ultra-550b-a55b:free | 35/40 (88%) | 33/40 (82%) | -5 pp |
| openrouter:nvidia/nemotron-3.5-lightning:free | 24/40 (60%) | 23/40 (57%) | -3 pp |
| openrouter:openai/gpt-4.1 | 16/40 (40%) | 40/40 (100%) | +60 pp |
| openrouter:poolside/laguna-s-2.1:free | 12/40 (30%) | 24/40 (60%) | +30 pp |
| openrouter:poolside/laguna-xs-2.1:free | 22/40 (55%) | 22/40 (55%) | +0 pp |

Samples per (task, condition): N=5; temperature=1.0; run date 2026-08-16T21:42:31+00:00.
Environment: Python 3.14.3, fastapi-loopguard 0.6.1, threshold 50 ms.
Judge self-check error rate: 0/2.

## Per-task breakdown (passed/n)

| Task | openrouter:cohere/north-mini-code:free neutral | openrouter:cohere/north-mini-code:free hinted | openrouter:nvidia/nemotron-3-super-120b-a12b:free neutral | openrouter:nvidia/nemotron-3-super-120b-a12b:free hinted | openrouter:nvidia/nemotron-3-ultra-550b-a55b:free neutral | openrouter:nvidia/nemotron-3-ultra-550b-a55b:free hinted | openrouter:nvidia/nemotron-3.5-lightning:free neutral | openrouter:nvidia/nemotron-3.5-lightning:free hinted | openrouter:openai/gpt-4.1 neutral | openrouter:openai/gpt-4.1 hinted | openrouter:poolside/laguna-s-2.1:free neutral | openrouter:poolside/laguna-s-2.1:free hinted | openrouter:poolside/laguna-xs-2.1:free neutral | openrouter:poolside/laguna-xs-2.1:free hinted |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| 01-user-lookup | 5/5 | 5/5 | 5/5 | 5/5 | 5/5 | 5/5 | 4/5 | 4/5 | 5/5 | 5/5 | 5/5 | 5/5 | 5/5 | 5/5 |
| 02-price-fanout | 5/5 | 5/5 | 5/5 | 5/5 | 5/5 | 5/5 | 5/5 | 5/5 | 2/5 | 5/5 | 3/5 | 2/5 | 5/5 | 4/5 |
| 03-report-export | 3/5 | 3/5 | 2/5 | 4/5 | 5/5 | 5/5 | 2/5 | 0/5 | 0/5 | 5/5 | 1/5 | 4/5 | 5/5 | 3/5 |
| 04-image-thumbnail | 0/5 | 2/5 | 0/5 | 5/5 | 3/5 | 5/5 | 3/5 | 5/5 | 0/5 | 5/5 | 0/5 | 3/5 | 0/5 | 2/5 |
| 05-audit-log | 3/5 | 4/5 | 4/5 | 4/5 | 4/5 | 3/5 | 0/5 | 1/5 | 5/5 | 5/5 | 1/5 | 1/5 | 1/5 | 1/5 |
| 06-document-save | 2/5 | 1/5 | 4/5 | 4/5 | 4/5 | 5/5 | 5/5 | 3/5 | 0/5 | 5/5 | 0/5 | 3/5 | 1/5 | 2/5 |
| 07-legacy-billing | 1/5 | 3/5 | 2/5 | 1/5 | 5/5 | 2/5 | 0/5 | 0/5 | 4/5 | 5/5 | 1/5 | 3/5 | 2/5 | 2/5 |
| 08-order-pipeline | 4/5 | 4/5 | 4/5 | 5/5 | 4/5 | 3/5 | 5/5 | 5/5 | 0/5 | 5/5 | 1/5 | 3/5 | 3/5 | 3/5 |
