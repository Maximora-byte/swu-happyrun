# Foreground HTTP connection ownership

## Proposed policy

Each HttpsAgentClient request now sets `Connection: close` before its first network I/O. This is request-local HTTP connection policy, avoiding reliance on a platform-global idle pool after the foreground owner releases its client. No process-global keep-alive property, trust manager, hostname verifier, cipher selection, timeout, retry, cancellation action, server TLS setting or acceptance assertion changes. The existing five-second request budget remains unchanged.

This trades connection reuse for clearer ownership and potentially additional TLS-handshake latency. The paired real Python-server fixture uses HTTP/1.1. The separate seven-case TLS helper uses BaseHTTPRequestHandler's default HTTP/1.0 responses; it verifies TLS and rejection semantics, not HTTP/1.1 pooling. Other proxy/protocol combinations have not been verified. This is not a general pool eviction API and does not close unrelated clients' sockets.

## Evidence and scope

The ba990 API 35 artifact SHA-256 is `86eca83d4bca41709fbfd08fa725fc5766821f004592ab057f9bfef7641a21f8`. Its two-job Activity scenario passed its body, strict JUnit/exit checks, local stop checks and host cleanup. Fixture shutdown alone failed: one closing TLS connection in SHUTDOWN, zero ASGI tasks, and the latest parsed route categorized as agent. That category is not authenticated ownership evidence. Host force-stop had already completed. Thirteen later scenarios were correctly not run; Back/Home behavior cannot be inferred from this run.

Official AOSP tag `android-15.0.0_r1` provides a mechanism supporting the strategy:

- [HttpEngine.java](https://android.googlesource.com/platform/external/okhttp/+/refs/tags/android-15.0.0_r1/okhttp/src/main/java/com/squareup/okhttp/internal/http/HttpEngine.java): the request or response close header triggers noNewStreams (line 752).
- [StreamAllocation.java](https://android.googlesource.com/platform/external/okhttp/+/refs/tags/android-15.0.0_r1/okhttp/src/main/java/com/squareup/okhttp/internal/http/StreamAllocation.java): release can detach the allocation from a pooled connection; subsequent cancel operates only on a still-associated stream or connection. noNewStreams participates in socket disposal once allocations are released.
- [HttpURLConnectionImpl.java](https://android.googlesource.com/platform/external/okhttp/+/refs/tags/android-15.0.0_r1/okhttp-urlconnection/src/main/java/com/squareup/okhttp/internal/huc/HttpURLConnectionImpl.java): disconnect delegates cancellation and does not itself guarantee eviction of all idle pooled sockets.
- [Http1xStream.java](https://android.googlesource.com/platform/external/okhttp/+/refs/tags/android-15.0.0_r1/okhttp/src/main/java/com/squareup/okhttp/internal/http/Http1xStream.java): a zero-length source completes its input during construction. Therefore the 204 return path is not established as an unconsumed-body leak and remains unchanged.

These fixed source references are not a claim that the exact emulator binary has been traced instruction by instruction. The observed Android shutdown failure still requires actual API 35 revalidation after this candidate.

## Verification

Three new JUnit ownership tests failed against the original client, then passed with the single-header change. All 15 selected protocol/transport tests passed, including existing five-second deadline and asynchronous-close behavior. The new tests inspect the real production client's injected connection before output or response I/O for 204 claims, 200 GET and rejected responses; they do not simulate Android's pool implementation.

Seven real JVM HTTPS cases passed with default certificate/hostname checks and only a temporary per-process test trust store: normal, untrusted certificate, hostname mismatch, redirect, oversize, request timeout and post-close rejection. All temporary trust/key material was removed.

A separate real Python HTTPS fixture received hello plus three empty claims. The JVM remained alive, with its client closed, while the unmodified fixture shut down naturally. In one bounded baseline run, the aggregate observation did not show all four requests using the close header and shutdown took 9.919 seconds, still passing the existing ten-second limit. With the candidate, all four server-observed requests carried the close header and shutdown took 0.150 seconds. A further bounded paired capture recorded each request as a fixed enum: baseline `[not_close, not_close, not_close, not_close]` with natural shutdown in 9.868 seconds; candidate `[close, close, close, close]` with natural shutdown in 0.131 seconds. Both retained the same fixture and budget, and the JVM remained alive. These are supporting comparisons, not timing guarantees or a reproduced Android failure. An initial probe setup used extra device-registration fields and was rejected before the agent scenario; that setup error was retained and corrected to the existing two-field contract.

Required next acceptance: real Android TLS/foreground scenarios, including idle heartbeats, two jobs, disconnect, Back/Home and rotation, followed by successful natural fixture shutdown. Preserve any failure and the original timeout limits. The earlier lost-event and Back/Home root causes remain unresolved until independently evidenced.
