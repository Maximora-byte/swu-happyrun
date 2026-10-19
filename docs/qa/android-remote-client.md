# Native remote protocol and HTTPS client

This module is opt-in and has no Activity, service, startup hook, default URL, or saved token. Constructing `HttpsAgentClient(origin, token)` performs no I/O. The foreground owner explicitly calls the fixed `AgentClient` operations and must close on leaving. The token is held only in memory; close drops the client's reference. Java strings and platform connection internals cannot be reliably zeroized.

Only simulation jobs are accepted. Advertised observation is always backend=fake, capabilities=[], app_version=null; events always have empty evidence. No app-record success can be emitted. Protocol fields are exact, duplicate JSON keys are rejected, numeric coercions are rejected, canonical UUID/digest/time checks apply. The implementation intentionally rejects device jobs, succeeded state, sub-microsecond timestamps, counters outside signed 64-bit range and any unknown/missing fields.

HTTPS uses platform default certificate and hostname verification without custom trust or hostname callbacks. Base URL must be an HTTPS origin, without credentials, path, query, or fragment. Redirects and implicit application retries are disabled. Responses are UTF-8 JSON bounded at 256 KiB and parsed with depth/item limits. Exceptions carry only fixed error codes, status and retry/ambiguity flags; response bodies and tokens are not logged. Request paths are generated from validated IDs.

The caller budget is five seconds including DNS/open/connect/write/read. A single daemon request worker bounds uninterruptible platform calls. On timeout or interruption the client closes permanently, drops its token reference, interrupts the worker and requests asynchronous disconnect; it never starts a replacement request worker. Android/Java DNS or I/O may continue briefly despite cancellation. The owner must treat mutating timeout/transport/invalid-response results as uncertain and reconcile before further actions. There is no guarantee a timed-out server mutation did not happen.

## Tests and limits

JUnit suites: StrictJsonTest (2), ProtocolCodecTest (4), HttpsAgentClientTest (8): 14 tests. Transport uses fake HttpsURLConnection, including an actual five-second wall-clock timeout against uncooperative open. This validates wrapper behavior, not real TLS or Android networking.

`PYTHONPATH=src python scripts/check_remote_protocol_interop.py JAVA_TEST_CLASSPATH` invokes a Java test bridge and the repository's actual Python v1 Pydantic models: 16 shared positive/negative JobView cases plus Java-generated JobView/AgentHello/JobEvent accepted by Python. No credentials or network are involved. Compile the test bridge together with protocol tests and JUnit on the classpath.

Actual HTTPS server interoperability, platform certificate rejection, emulator lifecycle and APK packaging remain pending independent integration. A debug-only test CA may be installed/configured by a dedicated acceptance fixture; release trust must remain untouched. Test fixtures must use disposable credentials only and never upload them as artifacts.
