package org.happyrun.app;

/** Evidence-based next steps. No wizard outcome enables real execution. */
public final class WizardPresentation {
    private WizardPresentation() { }

    public static boolean active(String status, Integer api) {
        return "active".equals(status) && api != null && api > 0;
    }

    public static String framework(String status, Integer api, boolean moduleIncluded) {
        String evidence;
        if (active(status, api)) {
            evidence = "active · 已收到本应用 hook 回执\nXposed bridge/API " + api;
        } else if ("inactive".equals(status)) {
            evidence = "inactive · 未观察到本应用 hook 回执";
        } else {
            evidence = "unknown · 本次检查无法确认模块状态，请重新检查";
        }
        return evidence + "\n" + (moduleIncluded ? "此版本包含可选的本应用诊断模块。"
                : "此版本不含可选模块；本地模拟无需模块。")
                + "\n框架具体发行版无法确认。Root 或模块检查通过，不代表真实执行能力；真实执行尚未实现。";
    }

    public static String nextLabel(String status, Integer api, boolean moduleIncluded) {
        if (active(status, api)) return "查看真实运行缺项";
        return moduleIncluded ? "查看启用步骤" : "了解可选模块";
    }

    public static String instructions(boolean moduleIncluded) {
        if (!moduleIncluded) {
            return "此版本不含可选模块入口，无需在管理器中反复查找。你可以直接体验本地模拟。"
                    + "\n需要本应用 hook 诊断时，请使用项目交付的可选模块版本，再由你自行在已有框架管理器中启用。"
                    + "\n本应用不会自动安装框架、发起 Root 授权或修改设置。";
        }
        return "1. 自行打开你已安装并信任的框架管理器。\n"
                + "2. 找到 HappyRun 可选诊断模块并启用，作用域仅选择 HappyRun（org.happyrun.app）。\n"
                + "3. 按管理器提示重新打开本应用，然后点击“我已设置，重新验证”。\n\n"
                + "没有回执可能是未启用、尚未生效、框架不兼容或检查失败；不能据此断言作用域选错。"
                + "\n无需选择学校应用。验证只证明本应用收到回执，不开放真实运行。";
    }

    public static String root(String status) {
        String message;
        switch (status == null ? "" : status) {
            case "not_checked": message = "尚未主动检查 Root；路径迹象不是授权证据。"; break;
            case "checking": message = "正在等待只读 Root 检查；约 30 秒后尝试结束，可取消。请在管理器中自行决定是否授权。"; break;
            case "uid_zero_observed": message = "本次只读命令观察到 uid=0；不代表真实执行或其他设备能力已验证。"; break;
            case "su_not_found": message = "未找到可调用的 su；无法确认设备是否已 Root。"; break;
            case "nonzero_exit": message = "未获 Root 结果，可能是拒绝授权或 su 错误。"; break;
            case "non_root_uid": message = "命令未返回 Root 身份，不能确认授权成功。"; break;
            case "timeout": message = "检查超时，已停止本次诊断，不会自动重试。"; break;
            case "cancelled":
            case "interrupted": message = "本次检查已取消；不撤销管理器中已作出的授权决定。"; break;
            default: message = "本次检查无法确认 Root 状态；未把错误视为授权成功。";
        }
        return message + "\n无论是否授权，均可继续本地模拟。";
    }
}
