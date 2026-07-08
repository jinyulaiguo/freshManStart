# Transformer Architecture and Attention Mechanism

## 1. Abstract
We propose a new simple network architecture, the Transformer, based solely on attention mechanisms, dispensing with recurrence and convolutions entirely.

## 2. Attention
An attention function can be described as mapping a query and a set of key-value pairs to an output.
The output is computed as a weighted sum of the values.

```python
# Self Attention implementation block
def self_attention(query, key, value):
    scores = query @ key.T / sqrt(d_k)
    weights = softmax(scores)
    return weights @ value
```

---
*Created by Vaswani et al.*
