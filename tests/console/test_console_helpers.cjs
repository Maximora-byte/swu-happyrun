// Execute the actual dependency-free production validation/time helpers in Node.
const fs = require("node:fs");
const vm = require("node:vm");
const assert = require("node:assert/strict");
const source = fs.readFileSync("src/swu_happyrun/server/web/app.js", "utf8");
const constants = source.slice(
  source.indexOf("  const uuidPattern"),
  source.indexOf("  const terminal"),
);
const dates = source.slice(
  source.indexOf("  function stamp("),
  source.indexOf("  function stateChip("),
);
const validation = source.slice(
  source.indexOf("  function validateSpec("),
  source.indexOf("  function formSpec("),
);
const context = vm.createContext({ Intl, Date, Error, Object, Array });
vm.runInContext(
  `${constants}\n${dates}\n${validation}\nglobalThis.helpers={utcDate,localDate,validateSpec,checkUUID,validateJobView};`,
  context,
);
const { utcDate, localDate, validateSpec, checkUUID, validateJobView } =
  context.helpers;
assert.equal(utcDate("2026-10-19T08:30"), "2026-10-19T00:30:00.000Z");
assert.equal(localDate("2026-10-18T20:30:00Z"), "2026-10-19T04:30:00");
assert.throws(() => utcDate("2026-10-19"), /时间/);
assert.throws(() => checkUUID("<img src=x onerror=alert(1)>"), /UUID/);
const spec = {
  protocol_version: 1,
  mode: "simulation",
  profile_id: "00000000-0000-0000-0000-000000000001",
  profile_revision: "a".repeat(64),
  route_id: "00000000-0000-0000-0000-000000000002",
  route_revision: "b".repeat(64),
  device_id: "00000000-0000-0000-0000-000000000003",
  not_before: "2026-10-19T00:00:00Z",
  deadline: "2026-10-19T01:00:00Z",
  expected_app_version: null,
};
assert.equal(validateSpec(spec), spec);
assert.throws(() => validateSpec({ ...spec, unexpected: true }), /未知/);
assert.throws(
  () => validateSpec({ ...spec, profile_revision: "fake" }),
  /revision/,
);
assert.throws(() => validateSpec({ ...spec, mode: "device" }), /版本/);
assert.throws(
  () => validateSpec({ ...spec, expected_app_version: "1" }),
  /版本/,
);
assert.throws(
  () => validateSpec({ ...spec, deadline: spec.not_before }),
  /截止/,
);
assert.throws(
  () => validateSpec({ ...spec, not_before: "2026-10-19T08:00:00+08:00" }),
  /UTC/,
);
assert.throws(
  () => validateSpec({ ...spec, protocol_version: true }),
  /protocol_version/,
);
assert.equal(
  validateSpec({ ...spec, mode: "device", expected_app_version: "confirmed-1" })
    .mode,
  "device",
);
assert(!source.includes("innerHTML"));
assert(!/localStorage|sessionStorage/.test(source));
assert(/redirect:\s*["']error["']/.test(source));
console.log("PASS: 16 validation, UTC+8 conversion and source security checks");

assert.throws(() => utcDate("2026-02-30T08:00"), /日期|时间/);
assert.throws(
  () => validateSpec({ ...spec, not_before: "2026-02-30T00:00:00Z" }),
  /日期|时间/,
);
assert.throws(() => localDate("2026-10-19T00:00:00.123456Z"), /整秒/);
assert.equal(localDate("2026-10-19T00:00:00.000Z"), "2026-10-19T08:00:00");
const job = {
  job_id: spec.device_id,
  spec,
  state: "queued",
  revision: 0,
  fence: 0,
  desired_state: "run",
  agent_id: null,
  reason_code: null,
  resume_phase: null,
  recovery_action: null,
  run_session_id: null,
};
assert.equal(validateJobView(job), job);
for (const bad of [
  {},
  null,
  { ...job, spec: null },
  { ...job, revision: -1 },
  { ...job, fence: 1.5 },
  { ...job, state: "invented" },
  { ...job, job_id: "bad" },
  { ...job, agent_id: {} },
  { ...job, reason_code: {} },
  { ...job, resume_phase: [] },
  { ...job, recovery_action: "unknown" },
]) {
  assert.throws(() => validateJobView(bad), /响应/);
}

async function creationBoundary(firstStatus) {
  const elements = new Map();
  function node() {
    return {
      value: "",
      hidden: false,
      disabled: false,
      children: [],
      events: {},
      className: "",
      textContent: "",
      addEventListener(name, fn) {
        this.events[name] = fn;
      },
      replaceChildren(...items) {
        this.children = items;
      },
      append(...items) {
        this.children.push(...items);
      },
      focus() {},
      reset() {},
    };
  }
  function get(id) {
    if (!elements.has(id)) elements.set(id, node());
    return elements.get(id);
  }
  get("token").value = "test-admin";
  get("job-mode").value = "simulation";
  get("job-form").elements = { expected_app_version: node() };
  let form = {
    ...spec,
    not_before: "2026-10-19T08:00",
    deadline: "2026-10-19T09:00",
    expected_app_version: "",
  };
  const posts = [];
  let releaseRetry;
  const fakeFetch = async (url, options) => {
    let body = {};
    let status = 200;
    if (url === "/api/v1/devices" || url === "/api/v1/schedules") body = [];
    else if (url.startsWith("/api/v1/jobs?"))
      body = { items: [], next_cursor: null };
    else if (url === "/api/v1/jobs" && options.method === "POST") {
      posts.push({
        key: options.headers["Idempotency-Key"],
        body: options.body,
      });
      if (posts.length === 2 && firstStatus === 200)
        await new Promise((resolve) => {
          releaseRetry = resolve;
        });
      status = posts.length === 1 ? firstStatus : 200;
      body = status === 200 ? {} : { error: { code: "invalid_input" } };
    }
    return {
      ok: status >= 200 && status < 300,
      status,
      json: async () => body,
    };
  };
  const sandbox = vm.createContext({
    Intl,
    Date,
    Error,
    Object,
    Array,
    Set,
    Number,
    JSON,
    TypeError,
    AbortController,
    setTimeout,
    clearTimeout,
    document: {
      getElementById: get,
      createElement: node,
      querySelectorAll: () => [],
    },
    window: { addEventListener() {} },
    location: { protocol: "http:", hostname: "127.0.0.1" },
    crypto: require("node:crypto").webcrypto,
    fetch: fakeFetch,
    FormData: class {
      constructor() {
        return Object.entries(form);
      }
    },
  });
  vm.runInContext(source, sandbox);
  const settle = () => new Promise((resolve) => setImmediate(resolve));
  get("connect-form").events.submit({ preventDefault() {}, submitter: node() });
  await settle();
  await settle();
  get("job-form").events.submit({
    preventDefault() {},
    submitter: get("create-job"),
  });
  await settle();
  await settle();
  assert.equal(posts.length, 1);
  assert.equal(get("job-fields").disabled, firstStatus === 200);
  if (firstStatus !== 200) form = { ...form, route_id: spec.device_id };
  get("job-form").events.submit({
    preventDefault() {},
    submitter: get("create-job"),
  });
  await settle();
  await settle();
  assert.equal(posts.length, 2);
  if (firstStatus === 200) {
    assert.equal(get("reset-creation").disabled, true);
    get("reset-creation").events.click();
    await settle();
    assert.equal(get("job-fields").disabled, true);
    releaseRetry();
    await settle();
    await settle();
    assert.equal(posts[0].key, posts[1].key);
    assert.equal(posts[0].body, posts[1].body);
  } else {
    assert.notEqual(posts[0].key, posts[1].key);
    assert.notEqual(posts[0].body, posts[1].body);
  }
}
(async () => {
  await creationBoundary(200);
  await creationBoundary(422);
  await creationBoundary(403);
  console.log(
    "PASS: malformed 2xx preserves key/body; definite 422/403 unlock editing",
  );
})().catch((error) => {
  console.error(error);
  process.exitCode = 1;
});
