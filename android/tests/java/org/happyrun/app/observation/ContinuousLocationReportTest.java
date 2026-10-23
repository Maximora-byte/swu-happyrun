package org.happyrun.app.observation;

/** Desktop contract checks without Android/JUnit runtime dependencies. */
public final class ContinuousLocationReportTest {
    private static final String NONCE="0123456789abcdef0123456789abcdef";
    private static int checks;
    public static void main(String[] args) throws Exception {
        check(ContinuousLocationReport.duration(NONCE,"5000")==5000,"minimum duration");
        check(ContinuousLocationReport.duration(NONCE,"1800000")==1800000,"maximum duration");
        for(String duration:new String[]{null,"4999","1800001","5.0","+5000"," 5000","999999999999999999999"})
            check(ContinuousLocationReport.duration(NONCE,duration)==-1,"reject invalid duration");
        check(ContinuousLocationReport.duration("../bad","5000")==-1,"nonce traversal rejected");
        check(ContinuousLocationReport.duration(NONCE.toUpperCase(),"5000")==-1,"uppercase rejected");
        ContinuousLocationReport report=new ContinuousLocationReport(NONCE,"01234567-89ab-cdef-0123-456789abcdef",100);
        check(report.encode(100).contains("\"sample\":null"),"no cached sample");
        report.observing();
        check(report.encode(101).contains("\"state\":\"observing\""),"ready without sample");
        check(!report.offer(1,2,3,99,101),"pre-window sample rejected");
        check(!report.offer(1,2,3,102,101),"future sample rejected");
        check(!report.offer(Double.NaN,2,3,101,101),"nonfinite rejected");
        check(!report.offer(91,2,3,101,101),"latitude rejected");
        check(!report.offer(1,181,3,101,101),"longitude rejected");
        check(!report.offer(1,2,-1,101,101),"accuracy rejected");
        check(report.offer(1,2,3,101,102),"fresh sample accepted");
        check(!report.offer(4,5,6,101,103),"duplicate rejected");
        check(!report.offer(4,5,6,100,103),"stale rejected");
        check(report.offer(4,5,6,103,104),"new sample accepted");
        String json=report.encode(104);
        check(json.contains("\"sequence\":2")&&json.contains("\"latitude\":4.0"),"latest sample and sequence");
        check(!json.contains("\"latitude\":1.0"),"history not retained");
        report.finish(true);
        check(report.encode(105).contains("\"state\":\"stopped\""),"confirmed cleanup stopped");
        check(!report.offer(1,2,3,106,106),"closed report rejects samples");
        ContinuousLocationReport failed=new ContinuousLocationReport(NONCE,"boot",100);
        failed.observing();failed.finish(false);
        check(failed.encode(105).contains("\"error_code\":\"cleanup_unconfirmed\""),"cleanup failure is error");
        failed.error("permission_required");failed.finish(true);
        check(failed.encode(106).contains("\"state\":\"error\""),"cleanup preserves prior failure");
        check(new ContinuousLocationReport(NONCE,"boot",100).encode(101).equals(
                "{\"schema\":1,\"nonce\":\""+NONCE+"\",\"boot_id\":\"boot\",\"sequence\":0,"
                +"\"state\":\"starting\",\"error_code\":null,\"window_start_ns\":100,"
                +"\"reported_at_ns\":101,\"sample\":null}"),"exact initial envelope");
        java.nio.file.Path directory=java.nio.file.Files.createTempDirectory("continuous-contract-");
        try {
            ContinuousLocationFile file=new ContinuousLocationFile(directory.toFile(),NONCE);
            file.write(report,()->105L);
            java.nio.file.Path output=directory.resolve("continuous-"+NONCE+".json");
            check(java.nio.file.Files.readString(output).equals(report.encode(105)),"atomic initial report");
            file.write(failed,()->106L);
            check(java.nio.file.Files.readString(output).equals(failed.encode(106)),"atomic replacement report");
            check(!java.nio.file.Files.exists(directory.resolve("continuous-"+NONCE+".tmp")),"temporary removed");
            boolean rejected=false;
            try { new ContinuousLocationFile(directory.toFile(),NONCE); }
            catch(java.io.IOException expected) { rejected=true; }
            check(rejected,"reuse cannot overwrite previous report");
            // A pre-existing temp file is never truncated or deleted.
            java.nio.file.Path temporary=directory.resolve("continuous-"+NONCE+".tmp");
            java.nio.file.Files.writeString(temporary,"private sentinel");
            rejected=false;
            try { file.write(report,()->107L); }
            catch(java.io.IOException expected) { rejected=true; }
            check(rejected && java.nio.file.Files.readString(temporary).equals("private sentinel"),"existing temp protected");
            java.nio.file.Files.delete(temporary);java.nio.file.Files.delete(output);
        } finally { java.nio.file.Files.delete(directory); }
        System.out.println("ContinuousLocationReportTest: "+checks+" contract checks passed");
    }
    private static void check(boolean condition,String message) {
        if(!condition)throw new AssertionError(message);
        checks++;
    }
}
