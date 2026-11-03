"use strict";
(() => {
  const $ = (id) => document.getElementById(id);
  const prefix = "/api/v1/desktop";
  const nonce = location.hash.slice(1);
  history.replaceState(null, "", location.pathname);
  const names = {queued:"等待领取",leased:"已领取",preflight:"预检中",ready:"准备就绪",running:"执行中",finishing:"收尾中",verifying:"核验中",completed:"模拟完成",succeeded:"记录核验通过",failed:"失败",cancelled:"已取消",cancelling:"等待停止确认",needs_attention:"需要处理"};
  const terminal = new Set(["completed", "failed", "cancelled", "succeeded"]);
  let state = null, selected = null, busy = false, pendingCreate = null, connected = false;
  let refreshing = false, noticeGeneration = 0;
  function tell(message) { $("notice").textContent = message; $("notice").hidden = !message; }
  async function api(path, options = {}) {
    const controller = new AbortController();
    const timer = setTimeout(() => controller.abort(), 5000);
    try {
      const response = await fetch(prefix + path, {credentials:"same-origin", cache:"no-store", ...options, signal:controller.signal,
        headers:{"Content-Type":"application/json", ...options.headers}});
      const value = await response.json();
      if (!response.ok) throw new Error(response.status === 401 ? "请关闭并重新打开本地启动器，建立工作台会话。" : response.status === 409 ? "任务状态已更新，请刷新后再操作。" : response.status === 403 ? "请从本机启动器访问工作台。" : "操作未确认，请先刷新状态，不要重复创建任务。");
      return value;
    } finally { clearTimeout(timer); }
  }
  function render() {
    if (!state) return;
    const active = state.jobs.filter(job => !terminal.has(job.state));
    $("service").textContent = state.service_ready ? "运行正常" : "尚未就绪";
    $("worker").textContent = !state.worker_alive ? "需要检查" : state.worker_status === "ready" ? "已连接" : state.worker_status === "starting" ? "连接中" : "需要检查";
    $("active-count").textContent = active.length ? `${active.length} 项进行中` : "空闲";
    $("start").disabled = busy || !state.service_ready || !state.worker_alive || state.worker_status !== "ready" || active.length > 0;
    $("start").firstChild.textContent = pendingCreate ? "核对上一次创建 " : "开始本地模拟 ";
    const current = state.jobs.find(job => job.job_id === selected) || active[0] || state.jobs[0];
    if (current) {
      selected = current.job_id;
      $("job-state").textContent = names[current.state] || current.state;
      $("current-title").textContent = current.state === "completed" ? "这一次，已完成。" : current.state === "cancelled" ? "已确认停止。" : current.state === "needs_attention" ? "保留现场，等待处理。" : current.state === "cancelling" ? "正在等待停止确认。" : "任务正在向前。";
      $("current-detail").textContent = current.reason_code ? `状态原因：${current.reason_code}` : current.state === "completed" ? "合成路线已结束，执行停止，结果已保存到本机。" : "显示的是服务端确认的状态；页面每秒自动更新。";
      $("job-id").textContent = current.job_id; $("revision").textContent = String(current.revision);
      $("cancel").hidden = terminal.has(current.state) || ["needs_attention","cancelling"].includes(current.state);
      $("recover").hidden = current.state !== "needs_attention";
      const stage = ({queued:0,leased:0,preflight:1,ready:1,running:2,finishing:3,verifying:3,completed:4})[current.state];
      [...$("steps").children].forEach((node, index) => {node.className = stage === index ? "active" : stage > index ? "done" : "";});
    }
    $("cancel").disabled = busy; $("recover").disabled = busy;
    $("history-count").textContent = `${state.jobs.length} 条`;
    if (state.jobs.length) {
      $("history").replaceChildren(...state.jobs.map(job => {
        const row = document.createElement("div"); row.className = "history-row";
        const button = document.createElement("button"); button.textContent = job.job_id;
        button.addEventListener("click", () => {selected = job.job_id; render();});
        const subtitle = document.createElement("small"); subtitle.textContent = `合成模拟 · 版本 ${job.revision}`;
        const chip = document.createElement("span"); chip.className = "pill"; chip.textContent = names[job.state] || job.state;
        row.append(button, subtitle, chip); return row;
      }));
    }
  }
  async function refresh() {
    if (!connected || refreshing) return;
    refreshing = true;
    const generation = noticeGeneration;
    try { state = await api("/workspace"); $("connection").textContent = "本机已连接"; render(); }
    catch (error) { $("connection").textContent = "连接中断"; $("start").disabled = true; if (generation === noticeGeneration) tell(error.message); }
    finally {refreshing = false;}
  }
  async function action(call) {
    if (busy) return;
    busy = true; noticeGeneration++; tell(""); render();
    try {await call();} catch(error) {tell(error.message);}
    finally {busy = false; await refresh(); render();}
  }
  $("start").addEventListener("click", () => action(async () => {
    if (!pendingCreate) pendingCreate = {spec:state.job_template, key:crypto.randomUUID()};
    const job = await api("/jobs", {method:"POST",headers:{"Idempotency-Key":pendingCreate.key},body:JSON.stringify(pendingCreate.spec)});
    selected = job.job_id; pendingCreate = null;
  }));
  $("cancel").addEventListener("click", () => action(() => api(`/jobs/${selected}/cancel`, {method:"POST",body:"{}"})));
  $("recover").addEventListener("click", () => action(() => {
    const job = state.jobs.find(item => item.job_id === selected);
    return api(`/jobs/${selected}/stop`, {method:"POST",body:JSON.stringify({expected_revision:job.revision,action:"stop_only"})});
  }));
  $("refresh").addEventListener("click", refresh);
  (async () => {
    try {
      if (nonce) await api("/session", {method:"POST",body:JSON.stringify({nonce})});
      connected = true; await refresh(); setInterval(refresh, 1000);
    } catch(error) {$("connection").textContent = "等待本地会话"; tell(error.message);}
  })();
})();
