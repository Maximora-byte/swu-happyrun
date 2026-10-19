package org.happyrun.app.remote.transport;
/** Never retains request, token, URL, body, cause or server-provided message. */
public final class ControlException extends RuntimeException {
    public final int httpStatus;
    public final boolean retryable;
    public final boolean ambiguous;
    public ControlException(String code,int httpStatus,boolean retryable,boolean ambiguous) {
        super(safe(code));this.httpStatus=httpStatus;this.retryable=retryable;this.ambiguous=ambiguous;
    }
    private static String safe(String code) {
        switch(code) {case "transport_failed":case "request_timeout":case "http_rejected":case "invalid_response":case "closed":case "busy":return code;default:return "control_failure";}
    }
}
