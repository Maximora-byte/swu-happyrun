package org.happyrun.app;

import android.test.ActivityInstrumentationTestCase2;
import android.view.View;
import android.widget.Button;
import android.widget.EditText;
import android.widget.TextView;

/** Local UI checks only: never supplies a usable endpoint or credential. */
@SuppressWarnings("deprecation")
public final class RemoteAgentActivityTest extends ActivityInstrumentationTestCase2<RemoteAgentActivity> {
    public RemoteAgentActivityTest() { super(RemoteAgentActivity.class); }
    private int id(RemoteAgentActivity activity, String name) {
        return activity.getResources().getIdentifier(name, "id", activity.getPackageName());
    }
    public void testStartsDisconnectedAndTokenNotRestored() throws Throwable {
        RemoteAgentActivity activity = getActivity();
        runTestOnUiThread(() -> {
            EditText token = activity.findViewById(id(activity, "remote_token"));
            assertEquals("", token.getText().toString());
            assertFalse(token.isSaveEnabled());
            assertEquals(View.IMPORTANT_FOR_AUTOFILL_NO_EXCLUDE_DESCENDANTS, token.getImportantForAutofill());
            Button stop = activity.findViewById(id(activity, "remote_stop"));
            assertFalse(stop.isEnabled());
        });
    }
    public void testRejectsCleartextWithoutConnecting() throws Throwable {
        RemoteAgentActivity activity = getActivity();
        runTestOnUiThread(() -> {
            ((EditText) activity.findViewById(id(activity, "remote_endpoint"))).setText("http://127.0.0.1");
            ((EditText) activity.findViewById(id(activity, "remote_token"))).setText("synthetic-not-valid");
            activity.findViewById(id(activity, "remote_connect")).performClick();
            EditText token = activity.findViewById(id(activity, "remote_token"));
            assertEquals("", token.getText().toString());
            TextView state = activity.findViewById(id(activity, "remote_status"));
            assertTrue(state.getText().toString().contains("输入无效"));
            assertFalse(activity.findViewById(id(activity, "remote_stop")).isEnabled());
        });
    }
    public void testLeavingPageClearsSecretWithoutSavingIt() throws Throwable {
        RemoteAgentActivity activity = getActivity();
        runTestOnUiThread(() -> {
            EditText token = activity.findViewById(id(activity, "remote_token"));
            token.setText("synthetic-local-field-only");
            getInstrumentation().callActivityOnStop(activity);
            assertEquals("", token.getText().toString());
            assertFalse(activity.getSharedPreferences("remote_agent_address", 0).contains("token"));
            getInstrumentation().callActivityOnStart(activity);
        });
    }
}
