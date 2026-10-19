package org.happyrun.app;

public final class WizardPresentationTest {
    public static void main(String[] args) {
        contains(WizardPresentation.framework("unknown", null, true), "unknown");
        contains(WizardPresentation.framework("inactive", null, true), "inactive");
        contains(WizardPresentation.framework("active", 82, true), "Xposed bridge/API 82");
        contains(WizardPresentation.framework("active", null, true), "unknown");
        contains(WizardPresentation.framework("active", 82, false), "不含可选模块");
        contains(WizardPresentation.framework("active", 82, true), "真实执行尚未实现");
        contains(WizardPresentation.instructions(false), "此版本不含");
        contains(WizardPresentation.instructions(true), "仅选择 HappyRun");
        contains(WizardPresentation.instructions(true), "可能");
        contains(WizardPresentation.root("not_checked"), "尚未主动检查");
        contains(WizardPresentation.root("uid_zero_observed"), "不代表真实执行");
        contains(WizardPresentation.root("nonzero_exit"), "本地模拟");
        contains(WizardPresentation.root("timeout"), "超时");
        contains(WizardPresentation.root("invented"), "无法确认");
        if (!"查看真实运行缺项".equals(WizardPresentation.nextLabel("active", 82, true))) throw new AssertionError();
        if (!"查看启用步骤".equals(WizardPresentation.nextLabel("inactive", null, true))) throw new AssertionError();
        if (!"了解可选模块".equals(WizardPresentation.nextLabel("inactive", null, false))) throw new AssertionError();
        for (String failure : new String[] {"su_not_found", "launch_failed", "nonzero_exit",
                "non_root_uid", "invalid_response", "output_limit", "timeout", "cancelled",
                "interrupted", "io_error", null}) {
            contains(WizardPresentation.root(failure), "本地模拟");
            if (WizardPresentation.root(failure).contains("观察到 uid=0")) throw new AssertionError();
        }
        contains(WizardPresentation.root("checking"), "约 30 秒后尝试结束，可取消");
        contains(WizardPresentation.instructions(false), "不会自动安装框架、发起 Root 授权或修改设置");
        if (WizardPresentation.root("nonzero_exit").contains("已拒绝")) throw new AssertionError();
        System.out.println("PASS: novice wizard evidence and next steps");
    }
    private static void contains(String value, String expected) {
        if (!value.contains(expected)) throw new AssertionError(expected + " missing in " + value);
    }
}
