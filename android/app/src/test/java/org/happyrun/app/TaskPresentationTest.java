package org.happyrun.app;

public final class TaskPresentationTest {
    private static void equal(Object expected, Object actual) {
        if (!expected.equals(actual)) throw new AssertionError(expected + " != " + actual);
    }
    public static void main(String[] args) {
        equal("模拟完成", TaskPresentation.stateLabel("completed"));
        equal("正在模拟", TaskPresentation.stateLabel("running"));
        equal("等待执行", TaskPresentation.stateLabel("ready"));
        equal("已观察", TaskPresentation.checkLabel("observed"));
        equal("当前不可用", TaskPresentation.checkLabel("unavailable"));
        equal("需要关注", TaskPresentation.stateLabel("needs_attention"));
        equal("已停止", TaskPresentation.stateLabel("cancelled"));
        equal("状态未知", TaskPresentation.stateLabel("succeeded"));
        equal(50, TaskPresentation.progress(10, 20));
        equal(100, TaskPresentation.progress(25, 20));
        equal(0, TaskPresentation.progress(Double.NaN, 20));
        equal(0, TaskPresentation.progress(1, 0));
        equal(0, TaskPresentation.progress(-5, 20));
        if (!TaskPresentation.resultMessage("completed").contains("不代表学校有效记录")) throw new AssertionError();
        if (!TaskPresentation.resultMessage("needs_attention").contains("不会自动重跑")) throw new AssertionError();
        equal("尚未验证", TaskPresentation.checkLabel("invented"));
        equal("曾中断，已确认停止本地模拟", TaskPresentation.reasonLabel("local_simulation_stopped_after_attention"));
        equal(false, TaskPresentation.actionsAllowed("storage_write_failed_not_persisted", true));
        equal(false, TaskPresentation.actionsAllowed("ok", false));
        equal(false, TaskPresentation.actionsAllowed("unknown", true));
        equal(true, TaskPresentation.actionsAllowed("ok", true));
        if (!TaskPresentation.healthMessage("storage_write_failed_not_persisted").contains("未保存到数据库")) throw new AssertionError();
        if (!TaskPresentation.snapshotLabel("needs_attention", false).contains("未保存")) throw new AssertionError();
        equal("模拟完成", TaskPresentation.snapshotLabel("completed", true));
        System.out.println("PASS: native UI state, progress and evidence wording");
    }
}
