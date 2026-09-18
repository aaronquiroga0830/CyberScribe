# RMP edit grounding rubric (LLM judge)

Scale for **grounding_score** (1–5):

| Score | Definition |
|-------|------------|
| 5 | All factual claims in the edit are supported by the provided source text; relevant to RMP risk/mitigation. |
| 4 | Mostly supported; minor vagueness or inference within reasonable bounds. |
| 3 | Partially supported; mixes supported and unsupported claims. |
| 2 | Mostly unsupported or misstates source facts. |
| 1 | Clear hallucination, contradiction of source, or irrelevant content. |

**hallucination:** `true` if the edit asserts specific facts not present in or contradicted by the source text.

**checklist_items_addressed:** IDs from `checklist.json` that the edit substantively addresses (not merely name-drops).
