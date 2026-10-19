package org.happyrun.app;

import android.app.Activity;
import android.content.SharedPreferences;
import android.os.Bundle;
import android.os.SystemClock;
import android.view.WindowManager;
import android.widget.Button;
import android.widget.EditText;
import android.widget.TextView;
import java.io.File;
import java.nio.charset.StandardCharsets;
import java.security.MessageDigest;
import java.time.Instant;
import java.util.UUID;
import java.util.concurrent.ExecutorService;
import java.util.concurrent.Executors;
import org.happyrun.app.remote.protocol.AgentHello;
import org.happyrun.app.remote.protocol.Checks;
import org.happyrun.app.remote.protocol.JobView;
import org.happyrun.app.remote.transport.HttpsAgentClient;
import org.happyrun.app.remote.journal.RemoteJournal;
import org.happyrun.app.remote.runtime.RemoteAgentRunner;
import org.happyrun.app.remote.runtime.RemoteClock;
import org.happyrun.app.remote.simulation.RemoteFakeDriver;
import org.happyrun.app.remote.ui.RemoteSessionGate;
import org.happyrun.app.remote.ui.RemoteOutcome;

/** Explicit foreground-only synthetic agent. No network in lifecycle initialization. */
public final class RemoteAgentActivity extends Activity {
    private final RemoteSessionGate gate = new RemoteSessionGate();
    private final ExecutorService worker = Executors.newSingleThreadExecutor();
    private EditText endpoint, agentId, deviceId, token;
    private Button connect, stop;
    private TextView status;
    private boolean destroyed;
    private boolean foreground;

    @Override protected void onCreate(Bundle savedInstanceState) {
        super.onCreate(savedInstanceState);
        getWindow().addFlags(WindowManager.LayoutParams.FLAG_SECURE);
        setContentView(R.layout.activity_remote_agent);
        endpoint = findViewById(R.id.remote_endpoint);
        agentId = findViewById(R.id.remote_agent_id);
        deviceId = findViewById(R.id.remote_device_id);
        token = findViewById(R.id.remote_token);
        token.setSaveEnabled(false);
        connect = findViewById(R.id.remote_connect);
        stop = findViewById(R.id.remote_stop);
        status = findViewById(R.id.remote_status);
        SharedPreferences saved = getSharedPreferences("remote_agent_address", MODE_PRIVATE);
        endpoint.setText(saved.getString("endpoint", ""));
        agentId.setText(saved.getString("agent_id", ""));
        deviceId.setText(saved.getString("device_id", ""));
        connect.setOnClickListener(v -> connectOnce());
        stop.setOnClickListener(v -> {
            gate.stop();
            token.setText("");
            status.setText(R.string.remote_stopping);
            updateButtons();
        });
    }

    @Override protected void onStart() {
        super.onStart();
        foreground = true;
        gate.enter();
        if (gate.blocked()) status.setText(R.string.remote_storage_failed);
        updateButtons();
    }

    private void updateButtons() {
        connect.setEnabled(foreground && !gate.busy() && !gate.blocked());
        stop.setEnabled(foreground && gate.busy() && !gate.stopping());
        endpoint.setEnabled(!gate.busy());
        agentId.setEnabled(!gate.busy());
        deviceId.setEnabled(!gate.busy());
        token.setEnabled(!gate.busy());
    }

    private void connectOnce() {
        if (!gate.begin()) return;
        HttpsAgentClient client = null;
        try {
            String origin = HttpsAgentClient.validateBaseUrl(endpoint.getText().toString().trim());
            String aid = agentId.getText().toString().trim();
            String did = deviceId.getText().toString().trim();
            Checks.uuid(aid);
            Checks.uuid(did);
            client = new HttpsAgentClient(origin, token.getText().toString());
            token.setText("");
            getSharedPreferences("remote_agent_address", MODE_PRIVATE).edit()
                .putString("endpoint", origin).putString("agent_id", aid).putString("device_id", did).apply();
            final HttpsAgentClient ownedClient = client;
            final File directory = new File(getFilesDir(), "remote-agent/" + namespace(origin, aid, did));
            status.setText(R.string.remote_connecting);
            updateButtons();
            worker.execute(() -> runSession(ownedClient, directory, aid, did));
        } catch (RuntimeException error) {
            if (client != null) client.close();
            gate.finish();
            token.setText("");
            status.setText(R.string.remote_invalid);
            updateButtons();
        }
    }

    private void runSession(HttpsAgentClient client, File directory, String aid, String did) {
        JobView result = null;
        String localStatus = "unknown";
        RemoteFakeDriver driver = new RemoteFakeDriver();
        try (HttpsAgentClient owned = client; RemoteJournal journal = new RemoteJournal(directory.toPath())) {
            RemoteClock clock = new RemoteClock() {
                @Override public double monotonicSeconds() { return SystemClock.elapsedRealtimeNanos() / 1e9; }
                @Override public Instant utcNow() { return Instant.now().truncatedTo(java.time.temporal.ChronoUnit.MICROS); }
                @Override public void sleepMillis(long millis) throws InterruptedException { Thread.sleep(millis); }
            };
            RemoteAgentRunner runner = new RemoteAgentRunner(owned, journal, driver, clock, aid, did, 10);
            gate.attach(runner::requestStop);
            if (!gate.stopping()) {
                AgentHello observation = new AgentHello(aid, did, UUID.randomUUID().toString(), Instant.now().truncatedTo(java.time.temporal.ChronoUnit.MICROS));
                runner.setHeartbeatObservation(observation);
                owned.hello(observation);
                result = runner.runOnce();
                localStatus = runner.localStatus();
                if ("storage_failed_not_persisted".equals(localStatus)) gate.block();
            }
        } catch (java.io.IOException storageFailure) {
            localStatus = "storage_failed_not_persisted";
            gate.block();
        } catch (Exception ignored) {
            // Never show exception text, request URLs, credentials or raw response data.
        } finally {
            driver.stop();
            client.close();
        }
        final String finalLocalStatus = localStatus;
        final JobView finalResult = result;
        runOnUiThread(() -> {
            gate.finish();
            if (destroyed) return;
            RemoteOutcome outcome = RemoteOutcome.classify(finalLocalStatus, finalResult != null);
            if (outcome == RemoteOutcome.STORAGE_BLOCKED) {
                status.setText(R.string.remote_storage_failed);
            } else if (outcome == RemoteOutcome.UNCONFIRMED) {
                status.setText(R.string.remote_failed);
            } else if (outcome == RemoteOutcome.CONFIRMED) {
                status.setText(getString(R.string.remote_result, finalResult.state, finalResult.jobId));
            } else {
                status.setText(R.string.remote_idle);
            }
            updateButtons();
        });
    }

    private static String namespace(String origin, String aid, String did) {
        try {
            byte[] digest = MessageDigest.getInstance("SHA-256")
                .digest((origin + "\n" + aid + "\n" + did).getBytes(StandardCharsets.UTF_8));
            StringBuilder value = new StringBuilder();
            for (byte b : digest) value.append(String.format(java.util.Locale.ROOT, "%02x", b & 255));
            return value.toString();
        } catch (java.security.NoSuchAlgorithmException impossible) { throw new AssertionError(impossible); }
    }

    @Override protected void onStop() {
        foreground = false;
        gate.leave();
        token.setText("");
        status.setText(gate.blocked() ? R.string.remote_storage_failed : R.string.remote_left);
        updateButtons();
        super.onStop();
    }

    @Override protected void onDestroy() {
        destroyed = true;
        gate.leave();
        token.setText("");
        worker.shutdown(); // Existing bounded stop/attention may finish; no new work is submitted.
        super.onDestroy();
    }
}
