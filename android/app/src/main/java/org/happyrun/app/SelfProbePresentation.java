package org.happyrun.app;

/** Evidence wording only. A local hook receipt grants no execution capabilities. */
public final class SelfProbePresentation {
    private SelfProbePresentation() { }

    public static String describe(boolean active, Integer bridgeApiVersion) {
        String evidence = active && bridgeApiVersion != null && bridgeApiVersion > 0
                ? "已收到本应用 hook 回执\nXposed bridge/API " + bridgeApiVersion
                : "inactive · 未收到本应用 hook 回执";
        return evidence + "\n此检查只涉及 org.happyrun.app，不识别框架发行版，也不代表真实执行能力。"
                + "\n可选模块需由你自行在框架管理器中启用，并将 scope 限于本应用；普通版本或未启用时保持 inactive。"
                + "\n应用不会自动申请 Root、安装模块或更改系统设置。";
    }
}
