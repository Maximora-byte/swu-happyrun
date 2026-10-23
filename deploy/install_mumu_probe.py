"""Install the shipped SELF_PROBE APK pair on an explicitly selected local MuMu instance."""

import argparse
import re
from pathlib import Path

PACKAGE = "org.happyrun.app"
PERMISSIONS = (
    "android.permission.ACCESS_COARSE_LOCATION",
    "android.permission.ACCESS_FINE_LOCATION",
)
MESSAGES = {
    "instance_index_invalid": "实例编号须为 1–8 位 ASCII 数字。",
    "probe_apk_missing": "探针文件缺失或为链接，请使用校验通过的完整交付文件夹。",
    "mumu_not_found": "未发现 MuMu 安装。请先安装并启动本轮支持的 MuMu 6.8.4.0。",
    "installation_selection_required": "发现多个 MuMu 安装，无法安全确定本次安装对象。",
    "transport_version_unverified": "本轮仅支持 MuMu 6.8.4.0 与 Android 15 / API 35。",
    "instance_not_ready": "所选实例尚未完全运行，请在 MuMu 中确认启动完成。",
    "android_boot_not_ready": "Android 尚未启动完成。请等待启动完成后由本人重新运行安装入口。",
    "binding_changed": "实例身份或启动状态发生变化，安装已停止。",
    "probe_install_failed": (
        "APK 安装未确认成功。可能存在签名不匹配；请保留现有应用和数据并人工检查。"
    ),
    "permission_grant_failed": "自身应用的位置权限授予未确认成功，已停止后续操作。",
    "permission_readback_failed": "自身应用的位置权限读回未确认，已停止。",
    "own_activity_start_failed": "探针已安装，但自身应用的前台页面未确认打开。请人工检查。",
    "command_failed": "设备命令未确认成功，已停止。",
    "command_timeout": "设备命令超时，结果未确认；请保留现场，不要自动重试。",
    "installation_interrupted": "安装已中断，可能存在未确认操作；请保留现场并人工检查。",
    "installation_unconfirmed": "安装结果未确认，已停止。请保留现场并人工检查。",
}


class InstallError(Exception):
    def __init__(self, code):
        self.code = code
        super().__init__(code)


def instance_index(value):
    if not isinstance(value, str) or re.fullmatch(r"[0-9]{1,8}", value) is None:
        raise argparse.ArgumentTypeError(MESSAGES["instance_index_invalid"])
    return value


def install_probe(root, index, *, transport_factory=None, runner=None, open_app=False):
    """No retry or cleanup side effects; dependencies are injectable for fake-command tests."""
    try:
        instance_index(index)
    except argparse.ArgumentTypeError:
        raise InstallError("instance_index_invalid") from None
    apks = [Path(root) / "Android" / name for name in ("probe.apk", "probe-test.apk")]
    if any(path.is_symlink() or not path.is_file() for path in apks):
        raise InstallError("probe_apk_missing")
    if transport_factory is None:
        from swu_happyrun.desktop.mumu_transport import LocalMuMuTransport

        transport_factory = LocalMuMuTransport
    if runner is None:
        from swu_happyrun.drivers.command import _run_bounded_bytes

        runner = _run_bounded_bytes
    transport = transport_factory()
    if transport.host_version != "6.8.4.0":
        raise InstallError("transport_version_unverified")
    inventory = transport.inventory()
    selected = next((item for item in inventory if item.get("index") == index), None)
    if selected is None or selected.get("running") is not True:
        raise InstallError("instance_not_ready")
    transport.connect(index)
    if transport.android_api != 35:
        raise InstallError("transport_version_unverified")

    def adb(*args, timeout=10):
        transport.assert_current()
        return runner(transport.adb, "-s", transport.serial, *args, timeout=timeout)

    for apk in apks:
        out, err, code = adb("install", "-r", str(apk.absolute()), timeout=60)
        lines = out.replace(b"\r", b"").splitlines()
        if (
            code != 0
            or err.strip()
            or b"Success" not in [line.strip() for line in lines]
            or re.search(rb"failure|error|install_failed", out, re.IGNORECASE)
        ):
            raise InstallError("probe_install_failed")
    # No permission mutation is possible until BOTH APK installs have confirmed Success.
    for permission in PERMISSIONS:
        out, err, code = adb("shell", "pm", "grant", PACKAGE, permission)
        if code != 0 or out.strip() or err.strip():
            raise InstallError("permission_grant_failed")
    out, err, code = adb("shell", "dumpsys", "package", PACKAGE)
    if (
        code != 0
        or err.strip()
        or not all(
            re.search(re.escape(permission.encode()) + rb":[ \t]+granted=true\b", out)
            for permission in PERMISSIONS
        )
    ):
        raise InstallError("permission_readback_failed")
    if open_app:
        out, err, code = adb("shell", "am", "start", "-W", "-n", PACKAGE + "/.MainActivity")
        if code != 0 or err.strip() or b"Status: ok" not in out or b"Error" in out:
            raise InstallError("own_activity_start_failed")
    transport.assert_current()


def main(argv=None, *, transport_factory=None, runner=None, input_fn=input, output=print):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--index", type=instance_index, help="explicit running MuMu instance index")
    parser.add_argument("--open-app", action="store_true", help="open the own SELF_PROBE page")
    args = parser.parse_args(argv)
    try:
        index = args.index
        if index is None:
            try:
                index = instance_index(input_fn("请输入已启动的 MuMu 实例编号（如 5）："))
            except argparse.ArgumentTypeError:
                raise InstallError("instance_index_invalid") from None
        install_probe(
            Path(__file__).absolute().parent,
            index,
            transport_factory=transport_factory,
            runner=runner,
            open_app=args.open_app,
        )
    except (KeyboardInterrupt, EOFError):
        output(MESSAGES["installation_interrupted"] + "（installation_interrupted）")
        return 3
    except Exception as error:
        candidate = getattr(error, "code", "installation_unconfirmed")
        code = candidate if candidate in MESSAGES else "installation_unconfirmed"
        output(f"{MESSAGES[code]}（{code}）")
        return (
            2
            if code
            in {
                "instance_index_invalid",
                "probe_apk_missing",
                "mumu_not_found",
                "installation_selection_required",
                "transport_version_unverified",
                "instance_not_ready",
                "android_boot_not_ready",
            }
            else 3
        )
    output("SELF_PROBE 双 APK 安装与自身位置权限已确认。未写入 GPS，也未操作乐跑记录。")
    output("请让 HappyRun 自身页面保持前台；首次启动后 GPS 初始化可能需要约 35 秒。")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
