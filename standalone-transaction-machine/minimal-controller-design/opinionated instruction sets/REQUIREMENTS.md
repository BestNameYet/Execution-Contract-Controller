# Minimal Opinionated Instruction Set Requirements

This document defines the requirements for the opinionated instruction-set caller that uses `initial.py` for interrogation and the simplified transaction layer for execution.

| ID | Requirement | Status | Code location / evidence |
|---|---|---|---|
| OIS-001 | The caller must use `initial.py` as the interrogation script source. | MET | `minimal instruction set.py`: `INITIAL_PATH = HERE / "initial.py"`. |
| OIS-002 | The caller must read the literal text of `initial.py` and pass that text as the script argument to `do_transaction(...)`. | MET | `minimal instruction set.py`: `run()` reads `INITIAL_PATH.read_text(...)` into `initial_script`, then passes `initial_script` as the first argument to `do_transaction(...)`. |
| OIS-003 | Before invoking the interrogation transaction, the caller must choose an explicit receipt path for that interrogation. | NOT MET | `minimal instruction set.py` defines only `RECEIPT_DIR`; no explicit interrogation receipt-file path is chosen. |
| OIS-004 | Interrogation receipts must be written under a caller-selected interrogation-receipts folder. | PARTIAL | `minimal instruction set.py`: `RECEIPT_DIR = HERE / "transaction-receipts"` and `receipt_dir=RECEIPT_DIR`. A receipt directory is selected, but it is not an interrogation-specific folder. |
| OIS-005 | The caller must pass the selected interrogation receipt path to `do_transaction(...)` through the transaction receipt-path argument. | NOT MET | `minimal instruction set.py`: `run()` passes `receipt_dir=RECEIPT_DIR`, not an explicit receipt-file path. |
| OIS-006 | The interrogation transaction must run to completion before the caller proceeds to the next instruction-set step. | MET | `minimal instruction set.py`: `receipt = do_transaction(...)` completes before `extract_generated_script(receipt)` is called. |
| OIS-007 | After the interrogation transaction ends, the caller must open the receipt at the exact interrogation receipt path it supplied. | NOT MET | `minimal instruction set.py` does not open a physical receipt file after the transaction; it uses the object returned by `do_transaction(...)`. |
| OIS-008 | The caller must mechanically locate the final valid generated script in the interrogation receipt by parsing recorded stdin events and extracting the JSON object whose exact shape is `{"script":"<script>"}`. | PARTIAL | `minimal instruction set.py`: `extract_generated_script()` scans recorded `stdin` events in reverse and parses JSON, but accepts any object containing a string-valued `script` key rather than requiring exact shape `{"script": ...}`. It also operates on the returned receipt object rather than the physical receipt file. |
| OIS-009 | The caller must extract only the literal script text from that receipt event; the interrogation receipt itself must not be passed into the next transaction. | PARTIAL | `minimal instruction set.py`: `extract_generated_script()` returns only `value["script"]`, and `run()` returns that string. No second transaction is currently implemented, so the handoff to a next transaction is not yet present. |
| OIS-010 | Before invoking the execution transaction, the caller must choose a new explicit receipt path for execution. | NOT MET | No execution-transaction receipt path is defined in `minimal instruction set.py`. |
| OIS-011 | Execution receipts must be written under a caller-selected execution-receipts folder distinct from the interrogation-receipts folder. | NOT MET | No execution-receipts folder is defined in `minimal instruction set.py`. |
| OIS-012 | The caller must invoke `do_transaction(...)` a second time using the extracted script text as the script argument and the new execution receipt path as the receipt-path argument. | NOT MET | `minimal instruction set.py` contains only one `do_transaction(...)` invocation. |
| OIS-013 | The second transaction must execute the extracted generated script as its supplied script. | NOT MET | No second `do_transaction(...)` invocation exists. |
| OIS-014 | The second transaction must write its receipt to the explicit execution receipt path supplied by the caller. | NOT MET | No execution transaction or execution receipt path exists. |
| OIS-015 | The caller's knowledge of whether a transaction is interrogation or execution is expressed through which receipt folder/path it supplies; the transaction layer itself is not required to classify receipts by purpose. | NOT MET | The current caller defines only one generic `transaction-receipts` directory and does not distinguish interrogation from execution paths. |
| OIS-016 | `initial.py` must emit all outbound packets through the same stdout emission function. | MET | `initial.py`: `emit()` is the sole stdout writer; question, answer, script, retry, and closing packets all call `emit(...)`. |
| OIS-017 | `initial.py` must validate each stdin response against the exact expected shape for its current stage. | MET | `initial.py`: `validate_q1()`, `validate_answer()`, and `validate_script()` require exact key sets and expected value types; `receive_valid()` applies the stage validator. |
| OIS-018 | If a received stdin object is invalid, `initial.py` must emit one stdout packet that contains both the validation error and the exact prior request message, then wait for another stdin response for the same stage. | MET | `initial.py`: `receive_valid()` loops; on error it emits one object containing both `"error"` and `"repeat": previous_message`, then reads stdin again. |
| OIS-019 | The final generated-script response must be validated with the same retry behavior and must have the exact shape `{"script":"<script>"}` with a string value. | MET | `initial.py`: final stage calls `receive_valid(script_request, validate_script)`; `validate_script()` requires exactly the `script` key and a string value. |
| OIS-020 | After a valid final script response is received, `initial.py` must emit one non-instructional conversational closing message through the normal stdout emission path. | MET | `initial.py`: after `receive_valid(script_request, validate_script)`, it calls `emit({"message": "Thanks, that completes the interrogation."})`. |
| OIS-021 | `initial.py` must perform no further stdin reads or semantic requests after the closing message and must then terminate naturally by reaching the end of the script. | MET | `initial.py`: the closing `emit(...)` is the final statement in `main()`; control returns naturally and the module then reaches the end after `main()` completes. |
| OIS-022 | The caller must rely on completion of `do_transaction(...)` as the boundary indicating that the child script has ended and the transaction receipt has been finalized at the supplied receipt path. | PARTIAL | `minimal instruction set.py`: the caller waits synchronously for `do_transaction(...)` to return before continuing, but it does not supply or subsequently use an explicit receipt-file path. |

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

The receipt folders provide coarse purpose separation.
