---
title: "Python Async Programming Guide"
author: "Jenar"
category: "engineering"
tags: [python, async, concurrency, programming]
date: 2025-03-10
source: https://example.com/python-async
---

# Python Async Programming Guide

Python's `asyncio` library enables concurrent I/O-bound operations without threads. Understanding when and how to use async is critical for building performant applications.

## The Event Loop

The event loop is the core of async Python. It runs coroutines, handles I/O callbacks, and schedules tasks. There is typically one event loop per thread.

```python
import asyncio

async def main():
    await asyncio.sleep(1)
    print("Done")

asyncio.run(main())
```

## Coroutines vs Threads

Use async/await for I/O-bound work (network requests, file reads, database queries). Use threads or processes for CPU-bound work (image processing, ML inference, cryptography).

The key insight: async doesn't make code faster — it makes waiting cheaper. While one coroutine waits for a network response, another can run.

## Common Patterns

### Parallel requests with gather

```python
async def fetch_all(urls):
    async with aiohttp.ClientSession() as session:
        tasks = [fetch(session, url) for url in urls]
        results = await asyncio.gather(*tasks)
    return results
```

### Timeouts

```python
async def fetch_with_timeout(url):
    try:
        async with asyncio.timeout(5.0):
            return await fetch(url)
    except asyncio.TimeoutError:
        return None
```

## Common Mistakes

- Calling blocking functions (requests, time.sleep) inside async code blocks the entire event loop
- Creating a new event loop when one already exists causes errors
- Forgetting to await a coroutine — it silently does nothing

## asyncio in Production

For web servers, use ASGI frameworks like FastAPI or Starlette. For background tasks, consider Celery with a message broker or asyncio.Queue for in-process queues.
