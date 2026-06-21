# Retrieval Performance Evaluation Report

This report compares the retrieval and citation performance of three search paths:
- **Lexical**: SQLite FTS5 search.
- **Hybrid**: SQLite FTS5 + semantic reranking (all-MiniLM-L6-v2 embeddings).
- **Agent-facing**: Pydantic context response API with citation resolving.

## Aggregate Benchmark Summary

| Metric | Lexical | Hybrid | Agent-facing |
| :--- | :---: | :---: | :---: |
| **Dataset Recall@5** | 86.67% | 86.67% | 86.67% |
| **Variable Recall@5** | 66.67% | 66.67% | 66.67% |
| **Citation Accuracy** | 80.00% | 80.00% | 80.00% |
| **Dataset MRR** | 0.9111 | 0.9111 | 0.9111 |
| **Variable MRR** | 0.4704 | 0.4704 | 0.4704 |

## Per-Question Results Comparison

### Query: `BENE_ID` (ID: q1)

| Path | Dataset Recall@5 | Variable Recall@5 | Citation Accuracy | Dataset MRR | Variable MRR |
| :--- | :---: | :---: | :---: | :---: | :---: |
| **Lexical** | 33.33% | 100.00% | 100.00% | 0.5000 | 0.5000 |
| **Hybrid** | 33.33% | 100.00% | 100.00% | 0.5000 | 0.5000 |
| **Agent-facing** | 33.33% | 100.00% | 100.00% | 0.5000 | 0.5000 |

### Query: `Part D prescription drug event` (ID: q2)

| Path | Dataset Recall@5 | Variable Recall@5 | Citation Accuracy | Dataset MRR | Variable MRR |
| :--- | :---: | :---: | :---: | :---: | :---: |
| **Lexical** | 0.00% | 0.00% | 0.00% | 0.1667 | 0.0000 |
| **Hybrid** | 0.00% | 0.00% | 0.00% | 0.1667 | 0.0000 |
| **Agent-facing** | 0.00% | 0.00% | 0.00% | 0.1667 | 0.0000 |

### Query: `Medicare Advantage encounter carrier` (ID: q3)

| Path | Dataset Recall@5 | Variable Recall@5 | Citation Accuracy | Dataset MRR | Variable MRR |
| :--- | :---: | :---: | :---: | :---: | :---: |
| **Lexical** | 100.00% | 0.00% | 100.00% | 1.0000 | 0.0000 |
| **Hybrid** | 100.00% | 0.00% | 100.00% | 1.0000 | 0.0000 |
| **Agent-facing** | 100.00% | 0.00% | 100.00% | 1.0000 | 0.0000 |

### Query: `inpatient fee-for-service` (ID: q4)

| Path | Dataset Recall@5 | Variable Recall@5 | Citation Accuracy | Dataset MRR | Variable MRR |
| :--- | :---: | :---: | :---: | :---: | :---: |
| **Lexical** | 100.00% | 0.00% | 100.00% | 1.0000 | 0.0000 |
| **Hybrid** | 100.00% | 0.00% | 100.00% | 1.0000 | 0.0000 |
| **Agent-facing** | 100.00% | 0.00% | 100.00% | 1.0000 | 0.0000 |

### Query: `dual eligibility code January` (ID: q5)

| Path | Dataset Recall@5 | Variable Recall@5 | Citation Accuracy | Dataset MRR | Variable MRR |
| :--- | :---: | :---: | :---: | :---: | :---: |
| **Lexical** | 100.00% | 100.00% | 100.00% | 1.0000 | 0.5000 |
| **Hybrid** | 100.00% | 100.00% | 100.00% | 1.0000 | 0.5000 |
| **Agent-facing** | 100.00% | 100.00% | 100.00% | 1.0000 | 0.5000 |

### Query: `MedPAR claim residual payment indicator` (ID: q6)

| Path | Dataset Recall@5 | Variable Recall@5 | Citation Accuracy | Dataset MRR | Variable MRR |
| :--- | :---: | :---: | :---: | :---: | :---: |
| **Lexical** | 100.00% | 100.00% | 0.00% | 1.0000 | 0.5000 |
| **Hybrid** | 100.00% | 100.00% | 0.00% | 1.0000 | 0.5000 |
| **Agent-facing** | 100.00% | 100.00% | 0.00% | 1.0000 | 0.5000 |

### Query: `Quality composite score modifier` (ID: q7)

| Path | Dataset Recall@5 | Variable Recall@5 | Citation Accuracy | Dataset MRR | Variable MRR |
| :--- | :---: | :---: | :---: | :---: | :---: |
| **Lexical** | 100.00% | 0.00% | 100.00% | 1.0000 | 0.0000 |
| **Hybrid** | 100.00% | 0.00% | 100.00% | 1.0000 | 0.0000 |
| **Agent-facing** | 100.00% | 0.00% | 100.00% | 1.0000 | 0.0000 |

### Query: `hha encounter claims` (ID: q8)

| Path | Dataset Recall@5 | Variable Recall@5 | Citation Accuracy | Dataset MRR | Variable MRR |
| :--- | :---: | :---: | :---: | :---: | :---: |
| **Lexical** | 100.00% | 0.00% | 100.00% | 1.0000 | 0.0556 |
| **Hybrid** | 100.00% | 0.00% | 100.00% | 1.0000 | 0.0556 |
| **Agent-facing** | 100.00% | 0.00% | 100.00% | 1.0000 | 0.0556 |

### Query: `Master Beneficiary Summary File CCW chronic conditions` (ID: q9)

| Path | Dataset Recall@5 | Variable Recall@5 | Citation Accuracy | Dataset MRR | Variable MRR |
| :--- | :---: | :---: | :---: | :---: | :---: |
| **Lexical** | 100.00% | 100.00% | 100.00% | 1.0000 | 1.0000 |
| **Hybrid** | 100.00% | 100.00% | 100.00% | 1.0000 | 1.0000 |
| **Agent-facing** | 100.00% | 100.00% | 100.00% | 1.0000 | 1.0000 |

### Query: `HEDIS Medicare Linked data` (ID: q10)

| Path | Dataset Recall@5 | Variable Recall@5 | Citation Accuracy | Dataset MRR | Variable MRR |
| :--- | :---: | :---: | :---: | :---: | :---: |
| **Lexical** | 66.67% | 100.00% | 100.00% | 1.0000 | 1.0000 |
| **Hybrid** | 66.67% | 100.00% | 100.00% | 1.0000 | 1.0000 |
| **Agent-facing** | 66.67% | 100.00% | 100.00% | 1.0000 | 1.0000 |

### Query: `dme encounter durable medical equipment` (ID: q11)

| Path | Dataset Recall@5 | Variable Recall@5 | Citation Accuracy | Dataset MRR | Variable MRR |
| :--- | :---: | :---: | :---: | :---: | :---: |
| **Lexical** | 100.00% | 100.00% | 100.00% | 1.0000 | 1.0000 |
| **Hybrid** | 100.00% | 100.00% | 100.00% | 1.0000 | 1.0000 |
| **Agent-facing** | 100.00% | 100.00% | 100.00% | 1.0000 | 1.0000 |

### Query: `Medicaid LTSS dual eligible months` (ID: q12)

| Path | Dataset Recall@5 | Variable Recall@5 | Citation Accuracy | Dataset MRR | Variable MRR |
| :--- | :---: | :---: | :---: | :---: | :---: |
| **Lexical** | 100.00% | 100.00% | 100.00% | 1.0000 | 0.5000 |
| **Hybrid** | 100.00% | 100.00% | 100.00% | 1.0000 | 0.5000 |
| **Agent-facing** | 100.00% | 100.00% | 100.00% | 1.0000 | 0.5000 |

### Query: `Claim Residual Payment Indicator Code hospice` (ID: q13)

| Path | Dataset Recall@5 | Variable Recall@5 | Citation Accuracy | Dataset MRR | Variable MRR |
| :--- | :---: | :---: | :---: | :---: | :---: |
| **Lexical** | 100.00% | 100.00% | 0.00% | 1.0000 | 0.5000 |
| **Hybrid** | 100.00% | 100.00% | 0.00% | 1.0000 | 0.5000 |
| **Agent-facing** | 100.00% | 100.00% | 0.00% | 1.0000 | 0.5000 |

### Query: `Master Beneficiary Summary File Base` (ID: q14)

| Path | Dataset Recall@5 | Variable Recall@5 | Citation Accuracy | Dataset MRR | Variable MRR |
| :--- | :---: | :---: | :---: | :---: | :---: |
| **Lexical** | 100.00% | 100.00% | 100.00% | 1.0000 | 1.0000 |
| **Hybrid** | 100.00% | 100.00% | 100.00% | 1.0000 | 1.0000 |
| **Agent-facing** | 100.00% | 100.00% | 100.00% | 1.0000 | 1.0000 |

### Query: `individual NPI number cec provider` (ID: q15)

| Path | Dataset Recall@5 | Variable Recall@5 | Citation Accuracy | Dataset MRR | Variable MRR |
| :--- | :---: | :---: | :---: | :---: | :---: |
| **Lexical** | 100.00% | 100.00% | 100.00% | 1.0000 | 0.5000 |
| **Hybrid** | 100.00% | 100.00% | 100.00% | 1.0000 | 0.5000 |
| **Agent-facing** | 100.00% | 100.00% | 100.00% | 1.0000 | 0.5000 |

