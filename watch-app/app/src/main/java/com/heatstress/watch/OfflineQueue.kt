package com.heatstress.watch

import android.content.ContentValues
import android.content.Context
import android.database.sqlite.SQLiteDatabase
import android.database.sqlite.SQLiteOpenHelper
import android.util.Log
import org.json.JSONObject

/**
 * 离线数据队列 — 断网时缓冲，恢复后重传
 *
 * SQLite 表结构:
 *   CREATE TABLE offline_queue (
 *     id        INTEGER PRIMARY KEY AUTOINCREMENT,
 *     topic     TEXT NOT NULL,
 *     payload   TEXT NOT NULL,        -- JSON 字符串
 *     created   INTEGER NOT NULL,     -- epoch ms
 *     retries   INTEGER DEFAULT 0
 *   )
 *
 * 策略:
 *   - 队列上限 10000 条，FIFO 淘汰
 *   - 最多重传 3 次，超限标记为丢弃
 *   - 只缓存 vital 数据（高价值），status 不缓存
 */
class OfflineQueue(context: Context) {

    companion object {
        private const val TAG = "OfflineQueue"
        private const val DB_NAME = "heatstress_queue.db"
        private const val DB_VERSION = 1
        private const val TABLE_NAME = "offline_queue"
        private const val MAX_QUEUE_SIZE = 10000L
        private const val MAX_RETRIES = 3
    }

    private val dbHelper = QueueDbHelper(context)
    private var db: SQLiteDatabase? = null

    fun open() {
        db = dbHelper.writableDatabase
    }

    fun close() {
        db?.close()
        db = null
    }

    /**
     * 入队一条数据
     */
    fun enqueue(topic: String, payload: String) {
        val d = db ?: return
        try {
            // FIFO 淘汰：超出上限删最旧的
            val count = d.compileStatement("SELECT COUNT(*) FROM $TABLE_NAME").simpleQueryForLong()
            if (count >= MAX_QUEUE_SIZE) {
                d.execSQL(
                    "DELETE FROM $TABLE_NAME WHERE id IN " +
                    "(SELECT id FROM $TABLE_NAME ORDER BY id ASC LIMIT ${count - MAX_QUEUE_SIZE + 100})"
                )
            }

            val cv = ContentValues().apply {
                put("topic", topic)
                put("payload", payload)
                put("created", System.currentTimeMillis())
            }
            d.insert(TABLE_NAME, null, cv)
        } catch (e: Exception) {
            Log.e(TAG, "入队失败: ${e.message}")
        }
    }

    /**
     * 获取并清空所有未超限的队列项
     * 返回 Pair<id, topic, payload> 列表
     */
    fun dequeuePending(limit: Int = 50): List<Triple<Long, String, String>> {
        val d = db ?: return emptyList()
        val result = mutableListOf<Triple<Long, String, String>>()
        try {
            val cursor = d.rawQuery(
                "SELECT id, topic, payload FROM $TABLE_NAME " +
                "WHERE retries < $MAX_RETRIES ORDER BY id ASC LIMIT $limit",
                null
            )
            cursor.use {
                while (it.moveToNext()) {
                    result.add(Triple(
                        it.getLong(0),
                        it.getString(1),
                        it.getString(2)
                    ))
                }
            }
        } catch (e: Exception) {
            Log.e(TAG, "出队失败: ${e.message}")
        }
        return result
    }

    /**
     * 标记某条已发送（删除）
     */
    fun markSent(id: Long) {
        db?.delete(TABLE_NAME, "id = ?", arrayOf(id.toString()))
    }

    /**
     * 增加重试次数
     */
    fun markRetry(id: Long) {
        db?.execSQL("UPDATE $TABLE_NAME SET retries = retries + 1 WHERE id = $id")
    }

    /**
     * 获取队列大小
     */
    fun size(): Long {
        val d = db ?: return 0
        return d.compileStatement("SELECT COUNT(*) FROM $TABLE_NAME").simpleQueryForLong()
    }

    // ============================================================
    // SQLiteOpenHelper
    // ============================================================

    private class QueueDbHelper(context: Context) : SQLiteOpenHelper(
        context, DB_NAME, null, DB_VERSION
    ) {
        override fun onCreate(db: SQLiteDatabase) {
            db.execSQL("""
                CREATE TABLE $TABLE_NAME (
                    id        INTEGER PRIMARY KEY AUTOINCREMENT,
                    topic     TEXT NOT NULL,
                    payload   TEXT NOT NULL,
                    created   INTEGER NOT NULL,
                    retries   INTEGER DEFAULT 0
                )
            """)
            db.execSQL("CREATE INDEX idx_retries ON $TABLE_NAME(retries)")
        }

        override fun onUpgrade(db: SQLiteDatabase, oldVersion: Int, newVersion: Int) {
            db.execSQL("DROP TABLE IF EXISTS $TABLE_NAME")
            onCreate(db)
        }
    }
}
