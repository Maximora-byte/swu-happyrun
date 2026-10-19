package org.happyrun.app.remote.simulation;
import java.io.*;
import java.security.*;
/** Only this explicitly synthetic WGS84 fixture is executable. No downloads/import fallback. */
public final class BundledSimulationProfiles {
 private BundledSimulationProfiles(){}
 public static final String PROFILE_ID="11111111-1111-4111-8111-111111111111";
 public static final String ROUTE_ID="22222222-2222-4222-8222-222222222222";
 public static final String PROFILE_REVISION="b9005da1c3470e5583d0950e085b7eecae8860ca4d3df909b485847265b3da3f";
 public static final String ROUTE_REVISION="2098e955d3f5d998ec252128d63e4dbbcfbdd2ef81edd7496ad746ae52dc6f1c";
 public static final double SPEED_MPS=2, MAX_SECONDS=30;
 public static final double DISTANCE_M=distance(.2,.2,.20001,.20001);
 private static double distance(double a,double b,double c,double d){double lat=Math.toRadians(c-a),lon=Math.toRadians(d-b);double h=Math.sin(lat/2)*Math.sin(lat/2)+Math.cos(Math.toRadians(a))*Math.cos(Math.toRadians(c))*Math.sin(lon/2)*Math.sin(lon/2);return 6371000*2*Math.atan2(Math.sqrt(h),Math.sqrt(1-h));}
 public static void require(String profile,String pr,String route,String rr)throws IOException {
  if(!PROFILE_ID.equals(profile)||!PROFILE_REVISION.equals(pr)||!ROUTE_ID.equals(route)||!ROUTE_REVISION.equals(rr))throw new IllegalArgumentException("unsupported_simulation_profile");verifyAssets();
 }
 public static void verifyAssets()throws IOException {verify("school",PROFILE_REVISION);verify("route",ROUTE_REVISION);}
 private static void verify(String name,String expected)throws IOException {
  try(InputStream in=BundledSimulationProfiles.class.getResourceAsStream("/remote-simulation/"+name+".canonical.json")) {
   if(in==null)throw new IOException("simulation_asset_missing");
   MessageDigest md=MessageDigest.getInstance("SHA-256");byte[] b=new byte[512];int count=0,n;
   while((n=in.read(b))!=-1){count+=n;if(count>4096)throw new IOException("simulation_asset_invalid");md.update(b,0,n);}
   StringBuilder hex=new StringBuilder();for(byte v:md.digest())hex.append(String.format(java.util.Locale.ROOT,"%02x",v&255));
   if(!expected.equals(hex.toString()))throw new IOException("simulation_asset_invalid");
  }catch(NoSuchAlgorithmException e){throw new AssertionError(e);}
 }
}
