"use strict";
// Run the unchanged production script with only DOM, timer and HTTP boundaries replaced.
const fs = require("node:fs");
const vm = require("node:vm");
const assert = require("node:assert/strict");
const {test} = require("node:test");
const source = fs.readFileSync("src/swu_happyrun/desktop/web/app.js", "utf8");

async function desktop(jobState = "completed") {
  const nodes = new Map(), intervals = [], calls = [];
  let offline = false, mutationFails = false, keyCounter = 0;
  const state = {service_ready:true, worker_alive:true, worker_status:"ready",
    mode:"simulation", record_verified:false, job_template:{mode:"simulation", test:"original"},
    jobs:[{job_id:"job-1", state:jobState, revision:3, reason_code:null}]};
  function element() {
    return {events:{}, children:[], firstChild:{}, disabled:false, hidden:false, textContent:"",
      addEventListener(name, handler) {this.events[name] = handler;},
      replaceChildren(...children) {this.children = children;},
      append(...children) {this.children.push(...children);}};
  }
  function get(id) {if (!nodes.has(id)) nodes.set(id, element()); return nodes.get(id);}
  vm.runInNewContext(source, {
    document:{getElementById:get, createElement:element},
    location:{hash:"", pathname:"/desktop/"}, history:{replaceState() {}},
    crypto:{randomUUID:() => `key-${++keyCounter}`},
    AbortController, setTimeout, clearTimeout, setInterval:callback => intervals.push(callback),
    fetch:async (url, options) => {
      calls.push({url, method:options.method || "GET", body:options.body,
        key:options.headers["Idempotency-Key"]});
      if (url.endsWith("/workspace")) {
        if (offline) throw new TypeError("offline");
        return {ok:true, status:200, json:async () => structuredClone(state)};
      }
      assert.equal(options.method, "POST");
      if (mutationFails) {offline = true; throw new TypeError("reply lost");}
      return {ok:true, status:200, json:async () => ({job_id:"job-2"})};
    },
  });
  await new Promise(resolve => setImmediate(resolve));
  assert.equal(intervals.length, 1, "bootstrap completed");
  return {get, state, calls, poll:intervals[0],
    offline:value => {offline = value;}, failMutation:value => {mutationFails = value;},
    posts:() => calls.filter(call => call.method === "POST"),
    history:() => get("history").children[0].children[0].events.click()};
}

test("history re-render cannot enable start after a failed workspace refresh", async () => {
  const ui = await desktop();
  assert.equal(ui.get("start").disabled, false);
  ui.offline(true); await ui.poll();
  assert.equal(ui.get("start").disabled, true);
  ui.history();
  assert.equal(ui.get("start").disabled, true);
  assert.equal(ui.get("connection").textContent, "连接中断");
});

test("action finally cannot enable start after its refresh fails", async () => {
  const ui = await desktop();
  ui.failMutation(true);
  await ui.get("start").events.click();
  assert.equal(ui.posts().length, 1);
  assert.equal(ui.get("start").disabled, true);
});

test("direct start event cannot create from stale state", async () => {
  const ui = await desktop();
  ui.offline(true); await ui.poll();
  await ui.get("start").events.click();
  assert.equal(ui.posts().length, 0);
});

test("only a successful ready refresh restores start", async () => {
  const ui = await desktop();
  ui.offline(true); await ui.poll(); ui.history();
  assert.equal(ui.get("start").disabled, true);
  ui.offline(false); ui.state.worker_status = "starting"; await ui.poll();
  assert.equal(ui.get("start").disabled, true);
  ui.state.worker_status = "ready"; await ui.poll();
  assert.equal(ui.get("start").disabled, false);
  await ui.get("start").events.click();
  assert.equal(ui.posts().length, 1);
});

test("uncertain creation keeps original body and key across disconnected history and recovery", async () => {
  const ui = await desktop();
  ui.failMutation(true); await ui.get("start").events.click();
  const original = ui.posts()[0];
  ui.history(); await ui.get("start").events.click();
  assert.equal(ui.posts().length, 1, "no retry while workspace is stale");
  ui.state.job_template = {mode:"simulation", test:"new template"};
  ui.failMutation(false); ui.offline(false); await ui.poll();
  await ui.get("start").events.click();
  assert.equal(ui.posts().length, 2);
  assert.equal(ui.posts()[1].key, original.key);
  assert.equal(ui.posts()[1].body, original.body);
});

for (const [state, command, suffix] of [["running","cancel","cancel"], ["needs_attention","recover","stop"]]) {
  test(`stale workspace does not suppress explicit ${command}`, async () => {
    const ui = await desktop(state);
    ui.offline(true); await ui.poll(); ui.history();
    assert.equal(ui.get(command).disabled, false);
    await ui.get(command).events.click();
    assert.equal(ui.posts().length, 1);
    assert.equal(ui.posts()[0].url, `/api/v1/desktop/jobs/job-1/${suffix}`);
    assert.equal(ui.get("start").disabled, true);
  });
}
