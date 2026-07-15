package com.heatstress.watch

import android.content.ContentValues
import android.content.Context
import android.database.sqlite.SQLiteDatabase
import android.database.sqlite.SQLiteOpenHelper
import android.util.Log

class OfflineQueue(context: Context) {
    private val dbHelper = QueueDbHelper(context.applicationContext)
    private var db: SQLiteDatabase? = null

    @Synchronized
    fun open() {
        if (db?.isOpen != true) db = dbHelper.writableDatabase
    }

    @Synchronized
    fun close() {
        db?.close()
        db = null
    }

    @Synchronized
    fun enqueue(topic: String, payload: String) {
        val database = db ?: return
        try {
            val count = database.compileStatement("SELECT COUNT(*) FROM $TABLE_NAME").simpleQueryForLong()
            if (count >= MAX_QUEUE_SIZE) {
                val removeCount = count - MAX_QUEUE_SIZE + PRUNE_BATCH_SIZE
                database.execSQL(
                    "DELETE FROM $TABLE_NAME WHERE id IN " +
                        "(SELECT id FROM $TABLE_NAME ORDER BY id ASC LIMIT $removeCount)"
                )
            }
            database.insert(TABLE_NAME, null, ContentValues().apply {
                put("topic", topic)
                put("payload", payload)
                put("created", System.currentTimeMillis())
                put("retries", 0)
            })
        } catch (e: Exception) {
            Log.e(TAG, "Queue insert failed", e)
        }
    }

    @Synchronized
    fun dequeuePending(limit: Int = 100): List<Triple<Long, String, String>> {
        val database = db ?: return emptyList()
        val result = mutableListOf<Triple<Long, String, String>>()
        try {
            database.rawQuery(
                "SELECT id, topic, payload FROM $TABLE_NAME ORDER BY id ASC LIMIT ?",
                arrayOf(limit.coerceIn(1, 500).toString())
            ).use { cursor ->
                while (cursor.moveToNext()) {
                    result += Triple(cursor.getLong(0), cursor.getString(1), cursor.getString(2))
                }
            }
        } catch (e: Exception) {
            Log.e(TAG, "Queue read failed", e)
        }
        return result
    }

    @Synchronized
    fun markSent(id: Long) {
        db?.delete(TABLE_NAME, "id = ?", arrayOf(id.toString()))
    }

    @Synchronized
    fun markRetry(id: Long) {
        db?.execSQL("UPDATE $TABLE_NAME SET retries = retries + 1 WHERE id = ?", arrayOf(id))
    }

    @Synchronized
    fun size(): Long = try {
        db?.compileStatement("SELECT COUNT(*) FROM $TABLE_NAME")?.simpleQueryForLong() ?: 0L
    } catch (_: Exception) {
        0L
    }

    private class QueueDbHelper(context: Context) :
        SQLiteOpenHelper(context, DB_NAME, null, DB_VERSION) {
        override fun onCreate(db: SQLiteDatabase) {
            db.execSQL(
                """
                CREATE TABLE $TABLE_NAME (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    topic TEXT NOT NULL,
                    payload TEXT NOT NULL,
                    created INTEGER NOT NULL,
                    retries INTEGER NOT NULL DEFAULT 0
                )
                """.trimIndent()
            )
        }

        override fun onUpgrade(db: SQLiteDatabase, oldVersion: Int, newVersion: Int) = Unit
    }

    companion object {
        private const val TAG = "OfflineQueue"
        private const val DB_NAME = "heatstress_queue.db"
        private const val DB_VERSION = 1
        private const val TABLE_NAME = "offline_queue"
        private const val MAX_QUEUE_SIZE = 10_000L
        private const val PRUNE_BATCH_SIZE = 100L
    }
}
