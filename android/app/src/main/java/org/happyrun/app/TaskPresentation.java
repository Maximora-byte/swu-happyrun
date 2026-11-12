package org.happyrun.app;

/** Display-only copy. Execution decisions remain in the persistent runtime. */
public final class TaskPresentation {
    private TaskPresentation() {}

    public static boolean actionsAllowed(String health, boolean persisted) {
        return "ok".equals(health) && persisted;
    }

    public static String healthMessage(String health) {
        if ("ok".equals(health)) return "";
        if ("storage_write_failed_not_persisted".equals(health)) {
            return "存储失败，执行已停止；当前提示未保存到数据库。原数据库记录可能仍显示运行状态。请修复存储后重启，开始与停止操作已锁定。";
        }
        return "运行器健康状态尚未确认。开始与停止操作已锁定，请重新检查。";
    }

    public static String snapshotLabel(String state, boolean persisted) {
        return stateLabel(state) + (persisted ? "" : "（未保存）");
    }

    public static String stateLabel(String state) {
        if ("running".equals(state)) return "正在模拟";
        if ("ready".equals(state)) return "等待执行";
        if ("completed".equals(state)) return "模拟完成";
        if ("cancelled".equals(state)) return "已停止";
        if ("needs_attention".equals(state)) return "需要关注";
        return "状态未知";
    }

    public static int progress(double distanceM, double totalDistanceM) {
        if (!Double.isFinite(distanceM) || !Double.isFinite(totalDistanceM)
                || totalDistanceM <= 0 || distanceM < 0) return 0;
        return (int) Math.min(100, Math.floor(distanceM / totalDistanceM * 100));
    }

    public static String resultMessage(String state) {
        if ("completed".equals(state)) {
            return "本地模拟已完成；不代表学校有效记录，也不证明其他应用支持。";
        }
        if ("cancelled".equals(state)) return "当前模拟已停止，不计为完成。";
        if ("needs_attention".equals(state)) {
            return "任务需要关注。可能发生进程中断；不会自动重跑。请先停止并确认当前本地模拟，再显式创建新模拟。";
        }
        if ("running".equals(state)) {
            return "正在执行应用内合成路线。建议保持应用在前台；系统终止进程后不会自动重跑。";
        }
        return "状态尚未确认，请重新检查。不会据此显示执行成功。";
    }

    public static String reasonLabel(String reason) {
        if ("storage_write_failed_not_persisted".equals(reason)) return "存储写入失败，安全停机提示未保存";
        if ("local_simulation_stopped_after_attention".equals(reason)) return "曾中断，已确认停止本地模拟";
        if ("local_simulation_stopped".equals(reason)) return "已确认停止本地模拟";
        if ("restart_uncertain".equals(reason)) return "上次进程中断，结果未确认";
        if ("runtime_stopped".equals(reason)) return "运行器已停止，需人工确认";
        if ("local_runtime_error".equals(reason)) return "本地运行异常，需人工确认";
        if ("simulation_only".equals(reason)) return "仅本地模拟";
        return reason == null || reason.isEmpty() ? "无" : reason;
    }

    public static String checkLabel(String status) {
        if ("observed".equals(status)) return "已观察";
        if ("unavailable".equals(status)) return "当前不可用";
        if ("unsupported".equals(status)) return "尚未支持";
        if ("missing".equals(status)) return "缺少条件";
        if ("detected".equals(status)) return "发现迹象";
        if ("blocked".equals(status)) return "条件未满足";
        return "尚未验证";
    }
}
