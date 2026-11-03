"use strict";
const fs = require("node:fs");
const vm = require("node:vm");
const assert = require("node:assert/strict");
const {test} = require("node:test");
const source = fs.readFileSync("src/swu_happyrun/desktop/web/mumu.js", "utf8");

async function panel(initial, mutate) {
  const nodes = new Map(), intervals = [], calls = [];
  let state = {state:"ready", route:{points:[]}, instances:[], device_verified:true,
    stop_confirmed:false, observation_state:"observing", observation_remaining_seconds:50,
    error_code:null, ...initial};
  function element() {
    return {dataset:{}, events:{}, value:"", textContent:"", hidden:false, disabled:false,
      addEventListener(name, handler) { this.events[name] = handler; },
      setAttribute() {}, replaceChildren() {}, append() {}};
  }
  function get(id) { if (!nodes.has(id)) nodes.set(id, element()); return nodes.get(id); }
  get("mumu-speed").value = "2"; get("mumu-duration").value = "120";
  vm.runInNewContext(source, {
    document:{getElementById:get, createElement:element, createElementNS:element},
    AbortController, setTimeout, clearTimeout, setInterval:callback => intervals.push(callback),
    fetch:async (url, options) => {
      if (options.method === "POST") {
        calls.push(url);
        state = mutate({...state}, url.split("/").at(-1));
      }
      return {ok:true, status:options.method === "POST" ? 202 : 200,
        json:async () => JSON.parse(JSON.stringify(state))};
    },
  });
  await new Promise(resolve => setImmediate(resolve));
  return {get:name => get("mumu-" + name), poll:intervals[0], calls};
}

test("observation shows remaining original window", async () => {
  const ui = await panel({}, state => state);
  assert.match(ui.get("observation").textContent, /剩余 50 秒/);
});

for (const [state, command] of [["ready","start"], ["paused","resume"]]) {
  test(`${command} budget rejection clears pending without retry`, async () => {
    const ui = await panel({state}, value => ({...value,error_code:"observation_budget_insufficient"}));
    await ui.get(command).events.click();
    await ui.poll();
    assert.equal(ui.get(command).disabled, false);
    assert.equal(ui.get("stop").disabled, false);
    if (command === "start") assert.equal(ui.get("duration").disabled, false);
    assert.match(ui.get("notice").textContent, /observation_budget_insufficient/);
    assert.equal(ui.calls.length, 1);
  });
}

for (const state of ["completed", "stopped"]) {
  test(`pause returning ${state} clears pending`, async () => {
    const ui = await panel({state:"running"}, value => ({...value,state,stop_confirmed:true}));
    await ui.get("pause").events.click();
    await ui.poll();
    assert.equal(ui.get("route-file").disabled, false);
    assert.equal(ui.get("connect").disabled, true); // No discovered instance in this fixture.
    assert.equal(ui.calls.length, 1);
  });
}

for (const command of ["start", "resume", "calibrate"]) {
  test(`${command} stopped by observation deadline clears pending`, async () => {
    const ui = await panel({state:command === "resume" ? "paused" : "ready"},
      value => ({...value,state:"stopped",stop_confirmed:true,error_code:null}));
    await ui.get(command).events.click();
    await ui.poll();
    assert.equal(ui.get("route-file").disabled, false);
    assert.equal(ui.calls.length, 1);
  });
}
