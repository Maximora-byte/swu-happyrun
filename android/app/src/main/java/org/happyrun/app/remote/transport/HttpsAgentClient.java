package org.happyrun.app.remote.transport;

import org.happyrun.app.remote.protocol.*;
import javax.net.ssl.HttpsURLConnection;
import java.net.URI;
import java.net.URL;
import java.io.InputStream;
import java.io.OutputStream;
import java.io.ByteArrayOutputStream;
import java.nio.ByteBuffer;
import java.nio.charset.StandardCharsets;
import java.nio.charset.CodingErrorAction;
import java.time.Instant;
import java.util.concurrent.*;
import java.util.concurrent.atomic.AtomicBoolean;

/** Explicit foreground-owned HTTPS client. Constructors do no I/O; no retries or redirects. */
public final class HttpsAgentClient implements AgentClient {
    private static final int BUDGET_MS=5000;
    private static final int MAX_BYTES=262144;
    interface ConnectionFactory { HttpsURLConnection open(URL url) throws Exception; }
    private final String origin;
    private volatile String token;
    private final ConnectionFactory factory;
    private final ExecutorService worker;
    private final AtomicBoolean busy=new AtomicBoolean();
    private volatile HttpsURLConnection active;
    private volatile boolean closed;
    public HttpsAgentClient(String baseUrl,String token) {
        this(baseUrl,token,url->(HttpsURLConnection)url.openConnection());
    }
    HttpsAgentClient(String baseUrl,String token,ConnectionFactory factory) {
        origin=validateBaseUrl(baseUrl);
        if(token==null || token.length()>4096 || !token.matches("[A-Za-z0-9._~+/-]+=*"))throw new IllegalArgumentException("invalid_memory_token");
        this.token=token;this.factory=factory;
        worker=Executors.newSingleThreadExecutor(r->{Thread t=new Thread(r,"happyrun-https");t.setDaemon(true);return t;});
    }
    public static String validateBaseUrl(String value) {
        try {
            URI uri=new URI(value);
            if(!"https".equals(uri.getScheme())||uri.getHost()==null||uri.getRawUserInfo()!=null||uri.getRawQuery()!=null||uri.getRawFragment()!=null
                ||(uri.getRawPath()!=null&&!uri.getRawPath().isEmpty()&&!"/".equals(uri.getRawPath()))||uri.getPort()==0||uri.getPort()>65535)throw new Exception();
            return "https://"+uri.getRawAuthority();
        }catch(Exception failure){throw new IllegalArgumentException("invalid_https_origin");}
    }
    private String request(String method,String path,Object payload,boolean noContentAllowed) {
        if(closed)throw failure("closed",0,false,false);
        if(!busy.compareAndSet(false,true))throw failure("busy",0,false,false);
        final boolean mutation="POST".equals(method);
        final long deadline=System.nanoTime()+TimeUnit.MILLISECONDS.toNanos(BUDGET_MS);
        Future<String> future;
        try {
            future=worker.submit(()->{
                HttpsURLConnection connection=null;
                try {
                    if(closed)throw failure("closed",0,false,false);
                    connection=factory.open(new URL(origin+"/api/v1/"+path)); active=connection;
                    if(closed)throw failure("closed",0,false,false);
                    connection.setInstanceFollowRedirects(false);
                    connection.setUseCaches(false);
                    connection.setConnectTimeout(remaining(deadline));connection.setReadTimeout(remaining(deadline));
                    connection.setRequestMethod(method);
                    String requestToken=token;
                    if(closed || requestToken==null)throw failure("closed",0,false,false);
                    connection.setRequestProperty("Authorization","Bearer "+requestToken);
                    connection.setRequestProperty("Accept","application/json");
                    connection.setRequestProperty("Accept-Encoding","identity");
                    if(payload!=null) {
                        byte[] bytes=StrictJson.write(payload).getBytes(StandardCharsets.UTF_8);
                        if(bytes.length>MAX_BYTES)throw failure("invalid_response",0,false,false);
                        connection.setRequestProperty("Content-Type","application/json; charset=utf-8");
                        connection.setDoOutput(true);connection.setFixedLengthStreamingMode(bytes.length);
                        try(OutputStream out=connection.getOutputStream()){out.write(bytes);}
                    }
                    connection.setReadTimeout(remaining(deadline));
                    int status=connection.getResponseCode();
                    if(status==204 && noContentAllowed)return null;
                    if(status!=200) {
                        boolean retry=status==408||status==429||status==502||status==503||status==504;
                        throw failure("http_rejected",status,retry,mutation&&(status>=500||status==408));
                    }
                    String type=connection.getContentType();
                    if(type==null||!type.toLowerCase(java.util.Locale.ROOT).matches("application/json(?:\\s*;\\s*charset=utf-8)?"))throw failure("invalid_response",status,false,mutation);
                    if(connection.getContentLengthLong()>MAX_BYTES)throw failure("invalid_response",status,false,mutation);
                    ByteArrayOutputStream data=new ByteArrayOutputStream();byte[] buffer=new byte[4096];
                    try(InputStream input=connection.getInputStream()) {
                        while(true) {
                            connection.setReadTimeout(remaining(deadline));int count=input.read(buffer);
                            if(count<0)break;
                            if(data.size()+count>MAX_BYTES)throw failure("invalid_response",status,false,mutation);
                            data.write(buffer,0,count);
                        }
                    }
                    remaining(deadline);
                    return StandardCharsets.UTF_8.newDecoder().onMalformedInput(CodingErrorAction.REPORT).onUnmappableCharacter(CodingErrorAction.REPORT).decode(ByteBuffer.wrap(data.toByteArray())).toString();
                }catch(ControlException safe){throw safe;}
                catch(Exception failure){throw failure("transport_failed",0,true,mutation);}
                finally {if(connection!=null)connection.disconnect();active=null;busy.set(false);}
            });
        }catch(RejectedExecutionException rejected){busy.set(false);throw failure("closed",0,false,false);}
        try {String result=future.get(Math.max(1,deadline-System.nanoTime()),TimeUnit.NANOSECONDS);if(closed)throw failure("closed",0,false,mutation);return result;}
        catch(TimeoutException timeout){future.cancel(true);close();throw failure("request_timeout",0,true,mutation);}
        catch(InterruptedException interrupted){future.cancel(true);close();Thread.currentThread().interrupt();throw failure("transport_failed",0,true,mutation);}
        catch(ExecutionException result){if(result.getCause() instanceof ControlException)throw (ControlException)result.getCause();throw failure("transport_failed",0,true,mutation);}
    }
    private int remaining(long deadline) {
        long nanos=deadline-System.nanoTime();if(nanos<=0)throw failure("request_timeout",0,true,true);
        return (int)Math.max(1,Math.min(BUDGET_MS,TimeUnit.NANOSECONDS.toMillis(nanos)));
    }
    private static ControlException failure(String code,int status,boolean retry,boolean ambiguous){return new ControlException(code,status,retry,ambiguous);}
    private <T> T decode(java.util.function.Supplier<T> decoder,boolean mutation) {
        try{return decoder.get();}catch(IllegalArgumentException malformed){throw failure("invalid_response",200,false,mutation);}
    }
    public HelloResult hello(AgentHello hello) {
        String body=request("POST","agents/hello",ProtocolCodec.hello(hello),false);
        HelloResult result=decode(()->ProtocolCodec.decodeHello(body),true);
        if(!hello.agentId.equals(result.agentId))throw failure("invalid_response",200,false,true);return result;
    }
    public Instant heartbeat(AgentHello hello) {String body=request("POST","agents/heartbeat",ProtocolCodec.hello(hello),false);return decode(()->ProtocolCodec.decodeHeartbeat(body),true);}
    public LeaseGrant claim(String deviceId) {
        Checks.uuid(deviceId);
        String body=request("POST","leases/claim",ProtocolCodec.map("device_id",deviceId),true);
        if(body==null)return null;
        LeaseGrant grant=decode(()->ProtocolCodec.decodeGrant(body),true);
        if(!deviceId.equals(grant.job.spec.deviceId))throw failure("invalid_response",200,false,true);
        return grant;
    }
    public JobView getJob(String jobId) {Checks.uuid(jobId);String body=request("GET","jobs/"+jobId,null,false);return jobResult(body,jobId,false);}
    public RenewResult renew(String jobId,LeaseCommand lease) {Checks.uuid(jobId);String body=request("POST","jobs/"+jobId+"/renew",ProtocolCodec.lease(lease),false);return decode(()->ProtocolCodec.decodeRenew(body),true);}
    public JobView events(String jobId,LeaseCommand lease,JobEvent event) {Checks.uuid(jobId);return jobResult(request("POST","jobs/"+jobId+"/events",ProtocolCodec.map("lease",ProtocolCodec.lease(lease),"event",ProtocolCodec.event(event)),false),jobId,true);}
    public JobView stopAck(String jobId,LeaseCommand lease,String eventId,long expectedRevision) {Checks.uuid(jobId);Checks.uuid(eventId);Checks.counter(expectedRevision);return jobResult(request("POST","jobs/"+jobId+"/stop-ack",ProtocolCodec.map("lease",ProtocolCodec.lease(lease),"event_id",eventId,"expected_revision",expectedRevision),false),jobId,true);}
    private JobView jobResult(String body,String id,boolean mutation) {JobView job=decode(()->ProtocolCodec.decodeJob(body),mutation);if(!id.equals(job.jobId))throw failure("invalid_response",200,false,mutation);return job;}
    @Override public synchronized void close(){
        if(closed)return;
        closed=true;token=null;worker.shutdownNow();
        // A platform DNS/read/disconnect operation can ignore interruption. Never block the
        // foreground caller or create replacement request workers after uncertain timeout.
        HttpsURLConnection connection=active;
        if(connection!=null){Thread cleanup=new Thread(connection::disconnect,"happyrun-https-close");cleanup.setDaemon(true);cleanup.start();}
    }
    @Override public String toString(){return "HttpsAgentClient[redacted]";}
}
