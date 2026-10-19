package org.happyrun.app;

import android.app.Activity;
import android.app.AlertDialog;
import android.content.res.ColorStateList;
import android.graphics.Color;
import android.graphics.Typeface;
import android.graphics.drawable.GradientDrawable;
import android.graphics.drawable.StateListDrawable;
import android.os.Build;
import android.os.Bundle;
import android.os.Handler;
import android.os.Looper;
import android.view.View;
import android.widget.Button;
import android.widget.LinearLayout;
import android.widget.ProgressBar;
import android.widget.ScrollView;
import android.widget.TextView;

import org.happyrun.app.diagnostics.CheckItem;
import org.happyrun.app.runtime.LocalRuntime;
import org.happyrun.app.runtime.TaskSnapshot;

import java.text.SimpleDateFormat;
import java.util.Date;
import java.util.List;
import java.util.Locale;
import java.util.concurrent.ExecutorService;
import java.util.concurrent.Executors;

/** Native Android UI. It observes the runtime; it never invents execution progress. */
public final class MainActivity extends Activity {
    private static final int INK = Color.rgb(20, 43, 67);
    private static final int MUTED = Color.rgb(96, 116, 137);
    private static final int ACCENT = Color.rgb(8, 126, 139);
    private static final int BACKGROUND = Color.rgb(243, 246, 250);
    private final Handler main = new Handler(Looper.getMainLooper());
    private final ExecutorService io = Executors.newSingleThreadExecutor();
    private LocalRuntime runtime;
    private TaskSnapshot task;
    private ScrollView scroll;
    private LinearLayout content;
    private LinearLayout checks;
    private TextView state;
    private TextView summary;
    private TextView taskId;
    private TextView notice;
    private TextView metrics;
    private ProgressBar progress;
    private Button start;
    private Button stop;
    private Button refresh;
    private Button history;
    private boolean historyLoading;
    private boolean foreground;
    private boolean destroyed;
    private boolean reading;
    private boolean pending;
    private boolean uncertain = true;
    private String runtimeHealth = "unknown";
    private String healthTaskId;
    private long serial;
    private AlertDialog confirmation;
    private AlertDialog auxiliaryDialog;

    private final Runnable poll = new Runnable() {
        @Override public void run() {
            if (!foreground || destroyed) return;
            readState(false);
            main.postDelayed(this, 500);
        }
    };

    @Override protected void onCreate(Bundle savedInstanceState) {
        super.onCreate(savedInstanceState);
        buildScreen();
    }

    @Override protected void onStart() {
        super.onStart();
        foreground = true;
        readState(true);
        main.postDelayed(poll, 500);
    }

    @Override protected void onStop() {
        foreground = false;
        main.removeCallbacks(poll);
        super.onStop();
    }

    @Override protected void onDestroy() {
        destroyed = true;
        serial++;
        main.removeCallbacks(poll);
        if (confirmation != null) confirmation.dismiss();
        if (auxiliaryDialog != null) auxiliaryDialog.dismiss();
        io.shutdown();
        // Runtime is process-scoped: rotating the screen must not stop or restart a task.
        super.onDestroy();
    }

    private void buildScreen() {
        scroll = new ScrollView(this);
        scroll.setId(R.id.app_scroll);
        scroll.setFillViewport(true);
        scroll.setBackgroundColor(BACKGROUND);
        scroll.setOnApplyWindowInsetsListener((view, insets) -> {
            view.setPadding(insets.getSystemWindowInsetLeft(), insets.getSystemWindowInsetTop(),
                    insets.getSystemWindowInsetRight(), insets.getSystemWindowInsetBottom());
            return insets;
        });
        content = vertical();
        content.setPadding(dp(20), dp(20), dp(20), dp(28));
        scroll.addView(content, new ScrollView.LayoutParams(-1, -2));
        setContentView(scroll);

        TextView brand = text(getString(R.string.app_name), 25, INK, true);
        content.addView(brand);
        content.addView(text(getString(R.string.app_subtitle), 13, MUTED, false));
        TextView badge = text(getString(R.string.simulation_badge), 13, ACCENT, true);
        badge.setPadding(dp(12), dp(8), dp(12), dp(8));
        badge.setBackground(background(Color.rgb(227, 243, 243), 10, false));
        addSpace(content, 14);
        content.addView(badge);
        addSpace(content, 20);
        content.addView(heading(getString(R.string.home_title), 28));
        content.addView(text(getString(R.string.home_intro), 15, MUTED, false));

        notice = text("", 14, Color.rgb(134, 76, 28), false);
        notice.setId(R.id.operation_notice);
        notice.setPadding(dp(12), dp(12), dp(12), dp(12));
        notice.setBackground(background(Color.rgb(255, 242, 223), 10, false));
        notice.setAccessibilityLiveRegion(View.ACCESSIBILITY_LIVE_REGION_POLITE);
        notice.setVisibility(View.GONE);
        content.addView(notice);

        LinearLayout simulation = card(R.string.simulation_title);
        simulation.addView(text(getString(R.string.simulation_intro), 15, MUTED, false));
        start = button(R.string.start_simulation, R.id.start_simulation, true);
        start.setEnabled(false);
        start.setOnClickListener(view -> askStart());
        simulation.addView(start, buttonParams());

        LinearLayout taskCard = card(R.string.task_title);
        state = text(getString(R.string.no_task), 21, INK, true);
        state.setId(R.id.task_state);
        state.setFocusableInTouchMode(true);
        state.setAccessibilityLiveRegion(View.ACCESSIBILITY_LIVE_REGION_POLITE);
        taskCard.addView(state);
        progress = new ProgressBar(this, null, android.R.attr.progressBarStyleHorizontal);
        progress.setId(R.id.task_progress);
        progress.setMax(100);
        progress.setProgressTintList(ColorStateList.valueOf(ACCENT));
        LinearLayout.LayoutParams bar = new LinearLayout.LayoutParams(-1, dp(10));
        bar.setMargins(0, dp(16), 0, dp(10));
        taskCard.addView(progress, bar);
        metrics = text("", 14, INK, true);
        taskCard.addView(metrics);
        summary = text(getString(R.string.no_task_hint), 15, MUTED, false);
        summary.setId(R.id.task_summary);
        taskCard.addView(summary);
        taskId = text("", 12, MUTED, false);
        taskId.setId(R.id.task_id);
        taskId.setTextIsSelectable(true);
        taskCard.addView(taskId);
        stop = button(R.string.stop_simulation, R.id.stop_simulation, false);
        stop.setEnabled(false);
        stop.setOnClickListener(view -> askStop());
        taskCard.addView(stop, buttonParams());
        history = button(R.string.task_history, R.id.task_history, false);
        history.setEnabled(false);
        history.setOnClickListener(view -> showHistory());
        taskCard.addView(history, buttonParams());

        LinearLayout environment = card(R.string.diagnostics_title);
        environment.addView(text(getString(R.string.diagnostics_hint), 14, MUTED, false));
        checks = vertical();
        checks.setId(R.id.capability_list);
        checks.addView(text(getString(R.string.checking), 14, MUTED, false));
        environment.addView(checks);
        refresh = button(R.string.refresh_checks, R.id.refresh_checks, false);
        refresh.setOnClickListener(view -> readState(true));
        environment.addView(refresh, buttonParams());

        LinearLayout requirements = card(R.string.requirements_title);
        requirements.addView(text(getString(R.string.requirements_intro), 15, MUTED, false));
        for (String item : new String[] {
                "学校配置：本人确认的校区边界、规则与路线尚未接入。",
                "应用适配：当前乐跑版本的页面操作与记录核验尚未实现。",
                "设备通道：位置、传感器与停止能力需分别验证。",
                "最终验收：需要真实设备观察和学校有效记录证据。"}) {
            addSpace(requirements, 10);
            requirements.addView(text("• " + item, 14, INK, false));
        }
        addSpace(requirements, 14);
        requirements.addView(text(getString(R.string.root_note), 14, MUTED, false));
        Button blocked = button(R.string.real_execution_unavailable, R.id.actual_run_blocked, false);
        blocked.setEnabled(false);
        requirements.addView(blocked, buttonParams());
        addSpace(content, 24);
        content.addView(text(getString(R.string.footer_note), 12, MUTED, false));
    }

    private void readState(boolean includeChecks) {
        if (destroyed || pending || reading) return;
        reading = true;
        final long request = ++serial;
        refresh.setEnabled(false);
        io.execute(() -> {
            TaskSnapshot snapshot = null;
            List<CheckItem> observations = null;
            boolean failed = false;
            String health = "unknown";
            String failedTask = null;
            try {
                if (runtime == null) runtime = LocalRuntime.get(getApplicationContext());
                synchronized (runtime) {
                    health = runtime.health();
                    failedTask = runtime.healthTaskId();
                    snapshot = runtime.currentTask();
                }
                if (includeChecks) observations = runtime.diagnostics();
            } catch (RuntimeException error) {
                failed = true;
            }
            final TaskSnapshot result = snapshot;
            final List<CheckItem> resultChecks = observations;
            final String resultHealth = health;
            final String resultHealthTaskId = failedTask;
            final boolean unavailable = failed;
            main.post(() -> {
                reading = false;
                if (destroyed || request != serial) return;
                refresh.setEnabled(true);
                runtimeHealth = resultHealth;
                healthTaskId = resultHealthTaskId;
                if (unavailable) {
                    uncertain = true;
                    showNotice(R.string.read_failed);
                } else {
                    uncertain = false;
                    render(result);
                    if (resultChecks != null) renderChecks(resultChecks);
                    if (includeChecks) notice.setVisibility(View.GONE);
                }
                showHealthNotice();
                updateButtons();
            });
        });
    }

    private void askStart() {
        if (pending || uncertain || !healthAllowsActions() || runtime == null || hasUnresolvedTask() || confirmation != null) return;
        confirmation = new AlertDialog.Builder(this)
                .setTitle(R.string.start_title)
                .setMessage(R.string.start_message)
                .setNegativeButton(R.string.not_now, null)
                .setPositiveButton(R.string.start_confirm, (dialog, which) -> execute(null))
                .create();
        confirmation.setOnDismissListener(dialog -> confirmation = null);
        confirmation.show();
    }

    private void askStop() {
        if (pending || uncertain || !healthAllowsActions() || !hasUnresolvedTask() || confirmation != null) return;
        final String id = task.id;
        confirmation = new AlertDialog.Builder(this)
                .setTitle(R.string.stop_title)
                .setMessage(R.string.stop_message)
                .setNegativeButton(R.string.continue_task, null)
                .setPositiveButton(R.string.stop_confirm, (dialog, which) -> execute(id))
                .create();
        confirmation.setOnDismissListener(dialog -> confirmation = null);
        confirmation.show();
    }

    private void execute(String stopId) {
        if (pending || uncertain || !healthAllowsActions() || runtime == null) return;
        if (stopId == null && hasUnresolvedTask()) return;
        if (stopId != null && (task == null || !stopId.equals(task.id))) return;
        pending = true;
        final long request = ++serial;
        updateButtons();
        refresh.setEnabled(false);
        showNotice(R.string.operation_pending);
        io.execute(() -> {
            TaskSnapshot snapshot = null;
            boolean failed = false;
            String health = "unknown";
            String failedTask = null;
            synchronized (runtime) {
                try {
                    snapshot = stopId == null ? runtime.startSimulation() : runtime.stop(stopId);
                } catch (RuntimeException error) {
                    failed = true;
                }
                health = runtime.health();
                failedTask = runtime.healthTaskId();
                if (!"ok".equals(health)) {
                    try { snapshot = runtime.currentTask(); } catch (RuntimeException ignored) { }
                }
            }
            final TaskSnapshot result = snapshot;
            final String resultHealth = health;
            final String resultHealthTaskId = failedTask;
            final boolean unavailable = failed;
            main.post(() -> {
                if (destroyed || request != serial) return;
                pending = false;
                refresh.setEnabled(true);
                runtimeHealth = resultHealth;
                healthTaskId = resultHealthTaskId;
                if (!"ok".equals(runtimeHealth)) render(result);
                if (unavailable) {
                    uncertain = true;
                    showNotice(R.string.operation_failed);
                } else {
                    uncertain = false;
                    notice.setVisibility(View.GONE);
                    render(result);
                    state.requestFocus();
                    scroll.post(() -> {
                        if (!destroyed) scroll.scrollTo(0, state.getParent() instanceof View
                                ? ((View) state.getParent()).getTop() : 0);
                    });
                }
                showHealthNotice();
                updateButtons();
                if (unavailable) readState(false);
            });
        });
    }

    private void render(TaskSnapshot snapshot) {
        task = snapshot;
        if (snapshot == null) {
            state.setText("ok".equals(runtimeHealth) ? getString(R.string.no_task) : "本次任务未保存");
            summary.setText("ok".equals(runtimeHealth) ? getString(R.string.no_task_hint) : TaskPresentation.healthMessage(runtimeHealth));
            taskId.setText("");
            metrics.setText("");
            progress.setProgress(0, false);
            progress.setContentDescription(getString(R.string.no_task));
            return;
        }
        state.setText(TaskPresentation.snapshotLabel(snapshot.state, snapshot.persisted));
        String resultText = snapshot.persisted ? TaskPresentation.resultMessage(snapshot.state)
                : "未保存的安全停机状态；原数据库记录可能仍显示运行。请修复存储后重启。";
        if (!"ok".equals(runtimeHealth) && snapshot.persisted && !snapshot.id.equals(healthTaskId)) {
            resultText += "\n这是此前已保存的任务，不是本次失败的完成结果。";
        }
        summary.setText(resultText);
        int percent = TaskPresentation.progress(snapshot.distanceM, snapshot.totalDistanceM);
        progress.setProgress(percent, false);
        progress.setContentDescription((snapshot.persisted ? "引擎记录进度 " : "最后可读进度 ") + percent + "% 的合成路线");
        metrics.setText(String.format(Locale.CHINA, "%.1f / %.1f 米 · 本地合成路线",
                snapshot.distanceM, snapshot.totalDistanceM));
        String updated = new SimpleDateFormat("MM-dd HH:mm:ss", Locale.CHINA)
                .format(new Date(snapshot.updatedAtMs));
        taskId.setText("任务 " + snapshot.id + "\n更新于 " + updated + "（设备时间）"
                + (snapshot.reason == null || snapshot.reason.isEmpty() ? "" : "\n原因：" + TaskPresentation.reasonLabel(snapshot.reason)));
    }

    private void renderChecks(List<CheckItem> observations) {
        checks.removeAllViews();
        if (observations.isEmpty()) {
            checks.addView(text("暂无可核实的能力检查结果。", 14, MUTED, false));
            return;
        }
        for (CheckItem item : observations) {
            addSpace(checks, 16);
            checks.addView(text(item.name + " · " + TaskPresentation.checkLabel(item.status), 15, INK, true));
            checks.addView(text(item.detail, 13, MUTED, false));
        }
    }

    private boolean hasUnresolvedTask() {
        return task != null && ("running".equals(task.state)
                || "ready".equals(task.state) || "needs_attention".equals(task.state));
    }

    private void updateButtons() {
        start.setEnabled(!pending && !uncertain && healthAllowsActions() && runtime != null && !hasUnresolvedTask());
        stop.setEnabled(!pending && !uncertain && healthAllowsActions() && hasUnresolvedTask());
        history.setEnabled(runtime != null && !historyLoading && !pending);
    }

    private void showHistory() {
        if (runtime == null || historyLoading || pending || confirmation != null) return;
        historyLoading = true;
        updateButtons();
        io.execute(() -> {
            List<TaskSnapshot> entries = null;
            try { entries = runtime.history(); } catch (RuntimeException ignored) { }
            final List<TaskSnapshot> result = entries;
            main.post(() -> {
                historyLoading = false;
                if (destroyed) return;
                updateButtons();
                if (result == null) { showNotice(R.string.read_failed); return; }
                if (!foreground) return;
                if (result.isEmpty()) {
                    showAuxiliary(new AlertDialog.Builder(this).setTitle(R.string.history_title)
                            .setMessage(R.string.history_empty).setPositiveButton("关闭", null));
                    return;
                }
                String[] labels = new String[result.size()];
                for (int i = 0; i < result.size(); i++) {
                    TaskSnapshot item = result.get(i);
                    labels[i] = TaskPresentation.snapshotLabel(item.state, item.persisted) + " · "
                            + new SimpleDateFormat("MM-dd HH:mm:ss", Locale.CHINA).format(new Date(item.startedAtMs))
                            + "\n" + item.id;
                }
                showAuxiliary(new AlertDialog.Builder(this).setTitle(R.string.history_title)
                        .setItems(labels, (dialog, which) -> showHistoryDetail(result.get(which).id))
                        .setNegativeButton("关闭", null));
            });
        });
    }

    private void showHistoryDetail(String id) {
        if (runtime == null || destroyed) return;
        io.execute(() -> {
            TaskSnapshot saved = null;
            try { saved = runtime.getTask(id); } catch (RuntimeException ignored) { }
            final TaskSnapshot result = saved;
            main.post(() -> {
                if (destroyed || !foreground) return;
                if (result == null) { showNotice(R.string.read_failed); return; }
                String details = "任务 " + result.id + "\n\n"
                        + TaskPresentation.snapshotLabel(result.state, result.persisted) + "\n"
                        + String.format(Locale.CHINA, "%.1f / %.1f 米", result.distanceM, result.totalDistanceM)
                        + "\n" + (result.persisted ? TaskPresentation.resultMessage(result.state)
                                : "安全停机提示未保存到数据库；原记录可能仍显示运行，不能视作已完成或已持久化。")
                        + (result.reason == null ? "" : "\n原因：" + TaskPresentation.reasonLabel(result.reason))
                        + "\n\n" + getString(R.string.history_note);
                showAuxiliary(new AlertDialog.Builder(this).setTitle("本地任务记录")
                        .setMessage(details).setPositiveButton("关闭", null));
            });
        });
    }

    private boolean healthAllowsActions() {
        return TaskPresentation.actionsAllowed(runtimeHealth, task == null || task.persisted);
    }

    private void showHealthNotice() {
        if (!"ok".equals(runtimeHealth)) {
            notice.setText(TaskPresentation.healthMessage(runtimeHealth));
            notice.setVisibility(View.VISIBLE);
        } else if (task != null && !task.persisted) {
            notice.setText("当前任务状态未保存到数据库，开始与停止操作已锁定。请修复存储后重启。");
            notice.setVisibility(View.VISIBLE);
        }
    }

    private void showAuxiliary(AlertDialog.Builder builder) {
        if (auxiliaryDialog != null) auxiliaryDialog.dismiss();
        auxiliaryDialog = builder.create();
        auxiliaryDialog.setOnDismissListener(dialog -> auxiliaryDialog = null);
        auxiliaryDialog.show();
    }

    private void showNotice(int textId) {
        notice.setText(textId);
        notice.setVisibility(View.VISIBLE);
        if ("storage_write_failed_not_persisted".equals(runtimeHealth)) showHealthNotice();
    }

    private LinearLayout vertical() {
        LinearLayout layout = new LinearLayout(this);
        layout.setOrientation(LinearLayout.VERTICAL);
        return layout;
    }

    private LinearLayout card(int titleId) {
        LinearLayout card = vertical();
        card.setPadding(dp(18), dp(18), dp(18), dp(18));
        card.setBackground(background(Color.WHITE, 16, true));
        LinearLayout.LayoutParams params = new LinearLayout.LayoutParams(-1, -2);
        params.topMargin = dp(18);
        content.addView(card, params);
        card.addView(heading(getString(titleId), 19));
        addSpace(card, 8);
        return card;
    }

    private TextView heading(String value, int size) {
        TextView view = text(value, size, INK, true);
        if (Build.VERSION.SDK_INT >= 28) view.setAccessibilityHeading(true);
        return view;
    }

    private TextView text(String value, int size, int color, boolean bold) {
        TextView view = new TextView(this);
        view.setText(value);
        view.setTextSize(size);
        view.setTextColor(color);
        view.setLineSpacing(dp(3), 1.05f);
        view.setIncludeFontPadding(true);
        if (bold) view.setTypeface(Typeface.DEFAULT, Typeface.BOLD);
        view.setLayoutParams(new LinearLayout.LayoutParams(-1, -2));
        return view;
    }

    private Button button(int labelId, int id, boolean primary) {
        Button button = new Button(this);
        button.setId(id);
        button.setText(labelId);
        button.setTextSize(15);
        button.setAllCaps(false);
        button.setMinHeight(dp(48));
        button.setMinimumHeight(dp(48));
        button.setPadding(dp(14), dp(10), dp(14), dp(10));
        StateListDrawable backgrounds = new StateListDrawable();
        backgrounds.addState(new int[] {-android.R.attr.state_enabled},
                background(Color.rgb(226, 232, 238), 10, false));
        backgrounds.addState(new int[] {}, background(primary ? ACCENT : Color.rgb(235, 242, 246), 10, false));
        button.setBackground(backgrounds);
        button.setTextColor(new ColorStateList(new int[][] {new int[] {-android.R.attr.state_enabled}, new int[] {}},
                new int[] {MUTED, primary ? Color.WHITE : INK}));
        return button;
    }

    private LinearLayout.LayoutParams buttonParams() {
        LinearLayout.LayoutParams params = new LinearLayout.LayoutParams(-1, -2);
        params.topMargin = dp(14);
        return params;
    }

    private GradientDrawable background(int color, int radius, boolean border) {
        GradientDrawable drawable = new GradientDrawable();
        drawable.setColor(color);
        drawable.setCornerRadius(dp(radius));
        if (border) drawable.setStroke(dp(1), Color.rgb(220, 229, 237));
        return drawable;
    }

    private void addSpace(LinearLayout parent, int height) {
        parent.addView(new View(this), new LinearLayout.LayoutParams(1, dp(height)));
    }

    private int dp(int value) {
        return Math.round(value * getResources().getDisplayMetrics().density);
    }
}
