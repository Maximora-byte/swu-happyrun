package org.happyrun.app;

public final class SelfProbePresentationTest {
    public static void main(String[] args) {
        check(SelfProbePresentation.describe(false, null).contains("inactive"));
        check(!SelfProbePresentation.describe(false, 82).contains("API 82"));
        check(SelfProbePresentation.describe(true, 82).contains("已收到本应用 hook 回执"));
        check(SelfProbePresentation.describe(true, 82).contains("Xposed bridge/API 82"));
        check(SelfProbePresentation.describe(true, null).contains("inactive"));
        check(SelfProbePresentation.describe(true, 0).contains("inactive"));
        check(SelfProbePresentation.describe(true, 82).contains("不代表真实执行能力"));
        check(SelfProbePresentation.describe(false, null).contains("自行"));
        System.out.println("PASS: self-scope evidence presentation");
    }

    private static void check(boolean value) {
        if (!value) throw new AssertionError("self-scope evidence wording");
    }
}
