package org.happyrun.app.rootprobe;

import java.io.ByteArrayOutputStream;
import java.io.File;
import java.io.IOException;
import java.io.InputStream;
import java.nio.charset.StandardCharsets;
import java.util.function.BooleanSupplier;
import java.util.function.LongSupplier;

/** Explicit user-triggered read-only check. Call only from a background executor. */
public final class RootDiagnostic {
    private static final int OUTPUT_LIMIT=4096;
    private static final long TIMEOUT_NANOS=30_000_000_000L;
    private RootDiagnostic() {}
    interface Factory {Process start(String[] command)throws IOException;}
    interface Sleeper {void sleep(long ms)throws InterruptedException;}

    public static RootReport run(BooleanSupplier cancelled) {
        if(Thread.currentThread().isInterrupted())return new RootReport("interrupted");
        if(cancelled.getAsBoolean())return new RootReport("cancelled");
        String executable;
        try {executable=findSu();}catch(RuntimeException unavailable){return new RootReport("launch_failed");}
        if(executable==null)return new RootReport("su_not_found");
        return run(command->new ProcessBuilder(executable,"-c","id").redirectErrorStream(true).start(),
            cancelled,System::nanoTime,Thread::sleep);
    }
    private static String findSu() {
        // Read-only lookup. Absence here does not prove the device is unrooted.
        String path=System.getenv("PATH");
        String candidates=(path==null?"":path)+":/system/bin:/system/xbin:/sbin:/su/bin:/debug_ramdisk";
        for(String dir:candidates.split(":")) {
            if(!dir.startsWith("/"))continue;
            File binary=new File(dir,"su");
            if(binary.isFile() && binary.canExecute())return binary.getAbsolutePath();
        }
        return null;
    }
    static RootReport run(Factory factory,BooleanSupplier cancel,LongSupplier clock,Sleeper sleeper) {
        if(Thread.currentThread().isInterrupted())return new RootReport("interrupted");
        if(cancel.getAsBoolean())return new RootReport("cancelled");
        long started=clock.getAsLong();Process child=null;
        try {
            try {child=factory.start(new String[]{"su","-c","id"});}
            catch(IOException failed) {return new RootReport("launch_failed");}
            child.getOutputStream().close();
            InputStream input=child.getInputStream();
            ByteArrayOutputStream captured=new ByteArrayOutputStream();
            byte[] buffer=new byte[1024];
            while(true) {
                if(cancel.getAsBoolean())return new RootReport("cancelled");
                if(Thread.currentThread().isInterrupted())return new RootReport("interrupted");
                if(clock.getAsLong()-started>=TIMEOUT_NANOS)return new RootReport("timeout");
                // Never await EOF: a descendant can keep the output pipe open.
                int available=input.available();
                if(available>0) {
                    int count=input.read(buffer,0,Math.min(buffer.length,available));
                    if(count>0) {
                        if(captured.size()+count>OUTPUT_LIMIT)return new RootReport("output_limit");
                        captured.write(buffer,0,count);
                    }
                    continue;
                }
                if(!child.isAlive()) {
                    if(input.available()>0)continue;
                    if(child.exitValue()!=0)return new RootReport("nonzero_exit");
                    String output=new String(captured.toByteArray(),StandardCharsets.UTF_8).trim();
                    if(output.matches("uid=0(?:\\(root\\))?(?:[ \\t]+[^\\r\\n]*)?"))return new RootReport("uid_zero_observed");
                    if(output.matches("uid=[0-9]+(?:\\([^\\r\\n)]*\\))?(?:[ \\t]+[^\\r\\n]*)?"))return new RootReport("non_root_uid");
                    return new RootReport("invalid_response");
                }
                sleeper.sleep(20);
            }
        } catch(InterruptedException interrupted) {
            Thread.currentThread().interrupt();return new RootReport("interrupted");
        } catch(IOException | RuntimeException failed) {
            return new RootReport("io_error");
        } finally {
            if(child!=null) {
                // No waitFor without a deadline and no surviving worker/read threads.
                try {child.destroy();if(child.isAlive())child.destroyForcibly();}catch(RuntimeException ignored){}
                try {child.getInputStream().close();}catch(IOException | RuntimeException ignored){}
                try {child.getErrorStream().close();}catch(IOException | RuntimeException ignored){}
                try {child.getOutputStream().close();}catch(IOException | RuntimeException ignored){}
            }
        }
    }
}
