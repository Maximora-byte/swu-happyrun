package org.happyrun.app.remote.transport;

import org.junit.Test;
import static org.junit.Assert.*;
import javax.net.ssl.HttpsURLConnection;
import java.net.URL;
import java.io.*;
import java.security.cert.Certificate;
import java.util.concurrent.atomic.AtomicInteger;
import org.happyrun.app.remote.protocol.*;

public class HttpsAgentClientTest {
    static final String ID="00000000-0000-0000-0000-000000000001";
    static class Connection extends HttpsURLConnection {
        int status=204; byte[] body=new byte[0]; String type="application/json";
        ByteArrayOutputStream output=new ByteArrayOutputStream(); boolean disconnected;
        Connection(URL url){super(url);}
        public void connect(){} public void disconnect(){disconnected=true;} public boolean usingProxy(){return false;}
        public String getCipherSuite(){return "test";} public Certificate[] getLocalCertificates(){return null;} public Certificate[] getServerCertificates(){return null;}
        public int getResponseCode(){return status;} public String getContentType(){return type;}
        public InputStream getInputStream(){return new ByteArrayInputStream(body);} public OutputStream getOutputStream(){return output;}
    }
    @Test public void constructorDoesNoNetworkAndRejectsUnsafeOrigins() {
        AtomicInteger opens=new AtomicInteger();
        HttpsAgentClient client=new HttpsAgentClient("https://example.test/","synthetic",u->{opens.incrementAndGet();return new Connection(u);});
        assertEquals(0,opens.get());assertFalse(client.toString().contains("synthetic"));client.close();
        for(String origin:new String[]{"http://example.test","https://user@example.test","https://example.test/api","https://example.test?q=1","https://example.test#x","https://example.test:0"}) {
            try{HttpsAgentClient.validateBaseUrl(origin);fail(origin);}catch(IllegalArgumentException expected){}
        }
    }
    @Test public void claimUsesExactPathMemoryBearerAndNoRedirectOrRetry() throws Exception {
        Connection connection=new Connection(new URL("https://example.test"));AtomicInteger opens=new AtomicInteger();
        try(HttpsAgentClient client=new HttpsAgentClient("https://example.test","synthetic",u->{assertEquals("/api/v1/leases/claim",u.getPath());opens.incrementAndGet();return connection;})) {
            assertNull(client.claim(ID));assertEquals(1,opens.get());assertFalse(connection.getInstanceFollowRedirects());
            assertEquals("Bearer synthetic",connection.getRequestProperty("Authorization"));
            assertEquals("{\"device_id\":\""+ID+"\"}",connection.output.toString("UTF-8"));assertTrue(connection.disconnected);
        }
    }
    @Test public void redirectsAndFailuresStaySanitized() throws Exception {
        for(int status:new int[]{301,302,307,308,401,403,409,422,500,503}) {
            Connection connection=new Connection(new URL("https://example.test"));connection.status=status;
            AtomicInteger opens=new AtomicInteger();
            try(HttpsAgentClient client=new HttpsAgentClient("https://example.test","synthetic",u->{opens.incrementAndGet();return connection;})) {
                try{client.claim(ID);fail();}catch(ControlException expected){assertEquals(status,expected.httpStatus);assertFalse(expected.toString().contains("synthetic"));assertEquals(status>=500,expected.ambiguous);assertNull(expected.getCause());}
                assertEquals(1,opens.get());
            }
        }
    }
    @Test public void invalidResponsesCannotBecomeEmptyClaims() throws Exception {
        for(byte[] data:new byte[][]{"{}".getBytes("UTF-8"),"null".getBytes("UTF-8"),new byte[]{(byte)0xc3,0x28},new byte[262145]}) {
            Connection connection=new Connection(new URL("https://example.test"));connection.status=200;connection.body=data;
            try(HttpsAgentClient client=new HttpsAgentClient("https://example.test","synthetic",u->connection)) {
                try{client.claim(ID);fail();}catch(ControlException expected){assertTrue(expected.ambiguous);}
            }
        }
    }
    @Test public void closedAndInvalidIdentifiersPerformNoNetwork() {
        AtomicInteger opens=new AtomicInteger();HttpsAgentClient client=new HttpsAgentClient("https://example.test","synthetic",u->{opens.incrementAndGet();return new Connection(u);});
        try{client.claim("../secret");fail();}catch(IllegalArgumentException expected){}
        client.close();try{client.claim(ID);fail();}catch(ControlException expected){assertEquals("closed",expected.getMessage());}
        assertEquals(0,opens.get());
    }
    @Test public void totalDeadlineBoundsEvenUncooperativeOpen() {
        HttpsAgentClient client=new HttpsAgentClient("https://example.test","synthetic",u->{long end=System.nanoTime()+7000000000L;while(System.nanoTime()<end){try{Thread.sleep(50);}catch(InterruptedException ignored){}}return new Connection(u);});
        long start=System.nanoTime();try{client.claim(ID);fail();}catch(ControlException expected){assertEquals("request_timeout",expected.getMessage());assertTrue(expected.ambiguous);}
        assertTrue((System.nanoTime()-start)/1000000<5800);client.close();
    }
    @Test public void allFixedEndpointsUseStrictPayloads() throws Exception {
        Connection connection=new Connection(new URL("https://example.test"));
        java.util.List<String> paths=new java.util.ArrayList<>();
        try(HttpsAgentClient client=new HttpsAgentClient("https://example.test","synthetic",u->{paths.add(u.getPath());connection.output.reset();return connection;})) {
            connection.status=200;
            connection.body=("{\"agent_id\":\""+ID+"\",\"heartbeat_seconds\":10,\"lease_seconds\":30}").getBytes("UTF-8");
            AgentHello observation=new AgentHello(ID,ID,ID,java.time.Instant.parse("2026-10-19T00:00:00Z"));
            assertEquals(ID,client.hello(observation).agentId);
            assertTrue(connection.output.toString("UTF-8").contains("\"backend\":\"fake\""));
            assertTrue(connection.output.toString("UTF-8").contains("\"capabilities\":[]"));
            connection.body="{\"server_time\":\"2026-10-19T00:00:00Z\"}".getBytes("UTF-8");client.heartbeat(observation);
            connection.body=StrictJson.write(ProtocolCodec.job(ProtocolCodecTest.job())).getBytes("UTF-8");client.getJob(ID);
            LeaseCommand lease=new LeaseCommand("synthetic-lease",1);
            client.events(ID,lease,new JobEvent(ID,1,"completed",null,null));
            assertTrue(connection.output.toString("UTF-8").contains("\"evidence\":[]"));
            client.stopAck(ID,lease,ID,1);
            connection.body="{\"expires_at\":\"2026-10-19T00:00:30Z\",\"desired_state\":\"cancel\"}".getBytes("UTF-8");assertEquals("cancel",client.renew(ID,lease).desiredState);
            assertEquals(java.util.Arrays.asList("/api/v1/agents/hello","/api/v1/agents/heartbeat","/api/v1/jobs/"+ID,"/api/v1/jobs/"+ID+"/events","/api/v1/jobs/"+ID+"/stop-ack","/api/v1/jobs/"+ID+"/renew"),paths);
        }
    }
    @Test public void closeDropsTokenWithoutBlockingOnPlatformDisconnect() throws Exception {
        java.util.concurrent.CountDownLatch opened=new java.util.concurrent.CountDownLatch(1);
        java.util.concurrent.CountDownLatch release=new java.util.concurrent.CountDownLatch(1);
        Connection connection=new Connection(new URL("https://example.test")) {
            public int getResponseCode(){opened.countDown();try{release.await();}catch(InterruptedException ignored){}return 204;}
            public void disconnect(){try{release.await();}catch(InterruptedException ignored){}}
        };
        HttpsAgentClient client=new HttpsAgentClient("https://example.test","synthetic",u->connection);
        Thread caller=new Thread(()->{try{client.claim(ID);}catch(ControlException expected){}});caller.setDaemon(true);caller.start();
        assertTrue(opened.await(2,java.util.concurrent.TimeUnit.SECONDS));
        long start=System.nanoTime();client.close();assertTrue((System.nanoTime()-start)/1000000<500);
        java.lang.reflect.Field token=HttpsAgentClient.class.getDeclaredField("token");token.setAccessible(true);assertNull(token.get(client));
        release.countDown();caller.join(2000);assertFalse(caller.isAlive());
    }
}
