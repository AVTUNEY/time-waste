---
title: "Trying to Understand Write-Ahead Logging Under the Hood"
date: 2026-07-08T17:05:00+04:00
draft: false
type: "post"
tags: ["databases", "relational-database", "storage-engine", "wal", "transactions", "systems"]
description: "My notes while trying to understand how write-ahead logging works inside relational databases, from pages and LSNs to redo, undo, checkpoints, and crash recovery."
image: "/images/wal.jpg"
---

Lately I have been working on a relational database and trying to understand how databases work under the hood.

Not from the usual application developer point of view where we send SQL, add indexes, check execution plans, and move on.

I mean the lower level part.

Pages.
Buffer pool.
Dirty pages.
Transaction log.
Crash recovery.
What actually happens when the process dies.

One topic that keeps coming back is **Write-Ahead Logging**, usually called WAL.

I knew the basic sentence before:

> Write the log before writing the data.

But this sentence is too small. It is technically correct, but it hides most of the important stuff.

The more useful version is:

> Before a changed database page is written to disk, the log record describing that change must already be durable.

In database terms, the rule is usually expressed like this:

```text
flushedLSN >= pageLSN
```

This is the main invariant.

`pageLSN` means:

> This page contains changes up to this log sequence number.

`flushedLSN` means:

> The WAL is durable up to this log sequence number.

So if a page has:

```text
pageLSN = 900
```

but the log is only flushed up to:

```text
flushedLSN = 700
```

then this page must not be written to disk yet.

Why?

Because the page contains a change from the future, at least from the log's point of view.

If the database crashes after writing that page, recovery will see data on disk that the durable log cannot explain. At that point the database has no clean way to decide whether the change should exist or not.

So before writing a dirty page, the buffer manager has to do something like this:

```csharp
if (page.PageLsn > wal.FlushedLsn)
{
    wal.FlushUntil(page.PageLsn);
}

disk.Write(page);
```

That condition looks small, but it is one of the core rules that makes crash recovery possible.

## The page is the real unit

When we use a database, we usually think in rows.

```sql
UPDATE accounts
SET balance = balance - 100
WHERE id = 1;
```

But the storage engine mostly thinks in pages.

A table file is split into fixed-size pages. PostgreSQL uses 8KB pages by default. SQL Server also uses 8KB pages. SQLite can use different page sizes, often 4KB.

A very simplified page in C# could look like this:

```csharp
public readonly record struct PageId(long Value);

public readonly record struct Lsn(long Value) : IComparable<Lsn>
{
    public int CompareTo(Lsn other) => Value.CompareTo(other.Value);

    public static bool operator >(Lsn left, Lsn right) => left.Value > right.Value;
    public static bool operator <(Lsn left, Lsn right) => left.Value < right.Value;
    public static bool operator >=(Lsn left, Lsn right) => left.Value >= right.Value;
    public static bool operator <=(Lsn left, Lsn right) => left.Value <= right.Value;
}

public sealed class Page
{
    public const int Size = 8192;

    public PageId Id { get; }
    public Lsn PageLsn { get; set; }
    public bool IsDirty { get; set; }

    private readonly byte[] _data = new byte[Size];

    public Page(PageId id)
    {
        Id = id;
    }

    public void Write(int offset, ReadOnlySpan<byte> bytes)
        => bytes.CopyTo(_data.AsSpan(offset));

    public ReadOnlySpan<byte> Read(int offset, int length)
        => _data.AsSpan(offset, length);
}
```

This is not a real production page implementation, but it is enough for the idea.

When a row is updated, the database finds the page containing that row and modifies bytes inside that page.

Something like this:

```csharp
var page = bufferPool.GetPage(pageId);

var before = page.Read(offset, length).ToArray();
var after = BitConverter.GetBytes(newBalance);

var lsn = wal.AppendUpdate(
    txnId,
    pageId,
    offset,
    before,
    after);

page.Write(offset, after);
page.PageLsn = lsn;
page.IsDirty = true;
```

The important part is that the page was changed in memory.

It does not mean the table file on disk was updated immediately.

The page is now dirty.

Dirty means:

```text
memory version != disk version
```

Databases keep dirty pages in memory all the time. They have to. If every update immediately wrote the full page to disk, performance would be terrible.

Imagine one transaction modifies 500 pages. If commit had to write all 500 pages to disk before returning, commits would be very slow.

So databases usually do this instead:

```text
on commit:
    force the WAL
    write dirty pages later
```

This is called **no-force**.

Commit does not force every changed data page to disk.

Commit only has to make the log durable enough so the database can redo the changes after a crash.

That is the first big reason WAL exists.

## Force, no-force, steal, no-steal

There are two old terms that are important here.

`force` means:

```text
At commit time, write all dirty pages touched by the transaction to disk.
```

`no-force` means:

```text
At commit time, do not write all dirty pages. Write only the log.
```

`steal` means:

```text
The buffer pool is allowed to write a dirty page to disk even if the transaction that changed it has not committed yet.
```

`no-steal` means:

```text
Uncommitted dirty pages cannot be written to disk.
```

The simple design is:

```text
no-steal + force
```

With this design:

Uncommitted data never reaches disk, so undo is not needed.

Committed data is always forced to disk, so redo is not needed.

Very easy to reason about.

Also very slow.

Modern databases usually want:

```text
steal + no-force
```

This is faster, but now recovery is harder.

With `no-force`, committed changes may still be only in memory when the database crashes.

So recovery needs **redo**.

With `steal`, uncommitted changes may already be on disk when the database crashes.

So recovery needs **undo**.

The table looks like this:

```text
                    FORCE                 NO-FORCE

NO-STEAL            simple                needs REDO

STEAL               needs UNDO            needs UNDO + REDO
```

This table explains a lot.

If we want a practical high-performance buffer pool, we accept `steal + no-force`.

Then WAL is needed because crash recovery must handle both cases:

```text
committed but not on disk     => redo
uncommitted but already disk  => undo
```

## What a WAL record contains

A WAL record is not just a message saying "row updated".

It needs enough information to redo or undo the change.

A simplified C# example:

```csharp
public readonly record struct TxnId(long Value);

public enum WalRecordType
{
    Update,
    Commit,
    Abort,
    Compensation,
    Checkpoint
}

public sealed record WalRecord(
    Lsn Lsn,
    Lsn? PrevTxnLsn,
    TxnId TxnId,
    WalRecordType Type,
    PageId PageId,
    int Offset,
    ReadOnlyMemory<byte> BeforeImage,
    ReadOnlyMemory<byte> AfterImage,
    uint Crc);
```

The important fields are:

`Lsn`

The position of this record in the log.

`PrevTxnLsn`

The previous log record for the same transaction.

`TxnId`

The transaction that produced this record.

`PageId`

The page that was changed.

`Offset`

Where inside the page the change happened.

`BeforeImage`

The bytes before the change. Used for undo.

`AfterImage`

The bytes after the change. Used for redo.

So if the database changed a 32-bit integer from `100` to `70`, the record may contain:

```text
pageId = 42
offset = 6132
before = 64 00 00 00
after  = 46 00 00 00
```

In C#:

```csharp
var before = BitConverter.GetBytes(100);
var after = BitConverter.GetBytes(70);

var record = new WalRecord(
    Lsn: new Lsn(120),
    PrevTxnLsn: null,
    TxnId: new TxnId(7),
    Type: WalRecordType.Update,
    PageId: new PageId(42),
    Offset: 6132,
    BeforeImage: before,
    AfterImage: after,
    Crc: 0);
```

Redo is then:

```csharp
page.Write(record.Offset, record.AfterImage.Span);
page.PageLsn = record.Lsn;
```

Undo is:

```csharp
page.Write(record.Offset, record.BeforeImage.Span);
```

This is the basic idea.

Real systems can be more complicated.

Some logs are physical:

```text
On page X, at offset Y, replace bytes A with bytes B.
```

Some logs are logical:

```text
Insert row with key 10.
```

Some logs are physiological, which is basically a mix:

```text
On this page, perform this logical operation.
```

ARIES uses physiological logging. I am still reading more about it, but the reason makes sense. You want recovery to be tied to pages because pages are what actually get flushed, but you also do not always want to log huge byte arrays for every operation.

## WAL is bytes, not objects

The C# record above is only an in-memory representation.

On disk, WAL is bytes.

A record needs framing so recovery can parse it.

A simple binary layout could be:

```text
record length
record type
lsn
previous transaction lsn
transaction id
page id
offset
before length
after length
before bytes
after bytes
crc
```

The length tells recovery where the record ends.

The CRC helps detect a partial or corrupted record.

This matters because the database can crash while writing the WAL itself.

If the last record is half-written, recovery must stop at the last valid record.

Teaching version in C#:

```csharp
public static class WalRecordWriter
{
    public static void WriteUpdate(
        Stream stream,
        Lsn lsn,
        Lsn? previousTxnLsn,
        TxnId txnId,
        PageId pageId,
        int offset,
        ReadOnlySpan<byte> before,
        ReadOnlySpan<byte> after)
    {
        using var payloadStream = new MemoryStream();
        using var writer = new BinaryWriter(payloadStream, Encoding.UTF8, leaveOpen: true);

        writer.Write((byte)WalRecordType.Update);
        writer.Write(lsn.Value);
        writer.Write(previousTxnLsn?.Value ?? -1);
        writer.Write(txnId.Value);
        writer.Write(pageId.Value);
        writer.Write(offset);
        writer.Write(before.Length);
        writer.Write(after.Length);
        writer.Write(before);
        writer.Write(after);
        writer.Flush();

        var payload = payloadStream.ToArray();
        var crc = Crc32.HashToUInt32(payload);

        using var finalWriter = new BinaryWriter(stream, Encoding.UTF8, leaveOpen: true);
        finalWriter.Write(payload.Length);
        finalWriter.Write(payload);
        finalWriter.Write(crc);
    }
}
```

This is not production code. I would not use this exact format in a real engine.

But it shows the important pieces:

```text
length
payload
checksum
```

During recovery, you scan record by record:

```csharp
while (TryReadNextRecord(stream, out var record))
{
    records.Add(record);
}
```

If the next record is incomplete or has a bad checksum, recovery ignores it and stops there.

The durable WAL is the longest valid prefix of the log.

In math form:

```text
validPrefix(WAL) = longest prefix where every record is complete and checksum-valid
```

Recovery must work only from that prefix.

Not from what the database intended to write.

Only from what it can prove was written correctly.

## LSN is database time

LSN means Log Sequence Number.

You can think of it as a byte offset in the WAL stream:

```text
LSN = offset inside WAL
```

If:

```text
LSN(A) = 100
LSN(B) = 180
```

then `A` happened before `B`.

So WAL gives the database a total order of changes:

```text
r_i < r_j  iff  LSN(r_i) < LSN(r_j)
```

Every page stores the latest LSN that affected it:

```text
pageLSN(p) = max { LSN(r) | r changed page p and page p includes r }
```

This is used during redo.

If a log record has already been applied to a page, do not apply it again.

```csharp
if (page.PageLsn >= record.Lsn)
{
    return;
}

page.Write(record.Offset, record.AfterImage.Span);
page.PageLsn = record.Lsn;
```

This makes redo idempotent.

Idempotent means applying it twice has the same effect as applying it once:

```text
redo(r, redo(r, page)) = redo(r, page)
```

That matters because recovery itself may crash.

If the database crashes during recovery and then starts recovery again, it must not corrupt pages by applying the same update twice.

The `pageLSN` check handles that.

## Commit is a log record

Before reading about WAL properly, I thought commit worked like this:

> The database writes the changed rows to disk and then returns success.

That is not how it usually works with WAL.

With WAL, a transaction is committed when its commit record is durable.

Example:

```text
LSN 100: T1 update page 5
LSN 140: T1 update page 8
LSN 180: T1 commit
```

If `LSN 180` is flushed, `T1` is committed.

Even if page 5 and page 8 are still dirty in memory.

After crash, recovery redoes those updates.

If `LSN 180` is not flushed, `T1` is not committed.

Even if page 5 was already written to disk because the buffer pool stole the page.

After crash, recovery undoes it.

So:

```text
committed(T) <=> commitLSN(T) <= flushedLSN
```

This is why `fsync` or equivalent durable flushing matters.

Writing to a file does not always mean durable. The bytes may still be in the OS page cache.

In C#, the rough version is:

```csharp
fileStream.Write(bytes);
fileStream.Flush(flushToDisk: true);
```

A toy WAL class:

```csharp
public sealed class Wal
{
    private readonly FileStream _stream;
    private long _nextLsn;

    public Lsn FlushedLsn { get; private set; }

    public Wal(FileStream stream)
    {
        _stream = stream;
    }

    public Lsn Append(ReadOnlySpan<byte> recordBytes)
    {
        var lsn = new Lsn(_nextLsn);

        _stream.Position = _nextLsn;
        _stream.Write(recordBytes);

        _nextLsn += recordBytes.Length;
        return lsn;
    }

    public void FlushUntil(Lsn lsn)
    {
        if (FlushedLsn >= lsn)
            return;

        _stream.Flush(flushToDisk: true);
        FlushedLsn = lsn;
    }
}
```

This code is too simple for a real database.

A real implementation has to care about partial writes, alignment, concurrent writers, group commit, file segment boundaries, and a lot more.

But the main idea is there:

```text
Append gives an LSN.
Flush makes LSNs durable.
Commit waits for the commit LSN to become durable.
```

## Group commit

Durable flushes are expensive.

If every transaction does its own flush, throughput is limited by flush latency.

If one flush takes 1 ms, one transaction per flush gives about:

```text
1000 commits/sec
```

That is a hard limit before you even talk about CPU or locks.

Group commit fixes this by batching many commit records behind one flush.

The idea:

```text
T1 appends commit at LSN 100
T2 appends commit at LSN 130
T3 appends commit at LSN 170

flush WAL once up to LSN 170

T1, T2, T3 are all durable
```

If:

```text
F = flush latency
lambda = commits arriving per second
```

then roughly:

```text
commits_per_flush ≈ lambda * F
```

and:

```text
amortized_flush_cost ≈ F / commits_per_flush
```

Not exact queueing theory, but good enough for intuition.

In C#, the waiters might look like this:

```csharp
public sealed class CommitWaiter
{
    public Lsn CommitLsn { get; }

    public TaskCompletionSource Completion { get; } =
        new(TaskCreationOptions.RunContinuationsAsynchronously);

    public CommitWaiter(Lsn commitLsn)
    {
        CommitLsn = commitLsn;
    }
}
```

A background flusher can take all waiters, find the highest commit LSN, flush once, then complete every waiter with:

```text
waiter.CommitLsn <= wal.FlushedLsn
```

This is one of those details that sounds like optimization, but it is actually central to database throughput.

## WAL bandwidth

WAL is not free.

Every update writes log bytes.

Simple calculation:

```text
N = updates per second
B = average WAL bytes per update
C = commits per second
K = average commit record size
```

Then:

```text
WAL bandwidth ≈ N * B + C * K
```

If an update logs metadata `M`, before image of length `L`, and after image of length `L`, then:

```text
B = M + 2L
```

So:

```text
WAL bandwidth ≈ N * (M + 2L) + C * K
```

Example:

```text
N = 100,000 updates/sec
M = 32 bytes metadata
L = 8 bytes
```

Then:

```text
B = 32 + 16 = 48 bytes
WAL ≈ 100,000 * 48 = 4.8 MB/sec
```

Not bad.

But if each update logs a full 8KB page:

```text
100,000 * 8192 bytes ≈ 781 MB/sec
```

Only for WAL.

That is a huge difference.

This is why log record size matters.

But sometimes databases do log full-page images.

One reason is torn pages.

## Torn pages

A page write is not always atomic.

The database may ask the OS to write 8KB, crash in the middle, and after restart the page might look like this:

```text
first 4KB  = new data
second 4KB = old data
```

That page is neither old nor new.

It is corrupted.

This is called a torn page.

Databases use different techniques to handle this:

```text
page checksums
full-page images in WAL
double-write buffers
atomic write assumptions
storage-level guarantees
```

Full-page images are expensive, but they give recovery a clean copy of the page when needed.

Again, tradeoff.

Smaller WAL records are faster.

Larger WAL records can make recovery safer or simpler.

## WAL segments

The log is append-only, but in practice it is usually split into files.

Something like:

```text
wal_000001
wal_000002
wal_000003
```

If segment size is `S` and absolute LSN is `L`, then:

```text
segment = floor(L / S)
offset  = L mod S
```

For example, with 16MB segments:

```text
S = 16 * 1024 * 1024
L = 40MB
```

Then:

```text
segment = floor(40 / 16) = 2
offset = 8MB
```

This matters because the database has to know which WAL files are still needed.

Old WAL cannot be deleted immediately.

It may still be needed for:

```text
crash recovery
replication
backup
point-in-time recovery
```

So even cleaning old WAL is not just deleting files. The database has to know the oldest LSN still required by any subsystem.

## Recovery

Crash recovery is usually explained in three phases:

```text
analysis
redo
undo
```

Analysis reconstructs what was happening when the crash happened.

It rebuilds things like:

```text
dirty page table
transaction table
winner transactions
loser transactions
redo start point
```

Redo repeats history.

Undo rolls back loser transactions.

The phrase "repeats history" is important.

Recovery does not simply redo committed transactions.

It first replays the logged page history, including changes from transactions that may not have committed.

Then it undoes the loser transactions.

At first this felt strange to me.

Why redo something if you will undo it later?

Because it makes recovery deterministic.

Redo brings the database pages to the state described by the log.

Undo then removes transactions that did not commit.

Conceptually:

```text
after redo = database state at crash time
after undo = database state with only committed transactions
```

More formally:

```text
H = log history
C = committed transactions
U = uncommitted loser transactions
```

Recovery wants:

```text
state_final ≡ apply({ r in H | txn(r) in C })
```

Every committed transaction survives.

Every uncommitted transaction disappears.

## Concrete recovery example

Suppose WAL contains:

```text
LSN 100: T1 update page 1, A -> B
LSN 120: T2 update page 2, C -> D
LSN 140: T1 commit
LSN 160: T3 update page 1, B -> E
LSN 180: T2 update page 3, F -> G
```

Then crash.

What do we know?

`T1` committed.

`T2` did not commit.

`T3` did not commit.

So:

```text
winners = { T1 }
losers  = { T2, T3 }
```

The disk may be in many possible states.

Maybe page 1 has `A`.

Maybe page 1 has `B`.

Maybe page 1 has `E`.

Maybe page 2 already has `D`, even though `T2` did not commit.

Recovery does not guess.

It uses WAL.

Redo scans forward and applies missing updates using `pageLSN`.

Undo walks loser transactions backward and restores their before images.

So `T1` remains.

`T2` and `T3` disappear.

This is the main promise:

```text
committed effects stay
uncommitted effects go away
```

## Transaction chains

`PrevTxnLsn` exists so rollback can walk a transaction backward.

Example:

```text
LSN 100: T5 update page 1, prev = null
LSN 160: T5 update page 8, prev = 100
LSN 220: T5 update page 3, prev = 160
```

If `T5` aborts, undo starts at `220`:

```text
220 -> 160 -> 100
```

Each step restores the before image.

In C#:

```csharp
var nextToUndo = transaction.LastLsn;

while (nextToUndo is not null)
{
    var record = wal.Read(nextToUndo.Value);

    if (record.Type == WalRecordType.Update)
    {
        var page = bufferPool.GetPage(record.PageId);
        page.Write(record.Offset, record.BeforeImage.Span);
    }

    nextToUndo = record.PrevTxnLsn;
}
```

Again, real recovery also writes compensation records, but this shows why the previous LSN pointer is useful.

## Undo has to be logged

Recovery can crash too.

Example:

The database crashes.

Recovery starts.

Recovery begins undoing transaction `T9`.

Then the machine crashes again.

If undo progress only exists in memory, it is lost.

So undo actions are also logged.

These are called compensation log records, or CLRs.

Example:

```text
LSN 300: T9 update page 7, A -> B
```

During undo:

```text
LSN 420: CLR for T9, undo LSN 300, restore A
```

The CLR means:

```text
I already performed this undo.
```

A CLR is redoable, but it is not undone again.

That prevents recovery from undoing its own undo.

A simplified CLR shape:

```csharp
public sealed record CompensationRecord(
    Lsn Lsn,
    TxnId TxnId,
    PageId PageId,
    int Offset,
    ReadOnlyMemory<byte> RestoredBytes,
    Lsn? UndoNextLsn);
```

`UndoNextLsn` tells recovery where to continue if it crashes again.

Example:

```text
LSN 100: T9 update A, prev = null
LSN 140: T9 update B, prev = 100
LSN 180: T9 update C, prev = 140
```

Undo starts at `180`.

After undoing `180`, recovery writes:

```text
LSN 220: CLR undoing 180, undoNext = 140
```

If the system crashes again, recovery follows `undoNext = 140`.

This makes rollback itself crash-safe.

## Checkpoints

I thought checkpoint means:

> Everything dirty is written to disk.

That is not always correct.

In WAL-based systems, a checkpoint often means:

> Here is enough metadata so recovery does not need to scan the log from the beginning.

A checkpoint can contain:

```text
dirty page table
transaction table
checkpoint LSN
```

In C#:

```csharp
public sealed record CheckpointRecord(
    Lsn Lsn,
    IReadOnlyDictionary<PageId, Lsn> DirtyPageTable,
    IReadOnlyDictionary<TxnId, Lsn> TransactionTable);
```

The dirty page table maps:

```text
pageId -> recLSN
```

`recLSN` is the first log record that made the page dirty.

Redo can start from:

```text
min(recLSN)
```

instead of from the beginning of the log.

This bounds recovery time.

Simple calculation:

```text
R = WAL generation rate in MB/s
T = seconds between checkpoints
B = WAL scan bandwidth in MB/s
```

Then:

```text
recovery_scan_time ≈ (R * T) / B
```

Example:

```text
R = 200 MB/s
T = 60 seconds
B = 1000 MB/s
```

Then:

```text
recovery_scan_time ≈ (200 * 60) / 1000 = 12 seconds
```

If checkpoint interval becomes 10 minutes:

```text
recovery_scan_time ≈ (200 * 600) / 1000 = 120 seconds
```

This is only scan time, not full recovery time, but the direction is clear.

Checkpoint too rarely and recovery takes longer.

Checkpoint too often and normal runtime gets more write pressure.

Again, no magic. Just tradeoffs.

## End-to-end example

Let’s use one simple transaction.

Initial page:

```text
Page 1:
  offset 100 = account 1 balance = 100
  offset 108 = account 2 balance = 50
  pageLSN = 0
```

Transaction `T1` transfers 30:

```text
account 1: 100 -> 70
account 2: 50  -> 80
```

WAL:

```text
LSN 100: T1 update page 1 offset 100, 100 -> 70
LSN 130: T1 update page 1 offset 108, 50 -> 80
LSN 160: T1 commit
```

Memory page after updates:

```text
account 1 = 70
account 2 = 80
pageLSN = 130
dirty = true
```

Now different crash cases.

Case 1:

```text
flushedLSN = 160
data page on disk is still old
```

The commit record is durable.

Transaction committed.

Recovery redoes both updates.

Final:

```text
account 1 = 70
account 2 = 80
```

Case 2:

```text
flushedLSN = 130
commit record is not durable
data page on disk contains account 1 = 70
```

The transaction did not commit.

But part of it reached disk.

Recovery undoes it.

Final:

```text
account 1 = 100
account 2 = 50
```

Case 3:

```text
flushedLSN = 160
data page on disk has account 1 = 70, account 2 = 50
pageLSN = 100
```

The transaction committed, but only the first update reached disk.

Recovery scans WAL:

```text
LSN 100: pageLSN >= 100, skip
LSN 130: pageLSN < 130, redo
LSN 160: commit, mark T1 committed
```

Final:

```text
account 1 = 70
account 2 = 80
```

This example is small, but it shows the core idea.

WAL lets the database handle many ugly disk states and still return to a valid transaction state.

## The basic rule

The database state is `S`.

Each log record is an operation:

```text
r_i : S -> S
```

The log is ordered:

```text
L = [r_1, r_2, ..., r_n]
```

Applying the log is function composition:

```text
S_n = r_n(...r_2(r_1(S_0)))
```

After a crash, the database only has the valid durable prefix of WAL:

```text
L[0..k]
```

Recovery must produce a state where:

```text
effects(T) are visible iff commit(T) is in L[0..k]
```

That is the real promise.

The data files do not have to be perfectly up to date at every moment.

They can contain old pages.

They can contain some uncommitted changes.

Some dirty committed pages may still only exist in memory before the crash.

But if the WAL rules are preserved, recovery can fix it.

The main rules are:

```text
1. Do not write a page before its log record is durable.
2. A transaction commits only when its commit record is durable.
3. Use pageLSN to make redo idempotent.
4. Use before images or undo information to roll back losers.
5. Log undo actions with CLRs so recovery can survive another crash.
6. Use checkpoints to reduce how much log must be scanned.
```

This is why WAL is such an important idea.

It is not just an append-only file.

It is the thing that lets the database separate fast normal execution from correct crash recovery.

During normal execution, pages can be dirty, writes can be delayed, and the buffer pool can make practical decisions.

After a crash, the log gives enough information to decide what must be redone and what must be undone.

That is the part I find interesting.

Not because it is mysterious.

Because once you see the rules, the whole thing becomes very mechanical.

And I like mechanical things.

Rows are what we query.

Pages are what the storage engine moves.

WAL is how the database remembers enough to put everything back together.
