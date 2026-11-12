package org.happyrun.app.runtime;

import android.content.Context;
import java.util.List;
import java.util.ArrayList;
import android.content.ContentValues;
import android.database.Cursor;
import android.database.sqlite.SQLiteDatabase;
import android.database.sqlite.SQLiteOpenHelper;

/** One private app database, no account, tokens, location writes or external storage. */
final class LocalStore extends SQLiteOpenHelper {
    LocalStore(Context context) { super(context,"happyrun-local-simulation.db",null,1); }
    @Override public void onCreate(SQLiteDatabase db) {
        db.execSQL("CREATE TABLE runs (id TEXT PRIMARY KEY,state TEXT NOT NULL,reason TEXT NOT NULL,distance REAL NOT NULL,total REAL NOT NULL,started INTEGER NOT NULL,updated INTEGER NOT NULL)");
    }
    @Override public void onUpgrade(SQLiteDatabase db,int oldVersion,int newVersion) {
        throw new IllegalStateException("unsupported_database_upgrade");
    }
    void recover() {
        ContentValues v=new ContentValues(); v.put("state","needs_attention");
        v.put("reason","restart_uncertain"); v.put("updated",System.currentTimeMillis());
        getWritableDatabase().update("runs",v,"state IN (?,?)",new String[]{"running","ready"});
    }
    TaskSnapshot latest() {
        try (Cursor c=getReadableDatabase().rawQuery("SELECT id,state,reason,distance,total,started,updated FROM runs ORDER BY rowid DESC LIMIT 1",null)) {
            return c.moveToFirst() ? new TaskSnapshot(c.getString(0),c.getString(1),c.getString(2),c.getDouble(3),c.getDouble(4),c.getLong(5),c.getLong(6)) : null;
        }
    }
    TaskSnapshot get(String id) {
        try (Cursor c=getReadableDatabase().rawQuery("SELECT id,state,reason,distance,total,started,updated FROM runs WHERE id=?",new String[]{id})) {
            return c.moveToFirst() ? new TaskSnapshot(c.getString(0),c.getString(1),c.getString(2),c.getDouble(3),c.getDouble(4),c.getLong(5),c.getLong(6)) : null;
        }
    }
    List<TaskSnapshot> history() {
        List<TaskSnapshot> rows=new ArrayList<>();
        try (Cursor c=getReadableDatabase().rawQuery("SELECT id,state,reason,distance,total,started,updated FROM runs ORDER BY rowid DESC LIMIT 50",null)) {
            while(c.moveToNext()) rows.add(new TaskSnapshot(c.getString(0),c.getString(1),c.getString(2),c.getDouble(3),c.getDouble(4),c.getLong(5),c.getLong(6)));
        }
        return rows;
    }
    void save(TaskSnapshot s) {
        ContentValues v=new ContentValues();v.put("id",s.id);v.put("state",s.state);
        v.put("reason",s.reason);v.put("distance",s.distanceM);v.put("total",s.totalDistanceM);
        v.put("started",s.startedAtMs);v.put("updated",s.updatedAtMs);
        if (getWritableDatabase().insertWithOnConflict("runs",null,v,SQLiteDatabase.CONFLICT_REPLACE) < 0)
            throw new IllegalStateException("simulation_persistence_failed");
    }
}
