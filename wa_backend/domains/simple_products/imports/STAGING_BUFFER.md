# Product Import staging spool resource policy

The spool is a private, disposable handoff between parsing and the single atomic
staging transaction. SourceStore remains the immutable recovery authority. No
database session is borrowed while the spool is built. Row numbers, raw values,
source-cell metadata, staging reconciliation and job state semantics are unchanged.

## Encoding and memory

JSONL is written as compact UTF-8 with `ensure_ascii=False`, including Arabic
headers and nested metadata. An Arabic character therefore occupies two UTF-8
bytes instead of the six ASCII bytes of `\uXXXX`. JSON escaping of quotes,
backslashes and control characters is retained. Isolated surrogate code points
are written as JSON escapes, preserving the previous JSON round trip.

One serialized row plus a **64 KiB** write chunk is held in memory; rows are
never accumulated in an import-sized list. Exact UTF-8 bytes, including newlines,
are counted before writing. `BufferedStageRows.byte_size` and `byte_limit` expose
the completed file size and its admitted budget for acceptance inspection.

## Volume-derived size limit and concurrent imports

Use the actual volume of `tempfile.gettempdir()` for both disk-space checks and
file creation. At spool admission:

```
slots = max(2, configured execution slots per process)
reserve = slots * 2 XLSX readers * 64 MiB uncompressed-source ceiling
spool byte limit = floor((current free bytes - reserve) / slots)
```

The approved topology is **one execution process with two slots**. Its reserve
is **256 MiB**. With **2 GiB free**, each admitted spool has at most **896 MiB**;
two such spools use at most **1,792 MiB**, leaving the working reserve. A second
spool admitted after the first has written bytes receives a smaller budget based
on the remaining space. Raising the configured slot count divides the available
space further and increases the reserve; it does not authorize extra processes.

The reserve is an operational headroom policy derived from the existing parser
envelope, not a claim that SQLite files occupy at most their input XML size.
Existing parser files and other already allocated files are reflected in the
measured free space. This correction does not change the parser or worker topology.

There is **no fixed MiB ceiling on a valid 50,000-row source** and no reduction of
the existing 50,000-row/100-column limits. Long values, wide Arabic headers and
metadata consume their actual encoded bytes. The storage allowance scales with
the worker volume; sufficiently large valid files require enough free space for
the configured concurrent imports. The admission budget remains fixed until the
spool closes; a later retry recomputes it after resources become available.

Before each write of at most **64 KiB**, check that free space will remain above
the reserve. Flush that chunk so concurrent checks see allocated spool data.
The check/write/flush sequence has no coroutine yield, so the two imports in
the approved execution process cannot interleave between that check and write.
There is no polling task, import-wide memory buffer, database lock or persistent
resource registry. The checks do not physically reserve disk blocks or prevent
unrelated processes from consuming the volume between a check and a write;
operating-system write/flush failures also follow the safe failure path.

## Safe resource failure

No allowance above the reserve, exceeding the admitted spool budget, falling
below the reserve during writing, or an OS storage failure raises the job-level
**`PRODUCT_IMPORT_STAGING_STORAGE_UNAVAILABLE`** error. It is a **retryable system
failure**, not invalid source data and never a row error. The existing queue
retains its bounded retries, original job/request identity and correlation ID.
At exhausted retries the existing retryable-failure contract exposes the code
and this safe message:

> Temporary import storage is unavailable or insufficient. The source file is
> retained; retry this import after storage is available.

Internal paths, OS error details and cell values are not part of that message.
The partial spool closes on failure/coroutine cancellation. Since staging has
not started, no source rows, products, audit events or outbox records are
published, and SourceStore is not cleared. Retry verifies SourceStore again and
rebuilds the spool. Successful buffering still proceeds through the existing
single atomic staging transaction and exact row-count reconciliation.

The prior **157.26 MiB / 50,000 rows / 25 Arabic fields** observation motivates
removing ASCII Unicode escapes. The two-to-six byte ratio applies to Arabic
characters only; the complete file-size reduction and disk-check overhead need
the owner's final acceptance measurement. No new performance result is claimed.
