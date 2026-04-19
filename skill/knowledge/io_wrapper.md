---
name: io-wrapper
type: domain-knowledge
topic: File-Like Wrapper + Counters
token_cost: 120
keywords: [io wrapper, wrap file, read counter, write counter, nreads, nwrites, context manager, __enter__, __exit__, passthrough, delegate, paasio, MetaRead, MetaWrite]
user-invocable: false
---
To wrap a file-like and count reads/writes: store the wrapped object as self._wrapped. Implement read(size=-1) (or readable/readinto as needed) by delegating to self._wrapped.read(size) and incrementing counters by the length of the RETURNED bytes (not the requested size — a short read counts for what it returned). Same for write: call self._wrapped.write(data) and increment nwrites by the RETURN VALUE (number of bytes actually written), or by len(data) if the wrapped write returns None. Expose read_bytes/nreads and write_bytes/nwrites as properties or attributes. Context-manager support: __enter__ returns self; __exit__ calls self._wrapped.__exit__ (or close()) and forwards the exception info. Don't forget close() as a plain method for non-context-manager use. Edge case: thread safety — if the test uses threads, wrap counter updates in a threading.Lock.
