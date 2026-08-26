# Simplified Transaction Layer Requirements

This table contains only requirements explicitly established in the project conversation for the isolated simplified transaction layer under `minimal-controller-design/simplified-transaction-layer/`.

`MET` means the requirement is implemented by executable code in this subfolder and the exact script/line evidence is listed. `SPECIFIED` means the requirement is authoritative for this layer but implementation evidence has not yet been verified. `UNMET` means verified executable behavior is required and absent.

| ID | Requirement | Status | Scripts / lines where requirement is met |
|---|---|---|---|
| STL-001 | The simplified transaction layer is implemented separately in its own subfolder rather than by reworking the existing transaction layer. | SPECIFIED | Implementation evidence not yet verified against this revised table. |
| STL-002 | The transaction function accepts script source as transaction input. | SPECIFIED | Implementation evidence not yet verified against this revised table. |
| STL-003 | For a transaction containing a script, the transaction function creates a runner and runs exactly the supplied script in a child process. | SPECIFIED | Implementation evidence not yet verified against this revised table. |
| STL-004 | The runner uses `subprocess.Popen(...)` so one child can remain alive across multiple stdin/stdout exchanges during the execution of the supplied script. | SPECIFIED | Implementation evidence not yet verified against this revised table. |
| STL-005 | The transaction passes caller/model input through to the child process's stdin. | SPECIFIED | Implementation evidence not yet verified against this revised table. |
| STL-006 | The transaction passes child-process stdout through to the caller/model. | SPECIFIED | Implementation evidence not yet verified against this revised table. |
| STL-007 | The transaction passes child-process stderr through to the caller. | SPECIFIED | Implementation evidence not yet verified against this revised table. |
| STL-008 | A single running child can perform multiple stdout emissions and receive multiple stdin responses before the supplied script terminates. | SPECIFIED | Implementation evidence not yet verified against this revised table. |
| STL-009 | The transaction records every observable stdin event in the transaction record. | SPECIFIED | Implementation evidence not yet verified against this revised table. |
| STL-010 | The transaction records every observable stdout event in the transaction record. | SPECIFIED | Implementation evidence not yet verified against this revised table. |
| STL-011 | The transaction records every observable stderr event in the transaction record. | SPECIFIED | Implementation evidence not yet verified against this revised table. |
| STL-012 | Recorded stdin/stdout/stderr events preserve their transaction order and remain in local memory while the child is running. | SPECIFIED | Implementation evidence not yet verified against this revised table. |
| STL-013 | The transaction records the function used to initialize/create the child process and the invocation information showing how the child was initialized. | SPECIFIED | Implementation evidence not yet verified against this revised table. |
| STL-014 | The transaction records the exact script supplied for execution. | SPECIFIED | Implementation evidence not yet verified against this revised table. |
| STL-015 | A normal transaction is finite: the transaction remains active while the supplied script is running and receipt finalization occurs after the script terminates and the child process closes. | SPECIFIED | Implementation evidence not yet verified against this revised table. |
| STL-016 | Work belonging to a persistent system is divided into finite transaction units when completed receipts are required. | SPECIFIED | Implementation evidence not yet verified against this revised table. |
| STL-017 | A transaction invocation with no script executes no child script and still generates a transaction receipt. | SPECIFIED | Implementation evidence not yet verified against this revised table. |
| STL-018 | During child execution, transaction events are accumulated in memory; the receipt file is written only after the child process has closed. | SPECIFIED | Implementation evidence not yet verified against this revised table. |
| STL-019 | The completed transaction receipt is written once to a local receipt file, either at a caller-specified filename or at a transaction-specific generated filename. | SPECIFIED | Implementation evidence not yet verified against this revised table. |
| STL-020 | After writing the receipt, the transaction verifies that the receipt file exists at the selected local destination. | SPECIFIED | Implementation evidence not yet verified against this revised table. |
| STL-021 | After writing the receipt, the transaction reads the persisted receipt back and verifies that it matches the in-memory receipt object that was used to write it. | SPECIFIED | Implementation evidence not yet verified against this revised table. |
| STL-022 | Receipt persistence is complete only after the written receipt has been verified against the in-memory receipt used for persistence. | SPECIFIED | Implementation evidence not yet verified against this revised table. |

## Current verification state

This revision is limited to transaction-layer requirements explicitly discussed in the conversation. Transaction-state recording has been removed from the receipt requirements to keep receipts concise. Code compliance has not yet been evaluated against this revised table.
