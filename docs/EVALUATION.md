# Evaluation

How each model was built and measured, including the results that were less flattering than expected. Every number here comes from a JSON report in [metrics/](metrics/).

## Reproduce

```bash
cd backend
python -m app.ml.train --report-dir ../docs/metrics
python -m app.rag.evaluate --report ../docs/metrics/rag.json      # after seeding
python -m app.ml.benchmark_uci --csv PATH --report ../docs/metrics/uci_benchmark.json
```

Training on an Intel i5-12500H with no GPU takes about 2 minutes.

## Data

### Synthetic history

[app/ml/synthetic.py](../backend/app/ml/synthetic.py) generates 18 months of tickets with a fixed seed: 15,747 rows, or 13,000 after removing 2,747 duplicate texts. No real or proprietary data is used.

The first version made all three text classifiers score exactly 0.9523. Identical scores from different algorithms meant they were all perfect except for injected label noise, so the number measured the noise and nothing else. Confidence was also meaningless, at over 90% on every ticket. The generator now adds what makes real tickets hard:

- Reporters describe symptoms, not causes. About 20% of tickets for overlapping topics are worded like a different topic.
- Vague tickets, typos, signatures, repeated monitoring alerts and 6% labelling mistakes.
- A queue simulation in which outcomes depend on staffing, backlog and time of day, plus randomness no model can see, and temporary staffing shortfalls absent from early data.

### Public benchmark

The [UCI Incident management process enriched event log](https://archive.ics.uci.edu/dataset/498/incident+management+process+enriched+event+log) by Amaral, Fantinato and Peres is an anonymised ServiceNow export of 141,712 events for 24,918 incidents. It is not included in this repository: download it from that page and check the terms there.

It has no ticket text, so it validates the SLA method only. The served model does not use it.

## Leakage controls

| Risk | Control |
| --- | --- |
| Target leakage | Features come from one function shared by training and serving, and only contain fields known at creation. A forbidden list is enforced at train time and by a test. |
| Duplicate leakage | Text is normalised and deduplicated before splitting. A test asserts that no text appears in both train and test. |
| Time leakage | All splits are chronological. |
| Unknown labels at the cutoff | An embargo removes every ticket opened within the usual resolution time of a split boundary. |
| Test contamination | Model selection and threshold tuning use validation data. The test split is scored once, for the selected model. |

The embargo replaced a simpler rule that dropped only tickets resolved after the cutoff. That rule looked safe but was biased: slow tickets are disproportionately breaches, so it deleted the outcomes being predicted. On the real log, validation showed a 9.5% breach rate against 38% overall.

## Category classification

Chronological 70/15/15 split with 1,950 test tickets.

| Candidate | Validation macro F1 | Confidence ECE |
| --- | --- | --- |
| Most frequent class | 0.030 | 0.863 |
| TF-IDF + naive Bayes | 0.821 | 0.172 |
| TF-IDF + logistic regression | 0.804 | 0.062 |
| **TF-IDF + calibrated linear SVM** | **0.819** | **0.071** |

Naive Bayes had the highest F1 by 0.0014 but useless confidence. Agents see this confidence, and low values send tickets to manual triage, so among models within 0.01 of the best F1 the one with the lowest ECE is selected.

Test results for the selected model:

| Measure | Value |
| --- | --- |
| Accuracy | 0.794 |
| Macro precision / recall / F1 | 0.799 / 0.794 / 0.795 |
| Top-3 accuracy | 0.914 |
| Confidence ECE | 0.037 |
| Macro F1 on unseen phrasing, 3-fold | **0.708** (std 0.068) |

The time split shares sentence templates between train and test, which real tickets would not. Unseen phrasing holds out whole templates, so **0.708 is the fairer estimate of generalisation**.

Per-class F1 ranges from 0.740 (software application) to 0.847 (hardware). The confusion matrix is in [metrics/category.json](metrics/category.json).

Confidence now carries information:

| Minimum confidence | Coverage | Accuracy |
| --- | --- | --- |
| 0.5 | 94.4% | 82.2% |
| 0.7 | 82.8% | 83.5% |
| 0.8 | 49.6% | 87.0% |

## Team routing

| Candidate | Validation accuracy | Top-3 |
| --- | --- | --- |
| **Category-to-team rule** | **0.739** | 0.954 |
| TF-IDF + logistic regression | 0.719 | 0.963 |

The rule won and ships. Test accuracy is 0.742, top-3 is 0.949. The generator assigns some topics to teams at random, so accuracy has a ceiling well below 1. Below 60% confidence a ticket goes to manual triage, and every override is recorded.

## SLA breach risk

Chronological splits: 9,310 train, 2,248 validation, 1,504 calibration, 2,363 test. Features: category, priority, impact, urgency, channel, team, time of day, team backlog and description length.

| Candidate | Validation ROC-AUC | Validation PR-AUC | Validation Brier |
| --- | --- | --- | --- |
| Base rate | 0.500 | 0.228 | 0.176 |
| Logistic regression | 0.743 | 0.488 | 0.150 |
| **LightGBM** | **0.764** | **0.547** | **0.142** |

LightGBM is justified here: it adds 0.059 PR-AUC over logistic regression.

Calibration was expected to help and did not. Sigmoid (Brier 0.14222) and isotonic (0.14243) were both worse than the raw model (0.14218) on validation, so none is applied. An earlier version always applied isotonic, which raised ECE from 0.016 to 0.026.

| Test measure | Model | Base rate |
| --- | --- | --- |
| ROC-AUC | 0.756 | 0.500 |
| PR-AUC | 0.541 | 0.240 |
| Brier | 0.150 | 0.183 |
| ECE | 0.022 | |

| Alert threshold | Flagged | Precision | Recall |
| --- | --- | --- | --- |
| 0.70 (default) | 2.7% | 95.2% | 10.6% |
| 0.25 (best validation F1) | 38.8% | 40.8% | 65.9% |

The default favours precision to avoid alert fatigue and catches only 1 in 10 breaches. Lowering `SLA_RISK_ALERT_THRESHOLD` trades the other way.

### Explaining a score

Each ticket shows what moved its score. For each group of facts, such as when a ticket was raised or its priority, the ticket is scored again with that group set to the training data's typical ticket, and the difference is shown in percentage points. Facts that belong together move together, so the comparison never describes an impossible ticket. The method works with any model, and it explains the model's behaviour, not the real world's.

It makes the simulator's strongest rule visible. P3 work does not start until the next working day, while its 24-hour clock keeps running, so in the simulated history 96.8% of P3 tickets raised at a weekend breach, against 33.1% on weekdays. Those tickets are 2.2% of the history, and the 0.70 alert flags 2.7% of test tickets, so the high precision above probably comes mostly from that one rule. The rule was left in place: changing the generator until the scores look better would be tuning the data, not the model.

## Real-data benchmark

The log is an event stream, so careless use leaks badly:

- `made_sla` changes during the life of 36.6% of incidents.
- The export is backfilled: a row in state `New` can already show `closed_code` and `resolved_by`.
- `sys_mod_count` and the reassignment and reopen counters rise as work happens.

The benchmark uses one row per incident, opening fields from the first event, and the outcome from the last. Usable data spans about 11 weeks and resolution can take weeks, so a single embargo sits before the test period, leaving 7,156 train, 1,789 validation and 5,841 test incidents.

| Test | ROC-AUC | PR-AUC | Brier | ECE |
| --- | --- | --- | --- | --- |
| **Leakage-safe (logistic regression selected)** | **0.707** | **0.439** | 0.322 | 0.394 |
| Deliberate leakage (LightGBM) | 0.985 | 0.974 | 0.120 | 0.253 |

Three findings:

1. **Leakage is worth 0.28 ROC-AUC here.** A 0.985 would look excellent and be useless, because those fields do not exist when a ticket opens.
2. **Ranking survives drift, probabilities do not.** The breach rate is 64% in March 2016 and 24% in April. Training data averaged 66% and test 24%, so the Brier score is far worse than a constant at the true test rate (about 0.18), even though ROC-AUC holds. Anyone reading these scores as probabilities would be misled until the model is recalibrated on recent data.
3. **The stronger model was not stronger.** LightGBM lost to logistic regression here (validation ROC-AUC 0.677 against 0.702).

## RAG

Corpus: 132 synthetic articles in 133 chunks, covering the eight support areas plus how the platform itself works. Questions were written by hand and paraphrased to avoid copying titles, but by the same author as the articles, so they are likely easier than real queries. There are 65 answerable and 14 unanswerable questions for tuning, and 67 and 18 for testing.

| Retrieval (test) | Vector | TF-IDF baseline |
| --- | --- | --- |
| Recall@1 | 0.888 | 0.843 |
| Recall@3 | 0.955 | 0.888 |
| Recall@5 | 0.963 | 0.933 |
| MRR | 0.926 | 0.886 |

| Generation (test, extractive provider) | Result |
| --- | --- |
| Answered | 63 of 67 |
| Answers citing a relevant source | 89% (56 of 63) |
| Unanswerable questions refused | 18 of 18 |
| Grounding score | 1.0, true by construction |

These scores are lower than the earlier run on 41 articles (Recall@3 1.000, MRR 0.976, 20 of 21 answered, 95% citation correctness). That does not mean the system got worse. The task got harder, with three times the articles, many close neighbours and three times the questions.

The grounding metric checks that answer sentences come from their cited sources. The extractive provider copies source sentences and cannot fail it. It will only be informative with a generative LLM, which has not been evaluated.

The evidence threshold of 0.37 has the best balanced accuracy on tuning questions (0.985). A larger corpus gives unrelated questions closer matches, which moved it up from 0.27. The margin is thin and the two groups overlap: across all questions the weakest answerable scored 0.244 and the strongest unanswerable 0.366, and 6 of the 132 answerable questions fall below the threshold.

The extractive provider used to refuse a second time when no single sentence reached a similarity of 0.3, a value that was never tuned. On tuning questions this refused 3 good answers and stopped no bad ones, so it now only trims an answer and never empties it.

The test split is not fully untouched. It was scored once with the new corpus (57 of 67 answered, 18 of 18 refused), then again after the sentence change and three article titles were corrected. Those changes were chosen from tuning questions alone, but 63 of 67 is slightly optimistic. An earlier threshold rule was also changed after seeing a test miss.

In a conversation, a message borrows the earlier topic only if it looks like a follow-up and finds a similarity below 0.55 by itself. That value comes from 18 hand-checked messages (follow-ups reached 0.539, new questions started at 0.571). It is a heuristic, and is not part of the evaluation above.

| Latency on a laptop CPU | p50 | p95 |
| --- | --- | --- |
| Retrieval, including embedding | 37 ms | 43 ms |
| Extractive generation | 99 ms | 301 ms |
