package org.happyrun.app.remote.protocol;
import java.time.Instant;
public final class Checks {
 private Checks() {}
 public static IllegalArgumentException invalid() {return new IllegalArgumentException("invalid_protocol_value");}
 public static String text(String v) {if(v==null||v.isEmpty())throw invalid();return v;}
 public static String uuid(String v) {if(v==null||!v.matches("[0-9a-f]{8}(?:-[0-9a-f]{4}){3}-[0-9a-f]{12}"))throw invalid();return v;}
 public static String digest(String v) {if(v==null||!v.matches("[0-9a-f]{64}"))throw invalid();return v;}
 public static long counter(long v) {if(v<0)throw invalid();return v;}
 public static String one(String v,String choices) {if(v==null||!java.util.Arrays.asList(choices.split(" ")).contains(v))throw invalid();return v;}
 public static String optional(String v,String choices) {return v==null?null:one(v,choices);}
 public static String phase(String v) {return optional(v,"leased preflight ready running finishing verifying cancelling");}
 public static String state(String v) {return one(v,"queued leased preflight ready running finishing verifying cancelling needs_attention completed failed cancelled");}
 public static Instant instant(Instant v) {if(v==null||v.getNano()%1000!=0)throw invalid();time(v.toString());return v;}
 public static Instant time(String v) {if(v==null||v.startsWith("0000-")||!v.matches("[0-9]{4}-[0-9]{2}-[0-9]{2}T[0-9]{2}:[0-9]{2}:[0-9]{2}(?:\\.[0-9]{1,6})?Z"))throw invalid();try{return java.time.OffsetDateTime.parse(v).toInstant();}catch(java.time.DateTimeException e){throw invalid();}}
}
