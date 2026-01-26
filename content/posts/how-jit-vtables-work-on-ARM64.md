---
title: "Why `sealed` Makes C# Code Faster: ARM64 Assembly Deep Dive"
date: 2026-01-27T01:00:00+04:00
draft: false
type: "post"
tags: ["dotnet", "csharp", "performance", "jit", "arm64", "assembly"]
description: "Starting from a debate about the sealed keyword, this article dives into C# and ARM64 assembly to show exactly what happens during virtual dispatch and why devirtualization is so much faster."
image: "/images/vtable-dispatch.png"
---
A couple of days ago I ended up in a small argument with a friend about the `sealed` keyword. He said something like:

> “Did you know using `sealed` is faster? Because it doesn’t need vtable lookup.”

I already knew this, but what surprised me was that a few other friends in the group had never heard about this at all. So I decided to dig a bit deeper and actually *prove* what’s going on under the hood, not just repeat folklore.

> **Why does devirtualized code run faster, and what exactly changes at the machine level?**

The idea of a *virtual table* (vtable) mostly comes from C++. It’s one of the classic building blocks of object-oriented programming: a table of function pointers used to decide *which* implementation should be executed at runtime.

[Wikipedia](https://en.wikipedia.org/wiki/Virtual_method_table) puts it nicely:

> The virtual table is a lookup table of functions used to resolve function calls in a dynamic/late binding manner.

C# and the CLR use the same general concept, even if the internal layout differs.

Devirtualization is simply an optimization where the JIT realizes:

> “I actually know the exact type here.”

Once it knows that, it no longer needs to perform a runtime lookup through a vtable. The call can become direct and in many cases, it can even be inlined.

The following is a small class structure (modeled in C#), and what the resulting implementation table and slot map would be for each class.

{{< figure src="/images/vtable-dispatch.png" title="" >}}

Interface calls in .NET don’t usually go through a classic vtable. Instead, the runtime uses something called Virtual Stub Dispatch (VSD).

Think of VSD as a tiny piece of code that sits in front of an interface call. The first time it runs, it figures out which concrete method should be called and remembers it. After that, most calls hit a fast cached path that’s roughly as cheap as a normal vtable lookup.

The CoreCLR docs describe it like this:

> “Virtual stub dispatching (VSD) is the technique of using stubs for virtual method invocations instead of the traditional virtual method table… Currently, VSD is enabled only for interface method calls.”


The example code below uses class virtual methods (regular vtable dispatch), not interface calls (VSD). The concepts are similar, but the implementation differs.
Now comes devirtualization. If the JIT sees that a call site always gets the same concrete type, it can skip all of that machinery. It just emits a direct call to the target method. And once the call is direct, the JIT can inline it and optimize it like any other method.

So the idea is simple: devirtualization doesn’t just make virtual calls a little faster, it turns them into normal calls that unlock a whole new level of optimization.

Deep dive document:

https://github.com/dotnet/coreclr/blob/master/Documentation/botr/virtual-stub-dispatch.md

I ran a small experiment myself:

```csharp
internal abstract class Base
{
    public virtual int F(int x) => x + 1;
}

internal sealed class Derived : Base
{
    public override int F(int x) => x + 1;
}

internal static class Demo
{
    private static int VirtualCall(Base b, int x) => b.F(x);

    private static int DevirtExact(int x) => new Derived().F(x);
}
```

When I benchmarked this, `DevirtExact` consistently came out roughly 2-3x faster than `VirtualCall`.

This difference is most visible in tight microbenchmarks. In real applications dominated by I/O, allocations, or larger computations, the relative impact is usually small but sometimes, it can absolutely matter.

I’m on an M2 Pro (ARM64), so I didn’t want to rely on SharpLab.io (which shows x86 output). Instead, I used this Rider plugin, which is currently at version 0.2.1:

https://plugins.jetbrains.com/plugin/29736--net-disassembler

It lets you see the JIT-generated assembly locally.

This is what the first method generated:

```asm
G_M000_IG01:
    stp     fp, lr, [sp, #-0x10]!
    mov     fp, sp

G_M000_IG02:
    ldr     x2, [x0]        # Load MethodTable pointer from object (x0 = 'this')
    ldr     x2, [x2, #0x40] # Load pointer from MethodTable at offset 0x40
    ldr     x2, [x2, #0x20] # Load actual method address at offset 0x20

G_M000_IG03:
    ldp     fp, lr, [sp], #0x10
    br      x2              # Indirect branch to target method
```

**ARM64 calling convention note:** `x0` holds the first argument (the object/"this" pointer), `w0` is the 32-bit version used for int parameters, and `lr` (link register) holds the return address.

According to the hacktricks blog which I personally use to disassemble the ARM64 commands: https://angelica.gitbook.io/hacktricks/macos-hardening/macos-security-and-privilege-escalation/macos-apps-inspecting-debugging-and-fuzzing/arm64-basic-assembly#common-instructions-arm64v8


- `stp fp, lr, [sp, #-0x10]!` saves frame pointer and return address to stack with space allocation
- `mov fp, sp` sets up new frame pointer
- The `ldr` chain loads from memory with offsets
- `ldp fp, lr, [sp], #0x10` restores registers and unwinds stack

In other words: **The method saves its execution state, loads the object's MethodTable pointer, follows it through two additional memory indirections to find the target method address, restores its state, and then performs an indirect branch to that method.**

Unlike C++'s flat vtable (typically 1-2 loads), the CLR's MethodTable structure is more complex. It stores type metadata, base class information, and method slots in a layered structure. This design supports features like type reflection and dynamic type checking, but adds indirection overhead.

Each `ldr` instruction is a memory access taking around 3 or 10 CPU cycles. The indirect branch (`br x2`) also hurts CPU branch prediction since the target address varies. Compare this to simple register operations like `add`, which take just 1 cycle.

This is virtual dispatch. Now let’s take a look at the instructions for the devirtualized version:

```asm
G_M000_IG01:
    stp     fp, lr, [sp, #-0x10]!  # Save frame pointer and return address, allocate 16 bytes
    mov     fp, sp                  # Set up new stack frame

G_M000_IG02:
    add     w0, w0, #1              # Add 1 to w0 (the x + 1 operation from F())

G_M000_IG03:
    ldp     fp, lr, [sp], #0x10     # Restore saved registers and unwind stack
    ret                              # Return to caller (lr is implied)
```

Basically: **The JIT completely devirtualized and inlined the method.** Instead of a call, it directly emitted the method body (`add w0, w0, #1` is literally the `x + 1` operation from `F()`). Simple as that, without any extra steps.

Virtual dispatch resolves the target method at runtime and performs an indirect jump, while a devirtualized call has its target known at JIT compile time and becomes a sequence of **direct** instructions.

This is why devirtualization is so fast.

By the way, .NET 10 includes many devirtualization improvements:
https://devblogs.microsoft.com/dotnet/performance-improvements-in-net-10/#deabstraction

Additionally, Profile Guided Optimization (PGO) : https://learn.microsoft.com/en-us/cpp/build/profile-guided-optimizations, can enable devirtualization at runtime even without `sealed`, by observing which types are actually used at a call site and specializing the code accordingly.

When you mark a class as `sealed`, you’re basically telling the JIT:
> "Nobody can ever inherit from this.”

If no one can derive from the type, then its virtual methods can’t be overridden. And if they can’t be overridden, the JIT **doesn’t have to treat calls** to them as virtual anymore. It knows exactly which method will run.

Once the JIT knows that, it can devirtualize the call. Once it devirtualizes, it can inline the method. And once a method is inlined, all the good optimizations kick in.

Once code is inlined, constant folding, dead code elimination, removal, and vectorization often become possible.

Inlining means the JIT literally copies the body of the method into the caller, instead of emitting a call instruction. So instead of:

```csharp
result = Add(a, b);
```

It does this:

```csharp
result = a + b;
```

So `sealed` isn’t some magic keyword that suddenly makes your code faster. What it really does is remove uncertainty.

When there are fewer unknowns, the JIT can make stronger assumptions. When the JIT can make stronger assumptions, it can replace indirect calls with direct calls. When calls become direct, they can be inlined. And once code is inlined, a whole set of optimizations becomes possible.

That's the reason why `sealed` often correlates with faster code not because it directly changes execution speed, but because it gives the JIT more room to optimize and see the world more clearly.

Don’t use `sealed` just for performance. Use it when it makes sense for design and performance is a bonus.
