package com.countonme.attendance.server

import android.content.ContentValues
import android.content.Context
import android.database.Cursor
import android.database.sqlite.SQLiteDatabase
import android.util.Log
import com.countonme.attendance.engine.Engine
import java.io.File
import java.text.SimpleDateFormat
import java.util.Date
import java.util.Locale

/**
 * SQLite persistence layer — a 1:1 port of the Python backend's
 * `app/database/__init__.py` (DatabaseManager + SessionRepository +
 * StudentRepository + AttendanceRepository).
 *
 * - `attendance.db` lives in the app's [Context.getFilesDir].
 * - Single writable connection with synchronized access (thread-safe without
 *   connection pooling, matching the spec).
 * - Schema matches the Flask backend exactly (same tables, columns, indices,
 *   and UNIQUE(student_name, session_id) constraint).
 * - Implements [Engine.DbBridge] so the engine can mark attendance and write
 *   engagement telemetry without knowing about the server layer.
 * - Python caches `active_session_id`, student total and present-count for
 *   2.0 s; that throttle is replicated here (cache invalidation on writes).
 * - On init, mirrors the Python bootstrap: if no session is active, activate
 *   the most recent session for today, else create a default session for today.
 *
 * All public list/get methods return snake_case column-name maps so the server
 * layer can serialize them straight to JSON with org.json.
 */
class Database(context: Context) : Engine.DbBridge {

    companion object {
        private const val TAG = "Database"
        private const val DB_NAME = "attendance.db"

        /** Python-side cache TTL (2.0 s) for hot counters. */
        private const val CACHE_TTL_MS = 2_000L

        private val DATE_FMT = SimpleDateFormat("yyyy-MM-dd", Locale.US)
        private val TIME_FMT = SimpleDateFormat("HH:mm:ss", Locale.US)
        private val HM_FMT = SimpleDateFormat("HH:mm", Locale.US)
    }

    private val lock = Any()
    private val conn: SQLiteDatabase

    init {
        val dbFile = File(context.filesDir, DB_NAME)
        dbFile.parentFile?.mkdirs()
        conn = SQLiteDatabase.openOrCreateDatabase(dbFile.absolutePath, null)
        initSchema()
    }

    /** Run [block] on the shared connection under the global lock (reentrant). */
    private fun <T> withDb(block: (SQLiteDatabase) -> T): T = synchronized(lock) { block(conn) }

    /** Close the connection (idempotent, exception-safe). */
    fun close() {
        synchronized(lock) {
            try { conn.close() } catch (_: Throwable) { }
        }
    }

    // ---------------- schema ----------------

    private fun initSchema() {
        withDb { db ->
            try {
                db.execSQL(
                    "CREATE TABLE IF NOT EXISTS students (" +
                        "id INTEGER PRIMARY KEY AUTOINCREMENT, " +
                        "student_id TEXT UNIQUE NOT NULL, " +
                        "name TEXT NOT NULL, " +
                        "email TEXT, " +
                        "department TEXT, " +
                        "created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP, " +
                        "is_active BOOLEAN DEFAULT 1)"
                )
                db.execSQL(
                    "CREATE TABLE IF NOT EXISTS sessions (" +
                        "id INTEGER PRIMARY KEY AUTOINCREMENT, " +
                        "session_id TEXT UNIQUE NOT NULL, " +
                        "title TEXT NOT NULL, " +
                        "course TEXT, " +
                        "date DATE NOT NULL, " +
                        "start_time TEXT, " +
                        "end_time TEXT, " +
                        "room TEXT, " +
                        "is_active BOOLEAN DEFAULT 0, " +
                        "created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP)"
                )
                db.execSQL(
                    "CREATE TABLE IF NOT EXISTS attendance (" +
                        "id INTEGER PRIMARY KEY AUTOINCREMENT, " +
                        "student_name TEXT NOT NULL, " +
                        "student_id TEXT, " +
                        "session_id TEXT NOT NULL, " +
                        "date DATE NOT NULL, " +
                        "time TEXT NOT NULL, " +
                        "engagement_score REAL DEFAULT 0.0, " +
                        "status TEXT DEFAULT 'Present', " +
                        "created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP, " +
                        "UNIQUE(student_name, session_id))"
                )
                db.execSQL(
                    "CREATE TABLE IF NOT EXISTS engagement_logs (" +
                        "id INTEGER PRIMARY KEY AUTOINCREMENT, " +
                        "student_name TEXT NOT NULL, " +
                        "timestamp TIMESTAMP DEFAULT CURRENT_TIMESTAMP, " +
                        "engagement_score REAL DEFAULT 0.0, " +
                        "status TEXT, " +
                        "ear_value REAL DEFAULT 0.0, " +
                        "head_pose_yaw REAL DEFAULT 0.0, " +
                        "head_pose_pitch REAL DEFAULT 0.0)"
                )
                db.execSQL("CREATE INDEX IF NOT EXISTS idx_sessions_date ON sessions(date)")
                db.execSQL("CREATE INDEX IF NOT EXISTS idx_sessions_active ON sessions(is_active)")
                db.execSQL("CREATE INDEX IF NOT EXISTS idx_attendance_session ON attendance(session_id)")
                db.execSQL("CREATE INDEX IF NOT EXISTS idx_attendance_date ON attendance(date)")
                db.execSQL("CREATE INDEX IF NOT EXISTS idx_attendance_student ON attendance(student_name)")
                bootstrapActiveSession(db)
            } catch (t: Throwable) {
                Log.e(TAG, "schema init failed", t)
            }
        }
    }

    /** Python `_init_database` step 6: guarantee an active session exists. */
    private fun bootstrapActiveSession(db: SQLiteDatabase) {
        try {
            db.rawQuery("SELECT id FROM sessions WHERE is_active = 1", emptyArray())
                .use { if (it.moveToFirst()) return }
            val today = DATE_FMT.format(Date())
            db.rawQuery(
                "SELECT session_id FROM sessions WHERE date = ? ORDER BY id DESC LIMIT 1",
                arrayOf(today)
            ).use { c ->
                if (c.moveToFirst()) {
                    db.execSQL(
                        "UPDATE sessions SET is_active = 1 WHERE session_id = ?",
                        arrayOf(c.getString(0))
                    )
                    return
                }
            }
            val defaultId = "SES_" + today.replace("-", "") + "_DEFAULT"
            db.execSQL(
                "INSERT INTO sessions (session_id, title, course, date, start_time, end_time, room, is_active) " +
                    "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                arrayOf(defaultId, "General Class ($today)", "General", today, "09:00", "10:00", "Room 101", 1)
            )
        } catch (t: Throwable) {
            Log.e(TAG, "bootstrap active session failed", t)
        }
    }

    // ---------------- DbBridge (hot path, called from engine threads) ----------------

    /** Cached active session id — Python caches this query for 2.0 s. */
    @Volatile private var cachedActiveSessionId: String? = null
    @Volatile private var cachedActiveSessionAt = 0L
    @Volatile private var cachedActiveSessionValid = false

    @Volatile private var cachedTotalStudents = -1
    @Volatile private var cachedTotalAt = 0L

    @Volatile private var cachedPresentCount = -1
    @Volatile private var cachedPresentAt = 0L
    @Volatile private var cachedPresentKey: Any? = null

    /**
     * Mark a student present in the given (or active) session.
     * Existing record: engagement score update only, returns false
     * (Python: "Attendance already marked in this session").
     */
    override fun markAttendance(name: String, engagementScore: Double, sessionId: String?): Boolean {
        return try {
            withDb { db ->
                val sid = sessionId ?: activeSessionId() ?: run {
                    // No session anywhere — mirror Python fallback: synthesize a default.
                    "SES_" + DATE_FMT.format(Date()).replace("-", "") + "_DEFAULT"
                }
                val sessDate = queryOne(
                    db, "SELECT date FROM sessions WHERE session_id = ?", arrayOf(sid)
                )?.get("date")?.toString() ?: DATE_FMT.format(Date())
                val studentId = queryOne(
                    db, "SELECT student_id FROM students WHERE name = ? LIMIT 1", arrayOf(name)
                )?.get("student_id")?.toString()
                val existingId = queryOne(
                    db, "SELECT id FROM attendance WHERE student_name = ? AND session_id = ?",
                    arrayOf(name, sid)
                )?.get("id")
                if (existingId != null) {
                    db.execSQL(
                        "UPDATE attendance SET engagement_score = ? WHERE id = ?",
                        arrayOf(engagementScore, existingId)
                    )
                    false
                } else {
                    db.execSQL(
                        "INSERT INTO attendance (student_name, student_id, session_id, date, time, engagement_score, status) " +
                            "VALUES (?, ?, ?, ?, ?, ?, 'Present')",
                        arrayOf(name, studentId, sid, sessDate, TIME_FMT.format(Date()), engagementScore)
                    )
                    clearActiveSessionCache()
                    true
                }
            }
        } catch (t: Throwable) {
            Log.e(TAG, "markAttendance failed for $name", t)
            false
        }
    }

    /** Session id of the is_active=1 row (2.0 s cache, Python parity). */
    override fun activeSessionId(): String? {
        val now = System.currentTimeMillis()
        if (cachedActiveSessionValid && now - cachedActiveSessionAt < CACHE_TTL_MS) {
            return cachedActiveSessionId
        }
        return try {
            val id = withDb { db ->
                queryOne(db, "SELECT session_id FROM sessions WHERE is_active = 1 LIMIT 1", emptyArray())
            }?.get("session_id")?.toString()
            cachedActiveSessionId = id
            cachedActiveSessionAt = now
            cachedActiveSessionValid = true
            id
        } catch (t: Throwable) {
            Log.e(TAG, "activeSessionId failed", t)
            null
        }
    }

    /** Throttled engagement log insert (the engine already throttles 3 s; DB-side is a no-op-safe insert). */
    override fun writeEngagementScore(name: String, score: Double) {
        try {
            withDb { db ->
                db.execSQL(
                    "INSERT INTO engagement_logs (student_name, engagement_score) VALUES (?, ?)",
                    arrayOf(name, score)
                )
            }
        } catch (t: Throwable) {
            Log.e(TAG, "writeEngagementScore failed for $name", t)
        }
    }

    /** Total registered students (2.0 s cache, Python parity). */
    override fun totalStudents(): Int {
        val now = System.currentTimeMillis()
        if (cachedTotalStudents >= 0 && now - cachedTotalAt < CACHE_TTL_MS) return cachedTotalStudents
        return try {
            val n = withDb { db ->
                countOf(db, "SELECT COUNT(*) AS n FROM students WHERE is_active = 1", emptyArray())
            }
            cachedTotalStudents = n
            cachedTotalAt = now
            n
        } catch (t: Throwable) {
            Log.e(TAG, "totalStudents failed", t)
            0
        }
    }

    /** Attendance count for the active/selected session (2.0 s cache keyed by session id). */
    override fun presentCount(sessionId: String?): Int {
        val now = System.currentTimeMillis()
        val key = sessionId ?: "ACTIVE"
        if (cachedPresentKey == key && cachedPresentCount >= 0 && now - cachedPresentAt < CACHE_TTL_MS) {
            return cachedPresentCount
        }
        return try {
            val sid = sessionId ?: activeSessionId()
            val n = withDb { db ->
                if (sid != null) {
                    countOf(db, "SELECT COUNT(*) AS n FROM attendance WHERE session_id = ?", arrayOf(sid))
                } else {
                    countOf(
                        db, "SELECT COUNT(*) AS n FROM attendance WHERE date = ?",
                        arrayOf(DATE_FMT.format(Date()))
                    )
                }
            }
            cachedPresentKey = key
            cachedPresentCount = n
            cachedPresentAt = now
            n
        } catch (t: Throwable) {
            Log.e(TAG, "presentCount failed", t)
            0
        }
    }

    /** Invalidate the 2.0 s caches (call after any session/attendance/student write). */
    fun clearActiveSessionCache() {
        cachedActiveSessionValid = false
        cachedActiveSessionId = null
        cachedTotalStudents = -1
        cachedTotalAt = 0L
        cachedPresentCount = -1
        cachedPresentAt = 0L
        cachedPresentKey = null
    }

    // ---------------- Students CRUD ----------------

    /** All active students ordered by name (Python get_all_students). */
    fun listStudents(): List<Map<String, Any?>> = try {
        withDb { db -> queryList(db, "SELECT * FROM students WHERE is_active = 1 ORDER BY name", emptyArray()) }
    } catch (t: Throwable) {
        Log.e(TAG, "listStudents failed", t)
        emptyList()
    }

    /**
     * Upsert a student on student_id conflict (Python add_student semantics:
     * name always refreshed; email/department only when provided; is_active=1).
     * Returns the row id, or -1 on failure.
     */
    fun addStudent(studentId: String, name: String, email: String?, dept: String?): Long {
        return try {
            withDb { db ->
                val insertCv = ContentValues().apply {
                    put("student_id", studentId)
                    put("name", name)
                    put("email", email)
                    put("department", dept)
                }
                var rowId = db.insertWithOnConflict("students", null, insertCv, SQLiteDatabase.CONFLICT_IGNORE)
                if (rowId == -1L) {
                    // Existing student: refresh fields (COALESCE parity for nullables).
                    val updCv = ContentValues().apply {
                        put("name", name)
                        if (email != null) put("email", email)
                        if (dept != null) put("department", dept)
                        put("is_active", 1)
                    }
                    db.update("students", updCv, "student_id = ?", arrayOf(studentId))
                    db.rawQuery(
                        "SELECT id FROM students WHERE student_id = ? LIMIT 1", arrayOf(studentId)
                    ).use { c -> if (c.moveToFirst()) rowId = c.getLong(0) }
                }
                clearActiveSessionCache()
                rowId
            }
        } catch (t: Throwable) {
            Log.e(TAG, "addStudent failed for $name", t)
            -1L
        }
    }

    /** Hard-delete a student by student_id (Python delete_student(soft_delete=False)). */
    fun deleteStudent(studentId: String): Boolean {
        return try {
            withDb { db ->
                db.delete("students", "student_id = ?", arrayOf(studentId))
            }.also { clearActiveSessionCache() } > 0
        } catch (t: Throwable) {
            Log.e(TAG, "deleteStudent failed for $studentId", t)
            false
        }
    }

    /** Single student row by student_id (Python get_student). */
    fun getStudent(studentId: String): Map<String, Any?>? = try {
        withDb { db ->
            queryOne(db, "SELECT * FROM students WHERE student_id = ? LIMIT 1", arrayOf(studentId))
        }
    } catch (t: Throwable) {
        Log.e(TAG, "getStudent failed for $studentId", t)
        null
    }

    /** Update editable student fields (StudentRepository.update_student parity). */
    fun updateStudent(studentId: String, name: String, email: String?, dept: String?): Boolean {
        return try {
            withDb { db ->
                val cv = ContentValues()
                cv.put("name", name)
                cv.put("email", email)
                cv.put("department", dept)
                db.update("students", cv, "student_id = ?", arrayOf(studentId))
            }.also { clearActiveSessionCache() } > 0
        } catch (t: Throwable) {
            Log.e(TAG, "updateStudent failed for $studentId", t)
            false
        }
    }

    // ---------------- Sessions CRUD ----------------

    /**
     * Sessions for a date, or all sessions (Python get_sessions_by_date /
     * get_all_sessions). Each row: sessions.* + present_count + avg_engagement.
     */
    fun listSessions(date: String?): List<Map<String, Any?>> {
        val base = "SELECT s.*, COUNT(a.id) AS present_count, " +
            "COALESCE(AVG(a.engagement_score), 0.0) AS avg_engagement " +
            "FROM sessions s LEFT JOIN attendance a ON s.session_id = a.session_id "
        return try {
            withDb { db ->
                if (date != null) {
                    queryList(
                        db,
                        base + "WHERE s.date = ? GROUP BY s.id " +
                            "ORDER BY s.is_active DESC, s.start_time DESC, s.id DESC",
                        arrayOf(date)
                    )
                } else {
                    queryList(
                        db,
                        base + "GROUP BY s.id ORDER BY s.date DESC, s.start_time DESC, s.id DESC",
                        emptyArray()
                    )
                }
            }
        } catch (t: Throwable) {
            Log.e(TAG, "listSessions failed", t)
            emptyList()
        }
    }

    /**
     * Create a session (Python create_session). session_id = "sess_" + timestamp
     * hex. When [setActive], all other sessions are deactivated first.
     * @return the new session_id.
     */
    fun createSession(
        title: String,
        course: String?,
        date: String,
        start: String?,
        end: String?,
        room: String?,
        setActive: Boolean
    ): String {
        val sessionId = "sess_" + java.lang.Long.toHexString(System.currentTimeMillis())
        try {
            withDb { db ->
                db.beginTransaction()
                try {
                    if (setActive) {
                        db.execSQL("UPDATE sessions SET is_active = 0")
                    }
                    db.execSQL(
                        "INSERT INTO sessions (session_id, title, course, date, start_time, end_time, room, is_active) " +
                            "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                        arrayOf(
                            sessionId, title, course ?: title, date,
                            start ?: HM_FMT.format(Date()), end ?: "", room ?: "Room 101",
                            if (setActive) 1 else 0
                        )
                    )
                    db.setTransactionSuccessful()
                } finally {
                    try { db.endTransaction() } catch (_: Throwable) { }
                }
            }
        } catch (t: Throwable) {
            Log.e(TAG, "createSession failed", t)
        } finally {
            clearActiveSessionCache()
        }
        return sessionId
    }

    /** The is_active=1 session as a map, or null (Python get_active_session without auto-create). */
    fun getActiveSession(): Map<String, Any?>? = try {
        withDb { db -> sessionRow(db, null, activeOnly = true) }
    } catch (t: Throwable) {
        Log.e(TAG, "getActiveSession failed", t)
        null
    }

    /** One session by session_id as a map (present_count/avg_engagement joined), or null. */
    fun getSession(sessionId: String): Map<String, Any?>? = try {
        withDb { db -> sessionRow(db, sessionId, activeOnly = false) }
    } catch (t: Throwable) {
        Log.e(TAG, "getSession failed", t)
        null
    }

    /** Activate exactly one session (Python set_active_session). */
    fun setActiveSession(sessionId: String): Boolean {
        return try {
            withDb { db ->
                db.beginTransaction()
                try {
                    db.execSQL("UPDATE sessions SET is_active = 0")
                    db.execSQL("UPDATE sessions SET is_active = 1 WHERE session_id = ?", arrayOf(sessionId))
                    db.setTransactionSuccessful()
                    true
                } finally {
                    try { db.endTransaction() } catch (_: Throwable) { }
                }
            }
        } catch (t: Throwable) {
            Log.e(TAG, "setActiveSession failed", t)
            false
        } finally {
            clearActiveSessionCache()
        }
    }

    /** Delete a session + its attendance; if it was active, promote the newest session (Python delete_session). */
    fun deleteSession(sessionId: String): Boolean {
        return try {
            withDb { db ->
                db.beginTransaction()
                try {
                    val wasActive = queryOne(
                        db, "SELECT is_active FROM sessions WHERE session_id = ?", arrayOf(sessionId)
                    )?.get("is_active")?.toString() == "1"
                    db.execSQL("DELETE FROM attendance WHERE session_id = ?", arrayOf(sessionId))
                    val deletedRows = db.delete("sessions", "session_id = ?", arrayOf(sessionId))
                    if (wasActive) {
                        queryOne(
                            db, "SELECT session_id FROM sessions ORDER BY date DESC, id DESC LIMIT 1", emptyArray()
                        )?.get("session_id")?.toString()?.also { next ->
                            db.execSQL("UPDATE sessions SET is_active = 1 WHERE session_id = ?", arrayOf(next))
                        }
                    }
                    db.setTransactionSuccessful()
                    deletedRows > 0
                } finally {
                    try { db.endTransaction() } catch (_: Throwable) { }
                }
            }
        } catch (t: Throwable) {
            Log.e(TAG, "deleteSession failed", t)
            false
        } finally {
            clearActiveSessionCache()
        }
    }

    // ---------------- Attendance CRUD ----------------

    /**
     * Attendance records for a session (or today's records when null), joined
     * with session title/course (Python get_attendance_by_session / _by_date).
     */
    fun listAttendance(sessionId: String?): List<Map<String, Any?>> {
        val base = "SELECT a.*, s.title AS session_title, s.course AS course " +
            "FROM attendance a LEFT JOIN sessions s ON a.session_id = s.session_id "
        return try {
            withDb { db ->
                if (sessionId != null) {
                    queryList(
                        db, base + "WHERE a.session_id = ? ORDER BY a.time DESC, a.id DESC", arrayOf(sessionId)
                    )
                } else {
                    queryList(
                        db,
                        base + "WHERE a.date = ? ORDER BY a.session_id, a.time DESC, a.id DESC",
                        arrayOf(DATE_FMT.format(Date()))
                    )
                }
            }
        } catch (t: Throwable) {
            Log.e(TAG, "listAttendance failed", t)
            emptyList()
        }
    }

    /** Attendance records for an explicit date (Python get_attendance_by_date). */
    fun listAttendanceByDate(date: String): List<Map<String, Any?>> = try {
        withDb { db ->
            queryList(
                db,
                "SELECT a.*, s.title AS session_title, s.course AS course " +
                    "FROM attendance a LEFT JOIN sessions s ON a.session_id = s.session_id " +
                    "WHERE a.date = ? ORDER BY a.session_id, a.time DESC, a.id DESC",
                arrayOf(date)
            )
        }
    } catch (t: Throwable) {
        Log.e(TAG, "listAttendanceByDate failed", t)
        emptyList()
    }

    /** Manually correct status (and optionally score) of one attendance record (Python update_attendance_status). */
    fun updateAttendanceStatus(recordId: Int, status: String, score: Double?): Boolean {
        return try {
            withDb { db ->
                if (score != null) {
                    db.execSQL(
                        "UPDATE attendance SET status = ?, engagement_score = ? WHERE id = ?",
                        arrayOf(status, score, recordId)
                    )
                } else {
                    db.execSQL(
                        "UPDATE attendance SET status = ? WHERE id = ?",
                        arrayOf(status, recordId)
                    )
                }
                true
            }.also { clearActiveSessionCache() }
        } catch (t: Throwable) {
            Log.e(TAG, "updateAttendanceStatus failed", t)
            false
        }
    }

    /**
     * Manually add or correct a student's attendance in a session
     * (Python manual_mark_student). Returns (success, message).
     */
    fun manualMark(name: String, sessionId: String, status: String, score: Double): Pair<Boolean, String> {
        try {
            val result = withDb { db ->
                val sessDate = queryOne(
                    db, "SELECT date FROM sessions WHERE session_id = ?", arrayOf(sessionId)
                )?.get("date")?.toString() ?: DATE_FMT.format(Date())
                val studentId = queryOne(
                    db, "SELECT student_id FROM students WHERE name = ? LIMIT 1", arrayOf(name)
                )?.get("student_id")?.toString()
                val existingId = queryOne(
                    db, "SELECT id FROM attendance WHERE student_name = ? AND session_id = ?",
                    arrayOf(name, sessionId)
                )?.get("id")
                if (existingId != null) {
                    db.execSQL(
                        "UPDATE attendance SET status = ?, engagement_score = ? WHERE id = ?",
                        arrayOf(status, score, existingId)
                    )
                    Pair(true, "Updated existing student attendance record")
                } else {
                    db.execSQL(
                        "INSERT INTO attendance (student_name, student_id, session_id, date, time, engagement_score, status) " +
                            "VALUES (?, ?, ?, ?, ?, ?, ?)",
                        arrayOf(name, studentId, sessionId, sessDate, TIME_FMT.format(Date()), score, status)
                    )
                    Pair(true, "Student $name marked as $status")
                }
            }
            clearActiveSessionCache()
            return result
        } catch (t: Throwable) {
            Log.e(TAG, "manualMark failed for $name", t)
            return Pair(false, "Failed to mark attendance: ${t.message}")
        }
    }

    /** Delete a single attendance record (Python delete_attendance). */
    fun deleteAttendance(recordId: Int): Boolean {
        return try {
            withDb { db -> db.delete("attendance", "id = ?", arrayOf(recordId.toString())) }
                .also { clearActiveSessionCache() } > 0
        } catch (t: Throwable) {
            Log.e(TAG, "deleteAttendance failed", t)
            false
        }
    }

    // ---------------- shared query helpers ----------------

    /** Session map with present_count + avg_engagement (Python Session.to_dict parity). */
    private fun sessionRow(db: SQLiteDatabase, sessionId: String?, activeOnly: Boolean): Map<String, Any?>? {
        val sql = "SELECT s.*, COUNT(a.id) AS present_count, " +
            "COALESCE(AVG(a.engagement_score), 0.0) AS avg_engagement " +
            "FROM sessions s LEFT JOIN attendance a ON s.session_id = a.session_id "
        return if (activeOnly) {
            queryOne(db, sql + "WHERE s.is_active = 1 GROUP BY s.id LIMIT 1", emptyArray())
        } else {
            queryOne(db, sql + "WHERE s.session_id = ? GROUP BY s.id LIMIT 1", arrayOf(sessionId ?: ""))
        }
    }

    private fun queryOne(db: SQLiteDatabase, sql: String, args: Array<String>): Map<String, Any?>? {
        db.rawQuery(sql, args).use { c ->
            if (c.moveToFirst()) return cursorToMap(c)
        }
        return null
    }

    private fun queryList(db: SQLiteDatabase, sql: String, args: Array<String>): List<Map<String, Any?>> {
        val list = ArrayList<Map<String, Any?>>()
        db.rawQuery(sql, args).use { c ->
            while (c.moveToNext()) list.add(cursorToMap(c))
        }
        return list
    }

    private fun countOf(db: SQLiteDatabase, sql: String, args: Array<String>): Int {
        db.rawQuery(sql, args).use { c ->
            if (c.moveToFirst()) return (c.getLong(0)).toInt()
        }
        return 0
    }

    /** Cursor row → snake_case map (column types preserved). */
    private fun cursorToMap(c: Cursor): Map<String, Any?> {
        val map = LinkedHashMap<String, Any?>(c.columnCount)
        for (i in 0 until c.columnCount) {
            map[c.getColumnName(i)] = when (c.getType(i)) {
                Cursor.FIELD_TYPE_NULL -> null
                Cursor.FIELD_TYPE_INTEGER -> c.getLong(i)
                Cursor.FIELD_TYPE_FLOAT -> c.getDouble(i)
                else -> c.getString(i)
            }
        }
        return map
    }
}