# Minimal Opinionated Instruction Set Requirements

This document defines requirements for this particular minimal opinionated instruction set, which uses `initial.py` for interrogation and the simplified transaction layer for execution.

| ID | Requirement | Status | Code location / evidence |
|---|---|---|---|
| OIS-001 | The caller must use `initial.py` as the interrogation script source. | MET | `minimal instruction set.py`: `INITIAL_PATH = HERE / "initial.py"`. |
| OIS-002 | The caller must read the literal text of `initial.py` and pass that text as the script argument to `do_transaction(...)`. | MET | `minimal instruction set.py`: `run()` reads `INITIAL_PATH.read_text(...)` into `initial_script`, then passes `initial_script` as the first argument to the first `do_transaction(...)`. |
| OIS-003 | Before invoking the interrogation transaction, the caller must choose an explicit receipt path for that interrogation. | MET | `minimal instruction set.py`: `run_id` is created and `interrogation_receipt_path = INTERROGATION_RECEIPT_DIR / f"interrogation_{run_id}.json"` is assigned before the first transaction call. |
| OIS-004 | Interrogation receipts must be written under a caller-selected interrogation-receipts folder. | MET | `minimal instruction set.py`: `INTERROGATION_RECEIPT_DIR = HERE / "interrogation-receipts"`; `interrogation_receipt_path` is created under that directory. |
| OIS-005 | The caller must pass the selected interrogation receipt path to `do_transaction(...)` through the transaction receipt-path argument. | MET | `minimal instruction set.py`: first `do_transaction(...)` passes `receipt_file=interrogation_receipt_path`. |
| OIS-006 | The interrogation transaction must run to completion before the caller proceeds to the next instruction-set step. | MET | `minimal instruction set.py`: the first synchronous `do_transaction(...)` call completes before `read_receipt(interrogation_receipt_path)` is executed. |
| OIS-007 | After the interrogation transaction ends, the caller must open the receipt at the exact interrogation receipt path it supplied. | MET | `minimal instruction set.py`: `read_receipt(interrogation_receipt_path)` reads the same path supplied as `receipt_file` to the first transaction. |
| OIS-008 | The caller must mechanically locate the final valid generated script in the interrogation receipt by parsing recorded stdin events and extracting the JSON object whose exact shape is `{"script":"<script>"}`. | MET | `minimal instruction set.py`: `extract_generated_script()` scans `events` in reverse, selects `stdin`, parses `event["data"]` as JSON, requires `set(value.keys()) == {"script"}`, requires a string value, and returns it. |
| OIS-009 | The caller must extract only the literal script text from that receipt event; the interrogation receipt itself must not be passed into the next transaction. | MET | `minimal instruction set.py`: `generated_script = extract_generated_script(interrogation_receipt)`; the second transaction receives `generated_script`, not `interrogation_receipt`. |
| OIS-010 | Before invoking the execution transaction, the caller must choose a new explicit receipt path for execution. | MET | `minimal instruction set.py`: `execution_receipt_path = EXECUTION_RECEIPT_DIR / f"execution_{run_id}.json"` is assigned before the second transaction call. |
| OIS-011 | Execution receipts must be written under a caller-selected execution-receipts folder distinct from the interrogation-receipts folder. | MET | `minimal instruction set.py`: `EXECUTION_RECEIPT_DIR = HERE / "execution-receipts"`, distinct from `INTERROGATION_RECEIPT_DIR`. |
| OIS-012 | The caller must invoke `do_transaction(...)` a second time using the extracted script text as the script argument and the new execution receipt path as the receipt-path argument. | MET | `minimal instruction set.py`: second `do_transaction(generated_script, receipt_file=execution_receipt_path)`. |
| OIS-013 | The second transaction must execute the extracted generated script as its supplied script. | MET | `minimal instruction set.py`: the exact `generated_script` returned by `extract_generated_script(...)` is the first argument to the second `do_transaction(...)`. |
| OIS-014 | The second transaction must write its receipt to the explicit execution receipt path supplied by the caller. | MET | `minimal instruction set.py`: second transaction passes `receipt_file=execution_receipt_path`; `transaction_layer.py` resolves explicit `receipt_file` directly and writes/verifies the receipt there. |
| OIS-015 | The caller's knowledge of whether a transaction is interrogation or execution is expressed through which receipt folder/path it supplies; the transaction layer itself is not required to classify receipts by purpose. | MET | `minimal instruction set.py` selects `interrogation-receipts/` for the first call and `execution-receipts/` for the second; both calls use the same neutral `do_transaction(...)`. |
| OIS-016 | `initial.py` must emit all outbound packets through the same stdout emission function. | MET | `initial.py`: `emit()` is the sole stdout writer; prompt capture, question generation, interrogation questions, script request, retry, and closing packets all call `emit(...)`. |
| OIS-017 | `initial.py` must validate each stdin response against the exact expected shape for its current stage. | MET | `initial.py`: `validate_user_prompt()`, `validate_q1()`, `validate_answer()`, and `validate_script()` require exact key sets and expected value types; `receive_valid()` applies the stage validator. |
| OIS-018 | If a received stdin object is invalid, `initial.py` must emit one stdout packet that contains both the validation error and the exact prior request message, then wait for another stdin response for the same stage. | MET | `initial.py`: `receive_valid()` loops; on error it emits one object containing both `"error"` and `"repeat": previous_message`, then reads stdin again. |
| OIS-019 | The final generated-script response must be validated with the same retry behavior and must have the exact shape `{"script":"<script>"}` with a string value. | MET | `initial.py`: final stage calls `receive_valid(script_request, validate_script)`; `validate_script()` requires exactly the `script` key and a string value. |
| OIS-020 | After a valid final script response is received, `initial.py` must emit one non-instructional conversational closing message through the normal stdout emission path. | MET | `initial.py`: after `receive_valid(script_request, validate_script)`, it calls `emit({"message": "Thanks, that completes the interrogation."})`. |
| OIS-021 | `initial.py` must perform no further stdin reads or semantic requests after the closing message and must then terminate naturally by reaching the end of the script. | MET | `initial.py`: the closing `emit(...)` is the final statement in `main()`; control returns naturally and the module ends after `main()` completes. |
| OIS-022 | The caller must rely on completion of `do_transaction(...)` as the boundary indicating that the child script has ended and the transaction receipt has been finalized at the supplied receipt path. | MET | `minimal instruction set.py`: each synchronous `do_transaction(...)` call completes before the caller proceeds; after the first return the caller immediately reads the supplied receipt path, and after the second return it returns both known receipt paths. |
| OIS-023 | In this minimal opinionated instruction set, every model-generated question used during its interrogation must be transmitted back to the model verbatim, without rewriting, paraphrasing, prefixing, suffixing, or otherwise changing the question text. | MET | `initial.py`: inside `for question in q1`, the outbound packet is built with `"instruction": question`; the model-generated string is assigned directly to the instruction field without transformation. |

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
