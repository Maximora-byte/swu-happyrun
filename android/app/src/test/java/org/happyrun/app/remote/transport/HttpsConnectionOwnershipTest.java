package org.happyrun.app.remote.transport;

import java.io.OutputStream;
import java.net.URL;
import java.nio.charset.StandardCharsets;
import java.util.concurrent.atomic.AtomicInteger;
import org.happyrun.app.remote.protocol.ProtocolCodec;
import org.happyrun.app.remote.protocol.ProtocolCodecTest;
import org.happyrun.app.remote.protocol.StrictJson;
import org.junit.Test;
import static org.junit.Assert.*;

/** Request ownership contract, not an emulation of Android's connection pool. */
public class HttpsConnectionOwnershipTest {
    private static final String ID = "00000000-0000-0000-0000-000000000001";
    private static final class OwnedConnection extends HttpsAgentClientTest.Connection {
        int observations;
        OwnedConnection() throws Exception { super(new URL("https://example.test")); }
        private void requireOwned() {
            assertEquals("close", getRequestProperty("Connection"));
            assertFalse(getInstanceFollowRedirects());
            assertTrue(getConnectTimeout() > 0 && getConnectTimeout() <= 5000);
            assertTrue(getReadTimeout() > 0 && getReadTimeout() <= 5000);
            observations++;
        }
        @Override public OutputStream getOutputStream() { requireOwned();return super.getOutputStream(); }
        @Override public int getResponseCode() { requireOwned();return super.getResponseCode(); }
    }
    @Test public void emptyClaimIsOwnedBeforeAnyIoAndCloseStaysFinal() throws Exception {
        OwnedConnection connection = new OwnedConnection();AtomicInteger opens = new AtomicInteger();
        HttpsAgentClient client = new HttpsAgentClient("https://example.test", "synthetic",
                u -> { opens.incrementAndGet();return connection; });
        assertNull(client.claim(ID));assertTrue(connection.observations >= 2);
        assertTrue(connection.disconnected);client.close();
        try { client.claim(ID);fail(); } catch(ControlException expected) {
            assertEquals("closed", expected.getMessage());
        }
        assertEquals(1, opens.get());
    }
    @Test public void getResponseIsOwnedBeforeAnyIo() throws Exception {
        OwnedConnection connection = new OwnedConnection();connection.status = 200;
        connection.body = StrictJson.write(ProtocolCodec.job(ProtocolCodecTest.job()))
                .getBytes(StandardCharsets.UTF_8);
        try(HttpsAgentClient client = new HttpsAgentClient("https://example.test", "synthetic",
                u -> connection)) {
            assertEquals(ID, client.getJob(ID).jobId);
            assertEquals(1, connection.observations);assertTrue(connection.disconnected);
        }
    }
    @Test public void rejectedResponsesKeepOwnershipAndNeverRetry() throws Exception {
        for(int status : new int[]{307, 401, 409, 503}) {
            OwnedConnection connection = new OwnedConnection();connection.status = status;
            AtomicInteger opens = new AtomicInteger();
            try(HttpsAgentClient client = new HttpsAgentClient("https://example.test", "synthetic",
                    u -> { opens.incrementAndGet();return connection; })) {
                try { client.claim(ID);fail(); } catch(ControlException expected) {
                    assertEquals(status, expected.httpStatus);
                }
                assertEquals(1, opens.get());assertTrue(connection.disconnected);
            }
        }
    }
}
