"use strict";
(() => {
  const $ = (id) => document.getElementById(id);
  const uuidPattern =
    /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/;
  const digestPattern = /^[0-9a-f]{64}$/;
  const terminal = new Set(["completed", "succeeded", "cancelled", "failed"]);
  const names = {
    queued: "等待领取",
    leased: "已领取",
    preflight: "预检中",
    ready: "准备就绪",
    running: "执行中",
    finishing: "收尾中",
    verifying: "核验中",
    cancelling: "等待停止确认",
    needs_attention: "需要关注",
    completed: "模拟完成",
    succeeded: "记录核验通过",
    failed: "失败",
    cancelled: "已取消",
  };
  let token = "",
    generation = 0,
    nextCursor = null,
    selectedJob = null,
    creation = null,
    dialogResolve = null;
  const controllers = new Set();
  const operations = new Set();
  let jobsLoad = 0,
    devicesLoad = 0,
    schedulesLoad = 0;
  function el(tag, text, className) {
    const node = document.createElement(tag);
    if (text !== undefined) node.textContent = text;
    if (className) node.className = className;
    return node;
  }
  function notice(text, error = false) {
    $("notice").textContent = text;
    $("notice").className = `notice${error ? " error" : ""}`;
    $("notice").hidden = !text;
  }
  function stamp(value) {
    const date = new Date(value);
    return Number.isNaN(date.valueOf())
      ? "未知时间"
      : new Intl.DateTimeFormat("zh-CN", {
          timeZone: "Asia/Shanghai",
          year: "numeric",
          month: "2-digit",
          day: "2-digit",
          hour: "2-digit",
          minute: "2-digit",
          second: "2-digit",
          hour12: false,
        }).format(date) + " UTC+8";
  }
  function localDate(value) {
    const fraction = /\.(\d+)Z$/.exec(value);
    if (fraction && /[1-9]/.test(fraction[1]))
      throw new Error(
        "本表单仅支持整秒时间，请先明确调整原 JobSpec 的小数秒，不会自动截断。",
      );
    const date = new Date(value);
    if (Number.isNaN(date.valueOf())) throw new Error("时间格式无效");
    return new Date(date.valueOf() + 8 * 3600000).toISOString().slice(0, 19);
  }
  function utcDate(value) {
    if (!/^\d{4}-\d\d-\d\dT\d\d:\d\d(?::\d\d)?$/.test(value))
      throw new Error("请填写有效的开始和截止时间");
    const date = new Date(`${value}+08:00`);
    if (Number.isNaN(date.valueOf())) throw new Error("时间格式无效");
    const normalized = new Date(date.valueOf() + 8 * 3600000)
      .toISOString()
      .slice(0, 19);
    if (normalized !== (value.length === 16 ? `${value}:00` : value))
      throw new Error("日期或时间不存在，请检查月份、天数和闰年。");
    return date.toISOString();
  }
  function checkUUID(value) {
    if (!uuidPattern.test(value))
      throw new Error("ID 必须是完整的小写 UUID（含连字符）");
    return value;
  }
  function stateChip(job) {
    return el(
      "span",
      names[job.state] || job.state,
      `chip ${job.state === "needs_attention" || job.state === "cancelling" ? "attention" : ["failed", "cancelled"].includes(job.state) ? "bad" : ["completed", "succeeded"].includes(job.state) ? "good" : ""}`,
    );
  }
  function empty(target, text) {
    $(target).replaceChildren(el("div", text, "empty"));
  }
  function clearSession(message = "") {
    generation++;
    token = "";
    for (const controller of controllers) controller.abort();
    controllers.clear();
    operations.clear();
    nextCursor = null;
    selectedJob = null;
    creation = null;
    for (const id of [
      "jobs-list",
      "job-detail",
      "devices-list",
      "device-options",
      "schedules-list",
    ])
      $(id).replaceChildren();
    for (const id of ["connect-form", "job-form", "job-lookup", "device-form"])
      $(id).reset();
    $("import-job").value = "";
    $("import-job").disabled = false;
    $("job-fields").disabled = false;
    $("load-more").hidden = true;
    $("job-detail").hidden = true;
    $("workspace").hidden = true;
    $("connection-panel").hidden = false;
    $("logout").hidden = true;
    $("connection-state").textContent = "未连接";
    $("connection-state").className = "chip";
    $("device-count").textContent = "—";
    $("health-state").textContent = "待检查";
    $("ready-state").textContent = "待检查";
    $("creation-state").textContent =
      "不会自动生成配置 revision、学校规则或路线。";
    $("reset-creation").hidden = true;
    for (const button of document.querySelectorAll("button"))
      button.disabled = false;
    if ($("confirm-dialog").open) $("confirm-dialog").close();
    finishConfirm(false);
    updateMode();
    notice(message, Boolean(message));
  }
  async function request(
    path,
    { method = "GET", body, key, publicCall = false } = {},
  ) {
    const epoch = generation,
      controller = new AbortController();
    controllers.add(controller);
    let timedOut = false;
    const timeout = setTimeout(() => {
      timedOut = true;
      controller.abort();
    }, 5000);
    try {
      const headers = { Accept: "application/json" };
      if (!publicCall) {
        if (!token) throw new Error("请先连接管理员账户");
        headers.Authorization = `Bearer ${token}`;
      }
      if (body !== undefined) headers["Content-Type"] = "application/json";
      if (key) headers["Idempotency-Key"] = key;
      const response = await fetch(`/api/v1${path}`, {
        method,
        headers,
        body: body === undefined ? undefined : JSON.stringify(body),
        signal: controller.signal,
        cache: "no-store",
        credentials: "omit",
        redirect: "error",
      });
      if (epoch !== generation)
        throw Object.assign(new Error("连接已退出"), { stale: true });
      if (response.status === 401) {
        clearSession("令牌已失效，请重新连接。私有内容已清除。");
        throw Object.assign(new Error("请重新连接"), { stale: true });
      }
      let data = null;
      try {
        data = await response.json();
      } catch {
        if (response.ok)
          throw new Error("服务响应无法解析，请刷新核对实际状态");
      }
      if (epoch !== generation)
        throw Object.assign(new Error("连接已退出"), { stale: true });
      if (!response.ok) {
        const messages = {
          403: "当前令牌不是 ADMIN，或无权执行此操作",
          404: "未找到该资源",
          409: "状态或版本冲突，请刷新并核对；不会自动重复执行",
          422: "输入不符合协议，请核对 ID、revision、时间及模式",
          503: "服务暂时不可用，请稍后刷新",
        };
        throw Object.assign(
          new Error(
            messages[response.status] ||
              `服务请求失败（HTTP ${response.status}）`,
          ),
          { status: response.status, code: data?.error?.code },
        );
      }
      return data;
    } catch (error) {
      if (epoch !== generation) throw Object.assign(error, { stale: true });
      if (error.name === "AbortError")
        throw new Error(
          timedOut
            ? "请求超时，结果尚未确认。请核对状态后重试。"
            : "请求已取消",
        );
      if (error instanceof TypeError)
        throw new Error("网络断开或服务不可达，结果尚未确认。");
      throw error;
    } finally {
      clearTimeout(timeout);
      controllers.delete(controller);
    }
  }
  async function run(name, button, action) {
    if (operations.has(name)) return;
    const epoch = generation;
    operations.add(name);
    if (button) button.disabled = true;
    if (name === "creation") {
      $("create-job").disabled = true;
      $("reset-creation").disabled = true;
    }
    try {
      await action(epoch);
    } catch (error) {
      if (!error.stale && epoch === generation) notice(error.message, true);
    } finally {
      if (epoch === generation) {
        operations.delete(name);
        if (button) button.disabled = false;
        if (name === "creation") {
          $("create-job").disabled = false;
          $("reset-creation").disabled = false;
        }
      }
    }
  }
  function finishConfirm(accepted) {
    const resolve = dialogResolve;
    dialogResolve = null;
    if (resolve) resolve(accepted);
  }
  function confirm(title, text) {
    if (dialogResolve) return Promise.resolve(false);
    $("confirm-title").textContent = title;
    $("confirm-text").textContent = text;
    $("confirm-dialog").showModal();
    $("confirm-back").focus();
    return new Promise((resolve) => {
      dialogResolve = resolve;
    });
  }
  $("confirm-back").addEventListener("click", () => {
    $("confirm-dialog").close();
    finishConfirm(false);
  });
  $("confirm-accept").addEventListener("click", () => {
    $("confirm-dialog").close();
    finishConfirm(true);
  });
  $("confirm-dialog").addEventListener("cancel", () => finishConfirm(false));
  $("confirm-dialog").addEventListener("close", () => {
    finishConfirm(false);
    $("confirm-text").textContent = "";
  });
  $("logout").addEventListener("click", () => {
    clearSession();
    $("token").focus();
  });
  $("connect-form").addEventListener("submit", (event) => {
    event.preventDefault();
    if (
      location.protocol !== "https:" &&
      !(
        location.protocol === "http:" &&
        ["localhost", "127.0.0.1", "[::1]"].includes(location.hostname)
      )
    ) {
      notice(
        "为保护令牌，仅允许 HTTPS 或本机回环 HTTP 地址连接。请通过可信 HTTPS 打开此服务。",
        true,
      );
      return;
    }
    run("connect", event.submitter, async () => {
      token = $("token").value.trim();
      $("token").value = "";
      if (!token) throw new Error("请输入管理员令牌");
      try {
        const devices = await request("/devices");
        $("workspace").hidden = false;
        $("connection-panel").hidden = true;
        $("logout").hidden = false;
        $("connection-state").textContent = "ADMIN 已连接";
        $("connection-state").className = "chip good";
        notice("已连接当前服务。");
        renderDevices(devices);
        await Promise.all([loadHealth(), loadJobs(), loadSchedules()]);
      } catch (error) {
        if (!error.stale && $("workspace").hidden) token = "";
        throw error;
      }
    });
  });
  async function loadHealth() {
    await Promise.all(
      [
        ["health", "health-state", "正常"],
        ["ready", "ready-state", "已就绪"],
      ].map(async ([path, id, label]) => {
        try {
          await request(`/${path}`, { publicCall: true });
          $(id).textContent = label;
        } catch (error) {
          if (!error.stale)
            $(id).textContent = path === "ready" ? "未就绪" : "不可达";
        }
      }),
    );
  }
  function renderDevices(devices) {
    $("devices-list").replaceChildren();
    $("device-options").replaceChildren();
    $("device-count").textContent = String(devices.length);
    if (!devices.length) {
      empty(
        "devices-list",
        "还没有登记设备。请先确认代理配置中的设备与代理 UUID。",
      );
      return;
    }
    devices.forEach((device) => {
      const card = el("article", undefined, "card device-row");
      card.append(
        el("strong", "已登记 · 能力未知"),
        el("p", `设备 ${device.device_id}`, "uuid"),
        el("p", `代理 ${device.agent_id}`, "uuid"),
        el("small", "在线状态：API 未提供 · 登记不启动设备"),
      );
      $("devices-list").append(card);
      const option = el("option");
      option.value = device.device_id;
      $("device-options").append(option);
    });
  }
  async function loadDevices() {
    const load = ++devicesLoad;
    const devices = await request("/devices");
    if (load === devicesLoad) renderDevices(devices);
  }
  async function loadJobs(more = false) {
    const load = ++jobsLoad;
    if (!more) {
      nextCursor = null;
      empty("jobs-list", "正在加载任务…");
      $("load-more").hidden = true;
    }
    try {
      const result = await request(
        `/jobs?limit=25${more && nextCursor ? `&before=${encodeURIComponent(nextCursor)}` : ""}`,
      );
      if (load !== jobsLoad) return;
      if (!more) $("jobs-list").replaceChildren();
      result.items.forEach((job) => {
        const card = el("article", undefined, "card job-row"),
          head = el("div", undefined, "row-head"),
          info = el("div");
        info.append(stateChip(job), el("p", job.job_id, "uuid"));
        const button = el("button", "查看详情", "secondary");
        button.addEventListener("click", () =>
          run("detail", button, () => loadDetail(job.job_id)),
        );
        head.append(info, button);
        const meta = el("div", undefined, "row-meta");
        meta.append(
          el(
            "span",
            job.spec.mode === "simulation" ? "模拟任务" : "实机请求 · 未验收",
          ),
          el("span", `开始 ${stamp(job.spec.not_before)}`),
          el("span", `revision ${job.revision}`),
        );
        card.append(head, meta);
        $("jobs-list").append(card);
      });
      nextCursor = result.next_cursor;
      $("load-more").hidden = !nextCursor;
      if (!$("jobs-list").children.length)
        empty("jobs-list", "还没有任务。展开下方“创建任务”开始一次模拟验证。");
    } catch (error) {
      if (!error.stale && !more && load === jobsLoad)
        empty("jobs-list", "任务加载失败。请检查连接后点击“刷新列表”。");
      throw error;
    }
  }
  async function loadDetail(id) {
    renderDetail(await request(`/jobs/${checkUUID(id)}`));
  }
  function renderDetail(job) {
    selectedJob = job;
    const target = $("job-detail");
    target.replaceChildren();
    target.hidden = false;
    const header = el("div", undefined, "row-head");
    header.append(el("h3", "任务详情"), stateChip(job));
    target.append(header, el("p", job.job_id, "uuid"));
    const grid = el("dl", undefined, "detail-grid");
    for (const [label, value] of [
      [
        "模式",
        job.spec.mode === "simulation"
          ? "模拟（不产生学校有效记录）"
          : "实机请求（当前候选未支持）",
      ],
      ["当前版本", job.revision],
      [
        "期望状态",
        job.desired_state === "cancel" ? "取消 · 需核对停止确认" : "运行",
      ],
      [
        "开始 / 截止",
        `${stamp(job.spec.not_before)} / ${stamp(job.spec.deadline)}`,
      ],
      ["设备", job.spec.device_id],
      ["代理", job.agent_id || "尚未分配"],
      ["原因代码", job.reason_code || "无"],
      ["恢复阶段", job.resume_phase || "无"],
      ["恢复授权", job.recovery_action || "无"],
    ])
      grid.append(el("dt", label), el("dd", String(value)));
    target.append(grid);
    if (
      job.state === "cancelling" ||
      (job.state === "needs_attention" && job.desired_state === "cancel")
    )
      target.append(
        el(
          "p",
          "取消意图已提交，但设备是否停止仍需代理确认。请勿创建另一任务绕过占用。",
          "warning",
        ),
      );
    if (job.state === "succeeded")
      target.append(
        el(
          "p",
          "这是代理上报的记录核验状态；不代表控制台独立证明学校后台认可。",
          "hint",
        ),
      );
    const actions = el("div", undefined, "actions");
    const refresh = el("button", "刷新详情", "secondary");
    refresh.addEventListener("click", () =>
      run("detail", refresh, () => loadDetail(job.job_id)),
    );
    actions.append(refresh);
    if (!terminal.has(job.state) && job.desired_state !== "cancel") {
      const cancel = el("button", "取消任务", "danger");
      cancel.id = "cancel-job";
      cancel.addEventListener("click", () =>
        run("job-command", cancel, async (epoch) => {
          if (
            !(await confirm(
              "确认取消任务？",
              `任务 ${job.job_id}\n当前 revision：${job.revision}\n执行中的任务需等待代理停止确认，不会立即显示“已停止”。取消接口不提供原子版本校验。`,
            ))
          )
            return;
          if (epoch !== generation) return;
          const fresh = await request(`/jobs/${job.job_id}`);
          if (fresh.revision !== job.revision) {
            renderDetail(fresh);
            throw new Error("任务状态已变化，详情已刷新。请重新确认取消。");
          }
          renderDetail(
            await request(`/jobs/${job.job_id}/cancel`, { method: "POST" }),
          );
          notice("已提交取消意图，请以最新状态和停止确认为准。");
        }),
      );
      actions.append(cancel);
    }
    if (job.state === "needs_attention") {
      const label = el("label", "恢复动作");
      const select = el("select");
      select.id = "recovery-action";
      const choices =
        job.desired_state === "cancel"
          ? [["stop_only", "仅停止"]]
          : [
              ["verify_only", "仅核验（不重跑、不重传）"],
              ["stop_only", "仅停止"],
              ...(["leased", "preflight", "ready"].includes(job.resume_phase)
                ? [["retry_preflight", "重新预检（服务器仍校验未开始）"]]
                : []),
            ];
      choices.forEach(([value, text]) => {
        const option = el("option", text);
        option.value = value;
        select.append(option);
      });
      label.append(select);
      target.append(label);
      const resume = el("button", "授权恢复");
      resume.id = "resume-job";
      resume.addEventListener("click", () =>
        run("job-command", resume, async (epoch) => {
          const action = select.value;
          if (
            !(await confirm(
              "确认授权恢复？",
              `任务 ${job.job_id}\n操作：${select.selectedOptions[0].textContent}\nexpected_revision：${job.revision}\n仅向原代理授权本次恢复；响应不确定时先刷新，不会自动重复授权。`,
            ))
          )
            return;
          if (epoch !== generation) return;
          renderDetail(
            await request(`/jobs/${job.job_id}/resume`, {
              method: "POST",
              body: { expected_revision: job.revision, action },
            }),
          );
          notice("恢复授权已保存，等待符合条件的原代理领取。");
        }),
      );
      actions.append(resume);
    }
    target.append(actions);
    const raw = el("details"),
      summary = el("summary", "查看协议数据");
    raw.append(summary, el("pre", JSON.stringify(job, null, 2)));
    target.append(raw);
    target.focus({ preventScroll: true });
  }
  function validateSpec(spec) {
    const keys = [
      "protocol_version",
      "mode",
      "profile_id",
      "profile_revision",
      "route_id",
      "route_revision",
      "device_id",
      "not_before",
      "deadline",
      "expected_app_version",
    ];
    if (
      !spec ||
      Array.isArray(spec) ||
      typeof spec !== "object" ||
      Object.keys(spec).length !== keys.length ||
      keys.some((key) => !Object.hasOwn(spec, key))
    )
      throw new Error(
        "文件必须是完整 JobSpec，不能包含未知字段或 JobView 外层",
      );
    if (
      spec.protocol_version !== 1 ||
      !["simulation", "device"].includes(spec.mode)
    )
      throw new Error("仅支持 protocol_version 1 与 simulation / device 模式");
    ["profile_id", "route_id", "device_id"].forEach((key) =>
      checkUUID(spec[key]),
    );
    ["profile_revision", "route_revision"].forEach((key) => {
      if (typeof spec[key] !== "string" || !digestPattern.test(spec[key]))
        throw new Error(
          "revision 必须使用原配置的 64 位小写 SHA-256，不能随意生成",
        );
    });
    for (const key of ["not_before", "deadline"])
      if (
        typeof spec[key] !== "string" ||
        !/^\d{4}-\d\d-\d\dT\d\d:\d\d:\d\d(?:\.\d{1,6})?Z$/.test(spec[key]) ||
        Number.isNaN(Date.parse(spec[key])) ||
        new Date(spec[key]).toISOString().slice(0, 19) !==
          spec[key].slice(0, 19)
      )
        throw new Error("导入时间须为以 Z 结尾的 UTC 时间");
    if (Date.parse(spec.deadline) <= Date.parse(spec.not_before))
      throw new Error("截止时间必须晚于最早开始时间");
    if (
      spec.mode === "simulation"
        ? spec.expected_app_version !== null
        : typeof spec.expected_app_version !== "string" ||
          !spec.expected_app_version.trim()
    )
      throw new Error(
        "模拟模式应用版本必须为 null，实机请求必须提供已确认的应用版本",
      );
    return spec;
  }
  function validateJobView(job) {
    try {
      if (!job || typeof job !== "object" || Array.isArray(job))
        throw new Error();
      checkUUID(job.job_id);
      validateSpec(job.spec);
      if (
        ![
          "queued",
          "leased",
          "preflight",
          "ready",
          "running",
          "finishing",
          "verifying",
          "cancelling",
          "needs_attention",
          "completed",
          "succeeded",
          "failed",
          "cancelled",
        ].includes(job.state)
      )
        throw new Error();
      if (
        ![job.revision, job.fence].every(
          (value) => Number.isSafeInteger(value) && value >= 0,
        )
      )
        throw new Error();
      if (!["run", "cancel"].includes(job.desired_state)) throw new Error();
      for (const key of ["agent_id", "run_session_id"]) {
        if (!Object.hasOwn(job, key)) throw new Error();
        if (job[key] !== null) checkUUID(job[key]);
      }
      if (
        job.reason_code !== null &&
        (typeof job.reason_code !== "string" || !job.reason_code)
      )
        throw new Error();
      if (
        ![
          null,
          "leased",
          "preflight",
          "ready",
          "running",
          "finishing",
          "verifying",
          "cancelling",
        ].includes(job.resume_phase)
      )
        throw new Error();
      if (
        ![null, "retry_preflight", "verify_only", "stop_only"].includes(
          job.recovery_action,
        )
      )
        throw new Error();
      return job;
    } catch {
      throw new Error(
        "服务成功响应格式无效，创建结果尚未确认。请保留原请求重试或核对任务列表。",
      );
    }
  }
  function formSpec() {
    const data = Object.fromEntries(new FormData($("job-form")));
    return validateSpec({
      protocol_version: 1,
      mode: data.mode,
      profile_id: data.profile_id.trim(),
      profile_revision: data.profile_revision.trim(),
      route_id: data.route_id.trim(),
      route_revision: data.route_revision.trim(),
      device_id: data.device_id.trim(),
      not_before: utcDate(data.not_before),
      deadline: utcDate(data.deadline),
      expected_app_version:
        data.mode === "simulation" ? null : data.expected_app_version.trim(),
    });
  }
  function updateMode() {
    const physical = $("job-mode").value === "device";
    $("app-version-label").hidden = !physical;
    $("device-warning").hidden = !physical;
    $("job-form").elements.expected_app_version.required = physical;
    $("create-job").textContent = creation?.uncertain
      ? "用同一请求重试"
      : physical
        ? "创建实机请求（不支持执行）"
        : "创建模拟任务";
  }
  $("job-mode").addEventListener("change", updateMode);
  $("import-job").addEventListener("change", (event) =>
    run("import", null, async (epoch) => {
      if (creation) {
        event.target.value = "";
        throw new Error("先处理当前未确认的创建，不能更换请求内容");
      }
      const file = event.target.files[0];
      if (!file) return;
      if (file.size > 65536) throw new Error("JobSpec 文件请小于 64 KiB");
      const text = await file.text();
      if (epoch !== generation) return;
      let spec;
      try {
        spec = JSON.parse(text);
      } catch {
        throw new Error("无法解析 JSON，请选择完整的 JobSpec 文件");
      }
      validateSpec(spec);
      const begin = localDate(spec.not_before);
      const deadline = localDate(spec.deadline);
      for (const key of [
        "mode",
        "profile_id",
        "profile_revision",
        "route_id",
        "route_revision",
        "device_id",
      ])
        $("job-form").elements[key].value = spec[key];
      $("job-form").elements.not_before.value = begin;
      $("job-form").elements.deadline.value = deadline;
      $("job-form").elements.expected_app_version.value =
        spec.expected_app_version || "";
      updateMode();
      notice(
        "已在本地解析 JobSpec。请核对时间与配置引用；代理需要相同版本的配置文件。",
      );
    }),
  );
  $("job-form").addEventListener("submit", (event) => {
    event.preventDefault();
    run("creation", event.submitter, async (epoch) => {
      if (!creation) {
        const body = formSpec();
        if (
          body.mode === "device" &&
          !(await confirm(
            "保存实机请求？",
            "当前候选不支持真实乐跑执行，创建成功不代表设备可用或学校记录有效。确定仍保存这个协议请求？",
          ))
        )
          return;
        if (epoch !== generation) return;
        creation = { body, key: crypto.randomUUID(), uncertain: false };
      }
      $("job-fields").disabled = true;
      $("import-job").disabled = true;
      try {
        const job = await request("/jobs", {
          method: "POST",
          body: creation.body,
          key: creation.key,
        });
        validateJobView(job);
        creation = null;
        $("job-fields").disabled = false;
        $("import-job").disabled = false;
        $("reset-creation").hidden = true;
        updateMode();
        $("creation-state").textContent =
          "任务已创建。若需另建任务，请确认不会重复执行。";
        renderDetail(job);
        notice(`任务已创建：${job.job_id}`);
        await loadJobs();
      } catch (error) {
        if (error.stale) throw error;
        if (
          creation &&
          !creation.uncertain &&
          [403, 422].includes(error.status)
        ) {
          creation = null;
          $("job-fields").disabled = false;
          $("import-job").disabled = false;
          $("reset-creation").hidden = true;
          $("creation-state").textContent =
            "请求已被拒绝，未创建任务。请修改输入或核对管理员权限后重新提交。";
          updateMode();
        } else if (creation) {
          creation.uncertain = true;
          $("reset-creation").hidden = false;
          $("creation-state").textContent =
            "创建结果未确认：已锁定原请求和幂等键。重试使用完全相同的内容，不会静默另建任务。刷新页面或退出将丢失此内存记录，请先核对任务列表。";
          updateMode();
        }
        throw error;
      }
    });
  });
  $("reset-creation").addEventListener("click", () =>
    run("creation", $("reset-creation"), async (epoch) => {
      if (
        !(await confirm(
          "放弃当前创建重试？",
          "原请求可能已成功。请先刷新任务列表并核对，避免重复任务。放弃后再提交会生成新幂等键；确定已经核对并要重新编辑？",
        ))
      )
        return;
      if (epoch !== generation) return;
      creation = null;
      $("job-fields").disabled = false;
      $("import-job").disabled = false;
      $("reset-creation").hidden = true;
      $("creation-state").textContent =
        "已放弃原请求。重新提交前请确认没有重复任务。";
      updateMode();
    }),
  );
  $("device-form").addEventListener("submit", (event) => {
    event.preventDefault();
    run("register", event.submitter, async (epoch) => {
      const data = Object.fromEntries(new FormData(event.target));
      const body = {
        device_id: checkUUID(data.device_id.trim()),
        agent_id: checkUUID(data.agent_id.trim()),
      };
      if (
        !(await confirm(
          "确认设备归属？",
          `设备 ${body.device_id}\n代理 ${body.agent_id}\n当前协议不支持转移归属。登记不会启动设备或证明其能力。`,
        ))
      )
        return;
      if (epoch !== generation) return;
      await request("/devices", { method: "POST", body });
      notice("设备归属已登记。仍需代理报告并验证能力。");
      event.target.reset();
      await loadDevices();
    });
  });
  async function loadSchedules() {
    const load = ++schedulesLoad;
    const schedules = await request("/schedules");
    if (load !== schedulesLoad) return;
    $("schedules-list").replaceChildren();
    if (!schedules.length) {
      empty(
        "schedules-list",
        "暂无日程。此版本可查看和启停已有 ScheduleSpec；创建与修改模板请使用协议 API。",
      );
      return;
    }
    const days = ["", "一", "二", "三", "四", "五", "六", "日"];
    schedules.forEach((schedule) => {
      const card = el("article", undefined, "card schedule-row"),
        header = el("div", undefined, "row-head");
      header.append(
        el(
          "strong",
          `${schedule.local_time} · 每周${schedule.weekdays.map((day) => days[day]).join("、")}`,
        ),
        el(
          "span",
          schedule.enabled ? "已启用" : "已暂停",
          `chip ${schedule.enabled ? "good" : ""}`,
        ),
      );
      card.append(
        header,
        el("p", schedule.schedule_id, "uuid"),
        el(
          "p",
          `${schedule.timezone} · ${schedule.job_template.mode === "simulation" ? "模拟任务" : "实机请求 · 未支持"} · 窗口 ${(Date.parse(schedule.job_template.deadline) - Date.parse(schedule.job_template.not_before)) / 60000} 分钟`,
          "hint",
        ),
      );
      const button = el(
        "button",
        schedule.enabled ? "暂停日程" : "启用日程",
        "secondary",
      );
      button.addEventListener("click", () =>
        run(`schedule-${schedule.schedule_id}`, button, async (epoch) => {
          if (
            !(await confirm(
              schedule.enabled ? "暂停此日程？" : "启用此日程？",
              `日程 ${schedule.schedule_id}\n仅影响未来尚未生成的任务；不会取消已有任务。${!schedule.enabled && schedule.job_template.mode === "device" ? "\n此实机模板当前不支持真实执行。" : ""}\n当前协议无日程版本锁，操作前将重新检查模板。`,
            ))
          )
            return;
          if (epoch !== generation) return;
          const fresh = (await request("/schedules")).find(
            (item) => item.schedule_id === schedule.schedule_id,
          );
          if (!fresh || JSON.stringify(fresh) !== JSON.stringify(schedule)) {
            await loadSchedules();
            throw new Error("日程已变化，请刷新后重新确认");
          }
          await request(`/schedules/${schedule.schedule_id}`, {
            method: "PUT",
            body: { ...fresh, enabled: !fresh.enabled },
          });
          await loadSchedules();
          notice("日程状态已更新；已有任务不受影响。");
        }),
      );
      card.append(button);
      const details = el("details");
      details.append(
        el("summary", "查看完整 ScheduleSpec"),
        el("pre", JSON.stringify(schedule, null, 2)),
      );
      card.append(details);
      $("schedules-list").append(card);
    });
  }
  $("job-lookup").addEventListener("submit", (event) => {
    event.preventDefault();
    run("detail", event.submitter, () =>
      loadDetail($("lookup-id").value.trim()),
    );
  });
  for (const [id, action] of [
    ["refresh-jobs", () => loadJobs()],
    ["load-more", () => loadJobs(true)],
    ["refresh-devices", loadDevices],
    ["refresh-schedules", loadSchedules],
    [
      "refresh-all",
      () =>
        Promise.all([loadHealth(), loadDevices(), loadJobs(), loadSchedules()]),
    ],
  ])
    $(id).addEventListener("click", () => run(id, $(id), action));
  window.addEventListener("offline", () =>
    notice(
      "浏览器处于离线状态。已提交操作的结果可能尚未确认，请勿重复创建。",
      true,
    ),
  );
  window.addEventListener("beforeunload", (event) => {
    if (creation) {
      event.preventDefault();
      event.returnValue = "";
    }
  });
  window.addEventListener("pagehide", () => clearSession());
})();
