"use strict";
(() => {
  const $ = (id) => document.getElementById(`mumu-${id}`);
  const prefix = "/api/v1/desktop/mumu";
  const names = {disconnected:"尚未连接",connecting:"正在连接",connected:"实例已连接",calibrating:"正在校准",ready:"校准就绪",running:"轨迹运行中",paused:"已暂停",stopping:"等待停止确认",completed:"轨迹已完成",stopped:"已确认停止",needs_attention:"需要处理",unavailable:"暂不可用"};
  const details = {disconnected:"连接实例后导入路线，完成校准才可启动。",connecting:"正在绑定实例并建立 Android 位置观察窗口。",connected:"导入路线后校准位置读回。校准完成前不会开放轨迹启动。",calibrating:"正在写入校准点并等待新鲜读回，通常需要 10–30 秒。可随时请求停止。",ready:"位置读回已校准。检查路线、速度和时长后，可显式启动轨迹。",running:"正在按单调时钟沿路线发送定位；实际位置以 Android 读回为准。",paused:"轨迹推进已暂停，最后定位保留。继续与停止均需显式操作。",stopping:"正在结束发送线程并等待在途命令结束，请等待确认。",completed:"轨迹发送已结束。学校记录尚未接入，此状态不代表乐跑记录有效。",stopped:"发送线程及在途命令已确认结束，最后定位保留。",needs_attention:"操作状态需要处理，不会自动重跑。请显式停止恢复；若上次进程中断或定位命令未确认，可能需要关闭选定 MuMu 实例才能确认停止。",unavailable:"MuMu 工具暂不可用，请检查本机安装与实例状态。"};
  const errorNames = {mumu_not_found:"未找到本机 MuMu 安装",mumu_unavailable:"MuMu 通道暂不可用",instance_not_running:"所选实例尚未运行",instance_not_found:"找不到所选实例",instance_changed:"实例身份已变化，请停止后重新连接",calibration_required:"请先完成位置读回校准",calibration_failed:"校准未通过，请检查实际读回并显式停止恢复",calibration_timeout:"校准等待新鲜定位超时",stale_sample:"定位读回已过期",observation_unavailable:"Android 位置观察窗口不可用",stop_unconfirmed:"尚未确认停止，请保留现场并继续处理",operation_in_progress:"另一项操作正在进行，请等待状态更新",invalid_state:"当前状态不允许这项操作",invalid_route:"路线格式或来源未通过校验",location_write_uncertain:"定位写入结果未确认，请显式停止恢复",device_locked:"设备已有未决会话，请先处理原会话"};
  const editable = new Set(["connected", "ready", "stopped", "completed"]);
  const stoppable = new Set(["connecting", "connected", "calibrating", "ready", "running", "paused", "needs_attention"]);
  let state = null, busy = false, polling = false, fresh = false, uncertain = false;
  let generation = 0, pending = null, lastError = "", routeKey = "", routeNodes = null;
  const finite = (value) => typeof value === "number" && Number.isFinite(value);
  const number = (value, decimals = 1) => finite(value) ? value.toFixed(decimals) : "—";
  function tell(message) { $("notice").textContent = message; $("notice").hidden = !message; }
  function errorText(code) { return code ? `${errorNames[code] || "操作未通过，请核对状态"}（${code}）` : ""; }
  function pointValid(point) { return point && finite(point.latitude) && finite(point.longitude) && Math.abs(point.latitude) <= 90 && Math.abs(point.longitude) <= 180; }
  function svg(name, attrs) {
    const node = document.createElementNS("http://www.w3.org/2000/svg", name);
    Object.entries(attrs).forEach(([key, value]) => node.setAttribute(key, value));
    return node;
  }
  function drawRoute() {
    const route = state.route;
    const points = route && Array.isArray(route.points) ? route.points.filter(pointValid) : [];
    const key = route ? `${route.route_id}:${route.revision}:${route.input_crs}` : "";
    if (key !== routeKey || !routeNodes) {
      routeKey = key; routeNodes = null; $("map-content").replaceChildren();
      $("map-empty").hidden = points.length > 1;
      if (points.length > 1) {
        const lat = points.reduce((sum, point) => sum + point.latitude, 0) / points.length;
        const factor = Math.max(0.000001, Math.cos(lat * Math.PI / 180));
        const xs = points.map(point => point.longitude * factor), ys = points.map(point => point.latitude);
        const minX = Math.min(...xs), maxX = Math.max(...xs), minY = Math.min(...ys), maxY = Math.max(...ys);
        const scale = Math.min(520 / Math.max(maxX - minX, 0.0000001), 220 / Math.max(maxY - minY, 0.0000001));
        const project = (point) => [300 + (point.longitude * factor - (minX + maxX) / 2) * scale, 150 - (point.latitude - (minY + maxY) / 2) * scale];
        const line = svg("polyline", {points:points.map(point => project(point).join(",")).join(" "),class:"mumu-route-line",fill:"none"});
        const start = project(points[0]), end = project(points[points.length - 1]);
        const marker = svg("circle", {r:"7",class:"mumu-readback-marker",visibility:"hidden"});
        $("map-content").append(line, svg("circle",{cx:start[0],cy:start[1],r:"5",class:"mumu-route-end"}), svg("circle",{cx:end[0],cy:end[1],r:"5",class:"mumu-route-end"}), marker);
        routeNodes = {project, marker};
      }
    }
    const comparable = route && route.input_crs === "WGS84";
    if (routeNodes) {
      const show = comparable && pointValid(state.sample);
      routeNodes.marker.setAttribute("visibility", show ? "visible" : "hidden");
      if (show) {
        const position = routeNodes.project(state.sample);
        const inBounds = position[0] >= 10 && position[0] <= 590 && position[1] >= 10 && position[1] <= 290;
        routeNodes.marker.setAttribute("visibility", inBounds ? "visible" : "hidden");
        routeNodes.marker.setAttribute("cx", position[0]); routeNodes.marker.setAttribute("cy", position[1]);
        $("map-note").textContent = inBounds ? "按路线范围等比例绘制" : "实际读回在预览范围外";
      } else $("map-note").textContent = comparable ? "等待实际读回" : "坐标基准不同，读回单独显示";
    } else $("map-note").textContent = "未导入路线";
    $("route-info").textContent = points.length ? `${points.length} 个路点 · ${route.input_crs} · 版本 ${String(route.revision).slice(0, 12)}` : "尚未导入路线";
  }
  function render() {
    if (!state) return;
    const current = state.state;
    const stopUnconfirmed = ["stopped","completed"].includes(current) && !state.stop_confirmed;
    $("state").textContent = fresh ? stopUnconfirmed ? "停止待确认" : names[current] || "未知状态" : "连接中断";
    $("state").dataset.state = current;
    $("detail").textContent = !fresh ? "本地服务状态暂未确认；不会自动重复操作。若设备可能仍活动，请显式请求停止并等待确认。" : stopUnconfirmed ? "尚未取得发送线程与在途命令结束确认。请显式停止恢复，不会自动开始另一条轨迹。" : details[current] || "请核对工具状态；未知状态不会开放轨迹启动。";
    const instances = Array.isArray(state.instances) ? state.instances : [];
    const instanceKey = JSON.stringify(instances.map(item => [item.index,item.name,item.running]));
    if ($("instance").dataset.options !== instanceKey) {
      const selected = $("instance").value;
      $("instance").replaceChildren();
      if (!instances.length) {
        const option = document.createElement("option"); option.value = ""; option.textContent = "未发现运行中的实例"; $("instance").append(option);
      }
      instances.forEach(item => {
        const option = document.createElement("option"); option.value = String(item.index);
        option.textContent = `${item.name || "MuMu"} · #${item.index}${item.running ? "" : " · 未运行，可检查恢复"}`; $("instance").append(option);
      });
      const previous = instances.find(item => String(item.index) === selected);
      const bound = instances.find(item => String(item.index) === String(state.instance_index));
      const first = instances.find(item => item.running) || instances[0];
      $("instance").value = previous ? String(previous.index) : bound ? String(bound.index) : first ? String(first.index) : "";
      $("instance").dataset.options = instanceKey;
    }
    const locked = busy || !!pending || !fresh;
    const canConnect = ["disconnected","unavailable","stopped","completed"].includes(current) && !uncertain && !stopUnconfirmed;
    $("instance").disabled = locked || !canConnect;
    $("connect").disabled = locked || !canConnect || !$("instance").value;
    $("route-file").disabled = locked || uncertain || stopUnconfirmed || !editable.has(current);
    $("calibrate").disabled = locked || uncertain || stopUnconfirmed || !editable.has(current) || !state.route;
    $("calibrate").textContent = current === "calibrating" ? "正在校准读回…" : "校准位置读回";
    $("start").disabled = locked || uncertain || current !== "ready" || !state.device_verified || !state.route;
    $("start").hidden = ["running","paused"].includes(current);
    $("pause").hidden = current !== "running"; $("pause").disabled = locked;
    $("resume").hidden = current !== "paused"; $("resume").disabled = locked || uncertain;
    $("stop").disabled = (busy && pending === "stop") || current === "stopping" || (!stoppable.has(current) && !uncertain && !stopUnconfirmed);
    $("stop").textContent = current === "stopping" ? "等待停止确认…" : current === "needs_attention" || uncertain || stopUnconfirmed ? "显式停止恢复" : "停止发送";
    $("speed").disabled = locked || ["running","paused","calibrating","stopping","needs_attention"].includes(current);
    $("duration").disabled = $("speed").disabled;
    const instance = instances.find(item => String(item.index) === String(state.instance_index));
    $("device").textContent = state.instance_index != null ? `实例 #${state.instance_index} · MuMu ${state.host_version || "版本未知"} · Android ${instance?.android_version || "版本未知"}${state.android_api ? ` / API ${state.android_api}` : ""}` : "尚未绑定实例；只会控制你选择的运行实例。";
    const progress = state.progress || {};
    $("distance").textContent = `${number(progress.distance_m)} / ${number(progress.total_distance_m)} m`;
    $("elapsed").textContent = `${number(progress.elapsed_seconds,0)} 秒`;
    $("progress").value = finite(progress.progress) ? Math.max(0, Math.min(1, progress.progress)) : 0;
    $("sample").textContent = pointValid(state.sample) ? `${number(state.sample.latitude,6)}, ${number(state.sample.longitude,6)}${finite(state.sample.accuracy) ? ` · ±${number(state.sample.accuracy)} m` : ""}` : "等待新鲜定位";
    $("error").textContent = finite(state.max_error_m) ? `${number(state.max_error_m,2)} m` : "尚未确认";
    $("writes").textContent = Number.isSafeInteger(state.writes) ? String(state.writes) : "—";
    const observations = {active:"正在观察",observing:"正在观察",running:"正在观察",stopped:"已结束",starting:"正在建立",unavailable:"不可用",fresh:"新鲜读回",stale:"读回过期",closed:"已关闭",ready:"观察已就绪"};
    $("observation").textContent = state.observation_state ? observations[state.observation_state] || state.observation_state : "尚未连接";
    if (state.error_code && state.error_code !== lastError) { lastError = state.error_code; tell(errorText(state.error_code)); }
    if (!state.error_code) lastError = "";
    drawRoute();
  }
  async function request(path, body) {
    const controller = new AbortController(), timer = setTimeout(() => controller.abort(), 5000);
    try {
      const response = await fetch(prefix + path, {method:body === undefined ? "GET" : "POST",credentials:"same-origin",cache:"no-store",headers:{"Content-Type":"application/json"},...(body === undefined ? {} : {body:JSON.stringify(body)}),signal:controller.signal});
      let value = {}; try { value = await response.json(); } catch { /* The status still determines the error. */ }
      if (!response.ok) {
        const code = value.error?.code || value.error_code || value.detail?.error_code || (typeof value.detail === "string" ? value.detail : null);
        const error = new Error(response.status === 401 ? "请从本机启动器重新建立工作台会话。" : response.status === 403 ? "请求来源未通过检查，请从本机启动器访问工作台。" : errorText(code) || (response.status === 409 ? "状态已变化，请核对当前状态后再操作。" : "本地操作未确认，请核对状态并显式停止恢复。"));
        error.status = response.status; throw error;
      }
      return value;
    } finally { clearTimeout(timer); }
  }
  async function poll() {
    if (polling) return;
    polling = true; const started = generation;
    try {
      const next = await request("");
      if (started !== generation) return;
      state = next; fresh = true;
      const target = {connect:["connected","ready"],route:["connected","ready","stopped","completed"],calibrate:["ready"],start:["running","completed"],pause:["paused"],resume:["running","completed"],stop:["stopped","completed"]};
      if (pending && (target[pending]?.includes(state.state) || ["needs_attention","unavailable"].includes(state.state))) pending = null;
      if (state.stop_confirmed) uncertain = false;
      render();
    } catch (error) {
      if (error.status === 401 && !state) return;
      fresh = false;
      if (state) render();
      tell(error.status ? error.message : "本地连接暂时中断，正在刷新状态。操作不会自动重试。");
    } finally { polling = false; }
  }
  async function action(command, body = {}) {
    if (busy && command !== "stop") return;
    if (pending && command !== "stop") return;
    generation++; busy = true; pending = command; tell(""); render();
    const currentGeneration = generation;
    try {
      const result = await request(`/${command}`, body);
      if (currentGeneration !== generation) return;
      if (state && typeof result.state === "string") state = {...state,state:result.state};
      if (command === "route") pending = null;
    } catch (error) {
      if (currentGeneration !== generation) return;
      pending = null;
      if (!error.status || error.status >= 500) uncertain = true;
      tell(error.status ? error.message : "操作结果未确认，不会自动重试。请等待当前状态并显式停止恢复。");
    } finally {
      if (currentGeneration === generation) { busy = false; render(); await poll(); }
    }
  }
  $("instance").addEventListener("change", render);
  $("connect").addEventListener("click", () => action("connect", {instance_index:$("instance").value}));
  $("route-file").addEventListener("change", async () => {
    const file = $("route-file").files[0];
    if (!file) return;
    try {
      if (file.size > 2 * 1024 * 1024) throw new Error("路线文件过大，请使用 2 MB 以内的 RouteProfile JSON。");
      const route = JSON.parse(await file.text());
      if (!route || !Array.isArray(route.points) || route.points.length < 2 || route.points.length > 10000 || !route.points.every(pointValid) || !["WGS84","GCJ02","BD09"].includes(route.input_crs) || typeof route.route_id !== "string" || !/^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i.test(route.route_id) || typeof route.revision !== "string" || !/^[0-9a-f]{64}$/.test(route.revision) || typeof route.source_ref !== "string" || !route.source_ref.trim()) throw new Error("请选择完整的 RouteProfile JSON：有效 UUID、64 位 revision、坐标基准、至少两个真实路点及来源。完整约束由本地服务校验。");
      await action("route", {route});
    } catch(error) { tell(error instanceof SyntaxError ? "无法解析 JSON，请检查路线文件格式。" : error.message); }
    finally { $("route-file").value = ""; }
  });
  $("calibrate").addEventListener("click", () => action("calibrate"));
  $("start").addEventListener("click", () => {
    const speed = Number($("speed").value), duration = Number($("duration").value);
    if (!finite(speed) || speed < 0.3 || speed > 8 || !Number.isInteger(duration) || duration < 5 || duration > 1800) { tell("请输入 0.3–8 m/s 的速度，以及 5–1800 秒的整数时长。"); return; }
    action("start", {speed_mps:speed,maximum_duration_seconds:duration});
  });
  ["pause","resume","stop"].forEach(command => $(command).addEventListener("click", () => action(command)));
  poll(); setInterval(poll, 1000);
})();
