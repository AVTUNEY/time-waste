---
title: "My Recent Obsession with Span<T>"
date: 2026-01-18T02:18:00+04:00
draft: false
type: "post"
tags: ["dotnet", "csharp", "performance", "span"]
description: "Why Span<T> reshaped how I think about allocations, hot paths, and real-world performance."
image: "/images/valeera.webp"
---

Lately, I’ve become obsessed with `Span<T>`.

I remember that in one of his talks and interviews, David Fowler mentioned multiple times how important `Span<T>` is especially for modern .NET, which is essentially built on top of it. Wherever performance matters, you’ll almost always find `Span<T>` somewhere under the hood.

What’s funny is how many critical systems rely on it.

For example, Kestrel and the ASP.NET Core web server itself use `Span<T>` heavily to avoid frequent allocations and prevent turning the GC into a bottleneck. This is one of the main reasons modern .NET servers can handle insane throughput with relatively low memory pressure.

I remember many years ago, when I was still very young, I often wondered why we as developers don’t think more about how to write code with better performance characteristics.

How many developers do you know who would think twice before declaring a class when a struct would be more appropriate?

Seriously.

In reality, I know many people who have been writing C# for over 10 years and have never written something like:

```csharp
public struct Student
{
    public int Id;
    public string Name;
}
```

Ironically, these are often the same people who can explain what a struct is in an interview, but can’t clearly explain the real differences between a class and a struct beyond the textbook definition.

And no, I’m not talking only about *that famous difference* everyone memorizes for interviews.

You know the one.
The allocation.

And yet, most developers never go beyond `List<T>`.


We C# developers are kind of lazy.

Modern CPUs are ridiculously fast, and the .NET runtime does an amazing job at hiding our mistakes. The GC cleans up after us, the OS schedules threads nicely, memory is cheap, and most of the time everything *just works*. So we get used to writing code without thinking too much about what’s really happening under the hood.

And honestly, in many projects, you can get away with it.

Most developers never think about how many objects their code allocates, how often the GC runs, what happens under heavy load, what a hot loop is doing to the heap, how easy it is to cause socket exhaustion, how memory leaks silently destroy long-running services, or how LOH allocations fragment memory over time.

The machine handles it. Until one day it doesn’t.

And then latency spikes.
Memory grows forever.
CPU sits at 100%.
The GC runs nonstop.
The service starts randomly dying.



The moment you decide to push yourself and actually understand what’s happening internally, your whole perspective changes.

You stop writing code that just “works”.
You start writing code that *survives*.

You start asking:
What does this allocate?
Is this on the hot path?
Is this called per request?
Is this creating garbage every time?
What does this look like in IL?
What does the GC do with this?

And suddenly, performance is no longer some abstract thing.
It becomes very real. Back when I was playing chess semi-professionally, I learned one thing very early:

You don’t play good chess by looking at only your next move.
You play good chess by seeing the whole board.

Every move is about future positions, hidden threats, long-term weaknesses, piece activity, positional tradeoffs.

You’re constantly asking: *“If I do this, what happens next?”*

And coding is exactly the same.

When you write code, you’re making a move on the board.

That `new` keyword is a move.
That LINQ query is a move.
That async call is a move.
That allocation inside a loop is a move. Real engineers write code and think:
What does this become at runtime?
What does the GC do with it?
What happens when this runs 10 million times?


Ten years ago, when AI wasn’t even a thing, one of the hardest parts of backend development was working with strings.

Back then you were constantly dealing with them. Appending, slicing, copying into new memory, transforming, parsing. Especially when it came to legacy logging systems.

Today most serious systems use telemetry. Cloud providers make it almost fun to work with logs. You filter, search, correlate, build dashboards, set alerts. Everything is structured.

But years ago, it was hell.

Most logs were stored in plain `.txt` files. Sometimes in some random NoSQL database. Sometimes just dumped on disk and rotated once a day. And very often you ended up with a single massive text file with millions of appended lines.

Something like this:

```
2008-05-09T12:34:56.123Z|INFO|userId=74291|Payment completed amount=19.99
```

This was the classic format.

Now imagine your boss comes to you and says:

“We need a system that parses all these logs, extracts values, iterates over millions of lines, and runs analytics on them.”

If you’ve written C# for more than five minutes, I already know what your first solution looks like.

Something like:

```csharp
var parts = line.Split('|');
var userPart = parts[2]; // userId=74291
var userId = int.Parse(userPart.Substring(7));
```

And for small workloads, this works fine.

But when you run this over millions of lines, you’re basically creating garbage at an industrial scale. Every `Split` allocates an array. Every part becomes a new string. Every `Substring` allocates again. The GC starts running constantly. Memory grows.

So I decided to benchmark it.

I took this exact log format and compared the classic `Split` approach with a `Span<T>` based parser and I got completely different runtime behavior.

This is the exact benchmark I used:

```csharp
[MemoryDiagnoser]
public class LogParsingBenchmarks
{
    private readonly string _line =
        "2026-01-17T12:34:56.123Z|INFO|userId=74291|Payment completed amount=19.99";

    private int _sink;

    [Benchmark(Baseline = true)]
    public int Bad_Split_Substring()
    {
        var parts = _line.Split('|');

        var level = parts[1];
        var userPart = parts[2];

        var eq = userPart.IndexOf('=');
        var userIdStr = userPart.Substring(eq + 1);
        var userId = int.Parse(userIdStr);

        _sink ^= level.Length;
        return userId;
    }

    [Benchmark]
    public int Good_Span_Slicing_NoAlloc()
    {
        ReadOnlySpan<char> s = _line.AsSpan();

        var p0 = s.IndexOf('|');
        s = s.Slice(p0 + 1);

        var p1 = s.IndexOf('|');
        ReadOnlySpan<char> level = s.Slice(0, p1);
        s = s.Slice(p1 + 1);

        var p2 = s.IndexOf('|');
        ReadOnlySpan<char> userField = s.Slice(0, p2);

        var eq = userField.IndexOf('=');
        var userId = int.Parse(userField.Slice(eq + 1));

        _sink ^= level.Length;
        return userId;
    }
}
```

One version allocates like crazy. The other allocates nothing. Now imagine running this in a loop over 10 million log lines.

```
| Method                    | Mean     | Ratio | Gen0   | Allocated |
| ------------------------- | -------- | ----- | ------ | --------: |
| Bad_Split_Substring       | 59.18 ns | 1.00  | 0.0392 |     328 B |
| Good_Span_Slicing_NoAlloc | 16.61 ns | 0.28  | -      |       0 B |
```

The benchmarks are from ```BenchmarkDotnet``` Library.

So just to parse a single log line, the Span + slicing version is roughly **3.5x faster** (59.18 / 16.61 ≈ 3.56) and it allocates **nothing**.

One quick nuance: `Span<T>` is mutable and lets you write into the underlying memory, while `ReadOnlySpan<T>` is read-only and safer for parsing. In this example I use `ReadOnlySpan<char>` because I only need to read slices, not modify them.

And that’s the key: you’re not only faster, you’re not feeding the GC at all.

Sometimes you don’t want a new array. You don’t want a new string. You just want to work with *a portion* of the data you already have.

That’s slicing.

The real takeaway is simple: if a piece of code sits on the hot path, treat every allocation as a design decision. `Span<T>` is not a magic bullet, but it gives you a sharper tool to express intent and keep the GC quiet. Once you see the difference in a benchmark, it is hard to unsee it.

Slicing is basically: “keep the same memory, just move the window.”

This simplified version is very close in spirit, but the real implementation isn’t literally “`T[]` + start” because `Span<T>` can point to **arrays, stack memory, native memory**, etc.

Conceptually though, it’s basically this:

* a pointer/reference to the first element
* a length

That’s it.

Here’s a “teaching version” that matches the idea of the ```Span<T>```:

```csharp
// Teaching-only implementation
public struct SimpleSpan<T>
{
    private readonly T[] _array;
    private readonly int _start;
    public int Length { get; }

    public SimpleSpan(T[] array)
    {
        _array = array;
        _start = 0;
        Length = array.Length;
    }

    private SimpleSpan(T[] array, int start, int length)
    {
        _array = array;
        _start = start;
        Length = length;
    }

    public T this[int index]
    {
        get
        {
            if ((uint)index >= (uint)Length)
                throw new IndexOutOfRangeException();

            return _array[_start + index];
        }
        set
        {
            if ((uint)index >= (uint)Length)
                throw new IndexOutOfRangeException();

            _array[_start + index] = value;
        }
    }

    public SimpleSpan<T> Slice(int start)
        => Slice(start, Length - start);

    public SimpleSpan<T> Slice(int start, int length)
    {
        if ((uint)start > (uint)Length || (uint)length > (uint)(Length - start))
            throw new ArgumentOutOfRangeException();

        return new SimpleSpan<T>(_array, _start + start, length);
    }
}
```

That’s the whole idea: `Slice` doesn’t copy anything. It just returns a new span that starts later and has a different length.

Let’s say we have an underlying array:

```
index:  0   1   2   3   4   5   6   7   8   9
data : [A] [B] [C] [D] [E] [F] [G] [H] [I] [J]
```

Now we create a span over the whole thing:

```
Span (start=0, length=10)
       |---------------------------------------|
       [A] [B] [C] [D] [E] [F] [G] [H] [I] [J]
```

Now we slice it:

```csharp
var s2 = s.Slice(3, 4);
```

That means: start at index 3, length 4.

So the span window becomes:

```
Slice (start=3, length=4)
                    |---------------|
                    [D] [E] [F] [G]
```

Notice what didn’t happen:
No allocation, copying or new array. Nothing moved.

Only the “window” moved.


**Slice = (same memory) + (new start) + (new length)**

That’s why slicing is so fast.
Under the hood, nothing is copied and no new memory is allocated. The span simply shifts its view forward and adjusts its length, with a couple of bounds checks to make sure you don’t step outside the original window.
Same memory.
Different start.
Different length.
That’s all there is to it.

Kestrel is basically a machine that reads bytes from sockets and tries to interpret them as HTTP as fast as possible.
Headers, methods, paths, query strings, they’re all just parts of buffers. If you parse HTTP by doing `Split`, `Substring`, and allocating strings for every little piece, you’re done. The server turns into a GC simulator.

So instead, Kestrel (and lots of modern .NET internals) uses spans to look at “segments” of the request buffer without copying it. It can slice out “Host”, “Content-Length”, “/api/orders”, etc. as spans and only materialize strings if it truly needs them.

Same principle in image processing: huge buffers, you only want to touch a region, and you really don’t want to allocate new arrays for every crop/segment/pixel block.

And once you see how much garbage the classic approach creates, you start looking at every Split, every Substring, and every LINQ call a little bit differently, which, honestly, most of us .NET developers desperately need. 😂

I’m planning to start experimenting with ```Memory<T>``` soon, and I’ll hopefully keep you updated on that. But honestly, at this point, I don’t think I’ll ever stop using ```Span<T>```.
My recommendation is to take a look at the GitHub implementation of ```Span<T>``` itself. It’s one of the best ways to truly understand how it works under the hood.
