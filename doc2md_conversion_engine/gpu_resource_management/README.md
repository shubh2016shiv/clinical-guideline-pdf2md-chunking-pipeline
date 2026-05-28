# GPU Resource Management

Two small primitives:

| Class | Job |
|---|---|
| `ExclusiveGPUContextManager` | Makes sure only one engine touches the GPU at a time |
| `GPUVRAMUsageMonitor` | Checks if there is enough free VRAM before starting |

---

## The lock leak problem (and how we fixed it)

This is not GPU-specific. It is about Python's `async with` protocol and how it
interacts with any resource that must be released — a lock, a file handle, a
socket, a database connection.

### The rule Python follows

Python has a simple rule for `async with`:

1. It calls `__aenter__`.
2. **If `__aenter__` returns normally**, the body runs, and then `__aexit__` is always called — even if the body raises.
3. **If `__aenter__` raises**, Python skips `__aexit__` entirely. The body never runs, so there is nothing to clean up.

Step 3 is where leaks happen.

### How a lock leaks

Imagine this sequence inside `__aenter__`:

```
await lock.acquire()       # Step A: we now own the lock
do_something()             # Step B: this raises!
return self                # Step C: never reached
```

Step A succeeds. We own the lock.  
Step B raises.  
Step C never happens, so `__aenter__` never returns.  
Python sees `__aenter__` raised, so it **does not call `__aexit__`**.  
The lock stays held forever.  

Every future `await lock.acquire()` blocks indefinitely. The whole process is
deadlocked.

### Where the gap was

The old code looked like this:

```python
async def __aenter__(self):
    await lock.acquire()               # lock acquired
    self.acquired_time = time.monotonic()
    logger.info("acquired ...")        # <-- if this raises, we leak
    return self
```

`logger.info()` lives **between** `acquire()` and `return self`. It is a
fallible operation — a custom log handler, a disk-full error, or a task
cancellation can make it raise. If it does, the lock leaks.

That gap was 3 lines wide. Any code added there in the future (metrics hooks,
tracing calls, state validation) would expand the gap.

### The fix: eliminate the gap entirely

After acquire, there is now **exactly one statement** before `return self`:

```python
async def __aenter__(self):
    # All fallible work (logging, timing, validation) lives HERE,
    # BEFORE the lock is acquired.
    self._wait_started_at = time.monotonic()
    logger.info("waiting ...")

    await lock.acquire()               # lock acquired

    self._acquired_at = time.monotonic()  # <-- the ONLY line after acquire
    return self
```

`time.monotonic()` cannot raise. It is a syscall that returns a float. That
means `__aenter__` **always** returns, which means `__aexit__` **always** runs,
which means the lock **always** gets released.

The "acquired" log message was moved into `__aexit__`, where it is combined
with the release log as a `wait_ms` field:

```
gpu.lock.released component=mineru cuda_device_id=0 held_seconds=12.345 wait_ms=1.2
```

### How we verified it

We wrote a test that reads the source code of `__aenter__` and asserts:

1. No `logger.info` (or any other call) lives between `acquire()` and `return self`.
2. The line `self._acquired_at = time.monotonic()` is present.
3. `return self` is present — meaning `__aexit__` is guaranteed to fire.

This is not a runtime test. It is a **structural assertion** that the gap
stays closed even as the code evolves. If someone adds a log line or a metrics
call after `acquire()`, the test fails immediately.

### Why not try/finally?

A `try/finally` inside `__aenter__` would also prevent the leak:

```python
await lock.acquire()
try:
    logger.info("acquired ...")    # safe: finally releases on failure
    return self
except BaseException:
    lock.release()
    raise
```

This works. But it is fragile — every new line of post-acquire code must
remember to stay inside the `try` block. It also means two code paths for
release (`__aexit__` for the happy path, the `except` block for the unhappy
path), which doubles the surface area for bugs.

The structural approach — zero fallible code between acquire and return — has
no such tax. There is one release path, in `__aexit__`, and it is always
reached.

---

## VRAM budget check

`GPUVRAMUsageMonitor` is a read-only check. It never allocates or frees GPU
memory.

- If the GPU is disabled (`enabled=False` or `force_cpu=True`), every method
  returns 0 and `assert_within_budget` raises `GPUNotAvailableError`.
- If `pynvml` (NVIDIA's Python bindings) is not installed, it logs a warning
  and returns 0 — the pipeline keeps working on CPU.
- If `pynvml` IS available, it queries current VRAM usage and compares it
  against the configured budget (`max_vram_mb`). Exceeding the budget raises
  `GPUError`.

This lets the pipeline decide whether to start a GPU-heavy operation or fall
back to CPU *before* committing GPU memory.

---

## Files

| File | Purpose |
|---|---|
| `exclusive_gpu_context_manager.py` | Process-wide async lock for GPU access |
| `gpu_vram_usage_monitor.py` | Read-only NVML VRAM queries |
