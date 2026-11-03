package org.happyrun.app.observation;

import java.io.File;
import java.io.IOException;
import java.nio.ByteBuffer;
import java.nio.channels.FileChannel;
import java.nio.charset.StandardCharsets;
import java.nio.file.Files;
import java.nio.file.LinkOption;
import java.nio.file.Path;
import java.nio.file.StandardCopyOption;
import java.nio.file.StandardOpenOption;
import java.util.function.LongSupplier;

/** Single bounded private snapshot, flushed before an atomic same-directory rename. */
final class ContinuousLocationFile {
    private final Path output,temporary;
    final File stop;
    ContinuousLocationFile(File ownDirectory,String nonce) throws IOException {
        if(nonce==null || !nonce.matches("[a-f0-9]{32}"))throw new IOException("request_invalid");
        output=ownDirectory.toPath().resolve("continuous-"+nonce+".json");
        temporary=ownDirectory.toPath().resolve("continuous-"+nonce+".tmp");
        stop=new File(ownDirectory,"continuous-"+nonce+".stop");
        if(Files.exists(output,LinkOption.NOFOLLOW_LINKS)
                || Files.exists(temporary,LinkOption.NOFOLLOW_LINKS)
                || Files.exists(stop.toPath(),LinkOption.NOFOLLOW_LINKS))throw new IOException("nonce_reused");
    }
    synchronized void write(ContinuousLocationReport report,LongSupplier clock) throws IOException {
        // Encode after acquiring this lock: a heartbeat cannot overwrite a newer callback snapshot.
        String json=report.encode(clock.getAsLong());
        byte[] bytes=json.getBytes(StandardCharsets.UTF_8);
        if(bytes.length>4096)throw new IOException("report_too_large");
        boolean created=false;
        try {
            try(FileChannel stream=FileChannel.open(temporary,StandardOpenOption.CREATE_NEW,
                    StandardOpenOption.WRITE,LinkOption.NOFOLLOW_LINKS)) {
                created=true;
                ByteBuffer buffer=ByteBuffer.wrap(bytes);
                while(buffer.hasRemaining())stream.write(buffer);
                stream.force(true);
            }
            Files.move(temporary,output,StandardCopyOption.ATOMIC_MOVE,StandardCopyOption.REPLACE_EXISTING);
        } finally {
            if(created)Files.deleteIfExists(temporary);
        }
    }
}
