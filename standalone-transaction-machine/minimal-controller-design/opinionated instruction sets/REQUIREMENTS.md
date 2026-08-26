# Minimal Opinionated Instruction Set Requirements

This document defines the requirements for the opinionated instruction-set caller that uses `initial.py` for interrogation and the simplified transaction layer for execution.

| ID | Requirement |
|---|---|
| OIS-001 | The caller must use `initial.py` as the interrogation script source. |
| OIS-002 | The caller must read the literal text of `initial.py` and pass that text as the script argument to `do_transaction(...)`. |
| OIS-003 | Before invoking the interrogation transaction, the caller must choose an explicit receipt path for that interrogation. |
| OIS-004 | Interrogation receipts must be written under a caller-selected interrogation-receipts folder. |
| OIS-005 | The caller must pass the selected interrogation receipt path to `do_transaction(...)` through the transaction receipt-path argument. |
| OIS-006 | The interrogation transaction must run to completion before the caller proceeds to the next instruction-set step. |
| OIS-007 | After the interrogation transaction ends, the caller must open the receipt at the exact interrogation receipt path it supplied. |
| OIS-008 | The caller must mechanically locate the final valid generated script in the interrogation receipt by parsing recorded stdin events and extracting the JSON object whose exact shape is `{"script":"<script>"}`. |
| OIS-009 | The caller must extract only the literal script text from that receipt event; the interrogation receipt itself must not be passed into the next transaction. |
| OIS-010 | Before invoking the execution transaction, the caller must choose a new explicit receipt path for execution. |
| OIS-011 | Execution receipts must be written under a caller-selected execution-receipts folder distinct from the interrogation-receipts folder. |
| OIS-012 | The caller must invoke `do_transaction(...)` a second time using the extracted script text as the script argument and the new execution receipt path as the receipt-path argument. |
| OIS-013 | The second transaction must execute the extracted generated script as its supplied script. |
| OIS-014 | The second transaction must write its receipt to the explicit execution receipt path supplied by the caller. |
| OIS-015 | The caller's knowledge of whether a transaction is interrogation or execution is expressed through which receipt folder/path it supplies; the transaction layer itself is not required to classify receipts by purpose. |
| OIS-016 | Interrogation and execution receipts are not required to contain explicit parent/child, planning/execution, or receipt-to-receipt linkage metadata. |
| OIS-017 | If a later consumer needs to associate an interrogation receipt with an execution receipt, it may do so mechanically by comparing the generated script extracted from the interrogation receipt with the exact script recorded as executed in a candidate execution receipt. |
| OIS-018 | `initial.py` must emit all outbound packets through the same stdout emission function. |
| OIS-019 | `initial.py` must validate each stdin response against the exact expected shape for its current stage. |
| OIS-020 | If a received stdin object is invalid, `initial.py` must emit one stdout packet that contains both the validation error and the exact prior request message, then wait for another stdin response for the same stage. |
| OIS-021 | The final generated-script response must be validated with the same retry behavior and must have the exact shape `{"script":"<script>"}` with a string value. |
| OIS-022 | After a valid final script response is received, `initial.py` must emit one non-instructional conversational closing message through the normal stdout emission path. |
| OIS-023 | `initial.py` must perform no further stdin reads or semantic requests after the closing message and must then terminate naturally by reaching the end of the script. |
| OIS-024 | The caller must rely on completion of `do_transaction(...)` as the boundary indicating that the child script has ended and the transaction receipt has been finalized at the supplied receipt path. |

## Intended sequence

```text
read literal initial.py
→ choose interrogation receipt path
→ do_transaction(initial.py text, interrogation receipt path)
→ interrogation ends and receipt is finalized
→ open interrogation receipt
→ mechanically extract generated script text
→ choose execution receipt path
→ do_transaction(generated script text, execution receipt path)
→ execution ends and execution receipt is finalized
```

The receipt folders provide coarse purpose separation. No additional receipt-linkage machinery is required by this instruction set.
