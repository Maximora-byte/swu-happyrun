package org.happyrun.app.observation;

import java.io.File;
import java.io.IOException;
import java.io.OutputStream;
import java.nio.charset.StandardCharsets;
import java.nio.file.Files;
import java.nio.file.LinkOption;
import java.nio.file.Path;
import java.nio.file.StandardOpenOption;

/** CREATE_NEW rejects stale files and symlinks; only the own app's private directory is used. */
public final class ObservationPrivateFile {
    private ObservationPrivateFile() {}
    public static void write(File ownFilesDir, String nonce, String report) throws IOException {
        if(nonce==null || !nonce.matches("[a-f0-9]{32}"))throw new IOException("private_request_invalid");
        byte[] bytes=report.getBytes(StandardCharsets.UTF_8);
        if(bytes.length>65536)throw new IOException("private_result_too_large");
        Path output=ownFilesDir.toPath().resolve("owned-observation-"+nonce+".json");
        try(OutputStream stream=Files.newOutputStream(output,StandardOpenOption.WRITE,
                StandardOpenOption.CREATE_NEW,LinkOption.NOFOLLOW_LINKS)) {
            stream.write(bytes);
        }
    }
}
