package com.countonme.attendance.server

import android.content.Context
import android.graphics.Bitmap
import android.graphics.BitmapFactory
import android.util.Base64
import android.util.Log
import androidx.lifecycle.LifecycleOwner
import com.countonme.attendance.engine.Engine
import fi.iki.elonen.NanoHTTPD
import org.json.JSONArray
import org.json.JSONObject
import java.io.ByteArrayInputStream
import java.io.File
import java.io.IOException
import java.io.InputStream
import java.io.PipedInputStream
import java.io.PipedOutputStream
import java.text.SimpleDateFormat
import java.util.Date
import java.util.Locale
import java.util.UUID

/** Unknown-face review queue operations (implemented elsewhere; routed by LocalServer). */
interface QueueHandler {
    fun list(cluster: Boolean): Map<String, Any?>
    fun clusterify(): Map<String, Any?>
    fun clear(): Map<String, Any?>
    fun register(filename: String, name: String, studentId: String, dept: String, email: String?): Map<String, Any?>
    fun registerCluster(filenames: List<String>, name: String, studentId: String, dept: String, email: String?): Map<String, Any?>
    fun ignore(filenames: List<String>): Map<String, Any?>
}

/** Batch (multi-image folder) attendance processing (implemented elsewhere). */
interface BatchHandler {
    fun run(folder: String): Map<String, Any?>
}

/**
 * Embedded HTTP backend — a 1:1 port of the Flask server (`app/__init__.py`)
 * into NanoHTTPD, bound to 127.0.0.1:8971 so the React SPA (served same-origin
 * from assets/public/) can call it with relative or absolute URLs.
 *
 * Serves:
 *  - static SPA files from assets/public/ (index.html SPA fallback included)
 *  - `/video_feed` MJPEG stream (multipart/x-mixed-replace, ~25 fps)
 *  - `/api/stream/events` SSE telemetry (500 ms, 1.5 s DB field cache)
 *  - the full JSON API with Flask-parity routes, keys, and error shapes
 *  - `/exports/[f]` and `/unknown/[f]` file downloads
 *
 * Also hosts [EngineHost] which implements the engine's [Engine.DbBridge]
 * (delegating to [Database]) and [Engine.UnknownQueueBridge] (unknown face
 * crops to filesDir/unknown/, capped at 50 entries).
 */
class LocalServer(
    private val appContext: Context,
    private val lifecycleOwner: LifecycleOwner,
    private val engine: Engine,
    private val db: Database,
    private val queueHandler: QueueHandler?,
    private val batchHandler: BatchHandler?
) : NanoHTTPD(HOSTNAME, PORT) {

    companion object {
        private const val TAG = "LocalServer"
        const val PORT = 8971
        const val HOSTNAME = "127.0.0.1"

        private const val MIME_HTML = "text/html"
        private const val MIME_JS = "application/javascript"
        private const val MIME_CSS = "text/css"
        private const val MIME_JSON = "application/json"
        private const val MIME_SVG = "image/svg+xml"
        private const val MIME_PNG = "image/png"
        private const val MIME_JPG = "image/jpeg"
        private const val MIME_WOFF2 = "font/woff2"
        private const val MIME_ICON = "image/x-icon"
        private const val MIME_CSV = "text/csv"

        /** SSE DB-derived field cache TTL (Python parity: 1.5 s). */
        private const val SSE_CACHE_TTL_MS = 1_500L
    }

    private val engineHost = EngineHost(appContext, engine, db)

    // ---------------- lifecycle ----------------

    /** Bind and start listening (idempotent, exception-safe). */
    fun startServer() {
        try {
            start(SOCKET_READ_TIMEOUT, false)
            Log.i(TAG, "Local server listening on http://$HOSTNAME:$PORT")
        } catch (t: Throwable) {
            Log.e(TAG, "startServer failed", t)
        }
    }

    /** Stop listening and close all connections (exception-safe). */
    fun stopServer() {
        try {
            stop()
            Log.i(TAG, "Local server stopped")
        } catch (t: Throwable) {
            Log.e(TAG, "stopServer failed", t)
        }
    }

    // ---------------- request entry ----------------

    override fun serve(session: IHTTPSession): Response {
        val uri = session.uri ?: "/"
        val method = session.method

        // CORS preflight (the SPA runs at https://localhost while this API is
        // http://127.0.0.1:8971 — fetch() with application/json triggers
        // OPTIONS preflights that must be answered before the real call).
        if (method == Method.OPTIONS) {
            val pre = newFixedLengthResponse(Response.Status.OK, MIME_HTML, "")
            addCorsHeaders(pre)
            return pre
        }

        val resp = try {
            if (uri.startsWith("/api/")) {
                routeApi(session, method, uri)
            } else when (method) {
                Method.GET, Method.HEAD -> routeGet(session, uri)
                else -> newFixedLengthResponse(
                    Response.Status.METHOD_NOT_ALLOWED, MIME_JSON,
                    """{"error": "Method not allowed"}"""
                )
            }
        } catch (t: Throwable) {
            Log.e(TAG, "serve failed: $method $uri", t)
            jsonError(Response.Status.INTERNAL_ERROR, (t.message ?: "Internal server error"))
        }
        addCorsHeaders(resp)
        return resp
    }

    private fun addCorsHeaders(resp: Response) {
        resp.addHeader("Access-Control-Allow-Origin", "*")
        resp.addHeader("Access-Control-Allow-Methods", "GET, POST, PUT, PATCH, DELETE, OPTIONS")
        resp.addHeader("Access-Control-Allow-Headers", "Content-Type, Authorization, X-Requested-With")
        resp.addHeader("Access-Control-Max-Age", "600")
    }

    // ---------------- body parsing ----------------

    /**
     * Robust JSON body extraction across POST/PUT/PATCH/DELETE:
     *  - POST: parseBody() stashes raw bodies under "postData".
     *  - PUT: parseBody() stashes a temp-file path under "content" (read the file).
     *  - PATCH/DELETE: NanoHTTPD discards these bodies, so we read
     *    content-length bytes straight off the session input stream.
     * Never falls back to a raw read after a *successful* parseBody — the
     * stream is already consumed and a second read would block.
     */
    private fun readJsonBody(session: IHTTPSession): JSONObject {
        val method = session.method
        if (method == Method.POST || method == Method.PUT) {
            val files = HashMap<String, String>()
            try {
                session.parseBody(files)
                files["postData"]?.let { return tryParseJson(it) }
                files["content"]?.let { path ->
                    val f = File(path)
                    if (f.isFile) return tryParseJson(f.readText())
                }
                return JSONObject() // parsed OK, but no usable body
            } catch (t: Throwable) {
                Log.w(TAG, "parseBody failed; attempting raw body read", t)
                // fall through to best-effort raw read
            }
        }
        return tryParseJson(readRawBody(session))
    }

    /** Read content-length bytes from the raw session stream (PATCH/DELETE bodies). */
    private fun readRawBody(session: IHTTPSession): String? {
        return try {
            val lenStr = session.headers["content-length"] ?: return null
            val len = lenStr.trim().toLongOrNull() ?: return null
            if (len <= 0L) return null
            val buf = ByteArray(len.toInt())
            val input = session.inputStream
            var off = 0
            while (off < buf.size) {
                val n = input.read(buf, off, buf.size - off)
                if (n < 0) break
                off += n
            }
            String(buf, 0, off, Charsets.UTF_8)
        } catch (t: Throwable) {
            Log.w(TAG, "readRawBody failed", t)
            null
        }
    }

    private fun tryParseJson(text: String?): JSONObject {
        if (text.isNullOrBlank()) return JSONObject()
        return try {
            JSONObject(text)
        } catch (_: Throwable) {
            JSONObject()
        }
    }

    // ---------------- query params ----------------

    private fun queryParam(session: IHTTPSession, key: String): String? =
        session.parameters[key]?.firstOrNull()?.takeIf { it.isNotBlank() }

    /**
     * Validate a yyyy-MM-dd query/body value like Python's
     * datetime.strptime(x, '%Y-%m-%d'); invalid → null (callers fall back).
     */
    private fun validDateOrNull(raw: String?): String? {
        if (raw.isNullOrBlank()) return null
        return try {
            java.text.SimpleDateFormat("yyyy-MM-dd", Locale.US).apply {
                isLenient = false
            }.let { fmt ->
                fmt.parse(raw.trim())
                fmt.format(fmt.parse(raw.trim()))
            }
        } catch (_: Throwable) {
            null
        }
    }

    // ---------------- API routing ----------------

    private fun routeApi(session: IHTTPSession, method: Method, uri: String): Response {
        val seg = uri.trim('/').split('/').filter { it.isNotEmpty() }
        // seg[0] == "api"

        when (uri) {
            "/api/start" -> if (method == Method.POST) return apiStart()
            "/api/stop" -> if (method == Method.POST) return apiStop()
            "/api/camera/flip" -> if (method == Method.POST) return apiCameraFlip()
            "/api/stats" -> if (method == Method.GET) return apiStats(session)
            "/api/engagement" -> if (method == Method.GET) return apiEngagement()
            "/api/encode" -> if (method == Method.POST) return apiEncodeDataset()
            "/api/register-student" -> if (method == Method.POST) return apiRegisterStudent(session)
            "/api/export/csv" -> if (method == Method.GET) return apiExportCsv(session)
            "/api/batch-attendance" -> if (method == Method.POST) return apiBatchAttendance(session)
            "/api/tuning" -> {
                if (method == Method.GET) return apiTuningGet()
                if (method == Method.POST) return apiTuningPost(session)
            }
        }

        when {
            uri == "/api/stream/events" && method == Method.GET -> return sseStream(session)
            uri == "/api/sessions" && method == Method.GET -> return apiListSessions(session)
            uri == "/api/sessions" && method == Method.POST -> return apiCreateSession(session)
            uri == "/api/sessions/active" && method == Method.GET -> return apiGetActiveSession()
            uri == "/api/sessions/active" && method == Method.POST -> return apiSetActiveSession(session)
            uri == "/api/attendance" && method == Method.GET -> return apiGetAttendance(session)
            uri == "/api/attendance/manual" && method == Method.POST -> return apiManualMark(session)
            uri == "/api/students" && method == Method.GET -> return apiListStudents()
            uri == "/api/students" && method == Method.POST -> return apiAddStudent(session)
            uri == "/api/unknown-faces" && method == Method.GET -> return apiUnknownFaces(session)
            uri == "/api/unknown-faces" && method == Method.DELETE -> return apiClearUnknownQueue()
            uri == "/api/unknown-faces/clusterify" && method == Method.POST -> return apiClusterify()
            uri == "/api/unknown-faces/clear" &&
                (method == Method.POST || method == Method.DELETE) -> return apiClearUnknownQueue()
            uri == "/api/unknown-faces/register" && method == Method.POST -> return apiRegisterUnknown(session, cluster = false)
            uri == "/api/unknown-faces/register-cluster" && method == Method.POST -> return apiRegisterUnknown(session, cluster = true)
            uri == "/api/unknown-faces/ignore" && method == Method.POST -> return apiIgnoreUnknown(session)
        }

        // Path-parameter routes
        if (seg.size >= 3) {
            when (seg[1]) {
                "sessions" -> {
                    if (seg.size == 3 && method == Method.DELETE) return apiDeleteSession(seg[2])
                }
                "attendance" -> {
                    if (seg.size == 3 && seg[2].toIntOrNull() != null) {
                        val id = seg[2].toInt()
                        if (method == Method.DELETE) return apiDeleteAttendance(id)
                        if (method == Method.PUT || method == Method.PATCH) return apiUpdateAttendance(id, session)
                    }
                }
                "students" -> {
                    if (seg.size == 3) {
                        if (method == Method.DELETE) return apiDeleteStudent(seg[2])
                        if (method == Method.PATCH || method == Method.PUT) return apiUpdateStudent(seg[2], session)
                    }
                    if (seg.size >= 4 && seg[3] == "photos") {
                        val sid = seg[2]
                        if (seg.size == 4 && method == Method.GET) return apiListStudentPhotos(sid)
                        if (seg.size == 4 && method == Method.POST) return apiAddStudentPhotos(sid, session)
                        if (seg.size == 5 && seg[4].toIntOrNull() != null) {
                            val idx = seg[4].toInt()
                            if (method == Method.GET) return apiGetStudentPhoto(sid, idx)
                            if (method == Method.DELETE) return apiDeleteStudentPhoto(sid, idx)
                        }
                    }
                }
            }
        }

        return jsonError(Response.Status.NOT_FOUND, "Not found: $method $uri")
    }

    // ---------------- engine start/stop + stats ----------------

    private fun apiStart(): Response {
        if (engine.isRunning.get()) {
            return jsonResponse("""{"status": "already_running"}""")
        }
        return try {
            engine.start(lifecycleOwner)
            // Foreground service keeps OEM freezers (ColorOS Hans etc.) from
            // suspending the camera/server while the user switches apps.
            com.countonme.attendance.EngineService.start(appContext)
            jsonResponse("""{"status": "started"}""")
        } catch (t: Throwable) {
            jsonError(Response.Status.INTERNAL_ERROR, "Failed to start camera: ${t.message}")
        }
    }

    private fun apiStop(): Response {
        try {
            engine.stop()
        } catch (_: Throwable) {
        }
        try {
            com.countonme.attendance.EngineService.stop(appContext)
        } catch (_: Throwable) {
        }
        return jsonResponse("""{"status": "stopped"}""")
    }

    /** POST /api/camera/flip — switch front/back lens at runtime. */
    private fun apiCameraFlip(): Response {
        if (!engine.isRunning.get()) {
            return jsonError(Response.Status.BAD_REQUEST, "Camera not running")
        }
        return try {
            val lens = engine.flipCamera()
            jsonResponse("""{"status": "success", "lens": "$lens"}""")
        } catch (t: Throwable) {
            jsonError(Response.Status.INTERNAL_ERROR, t.message ?: "Flip failed")
        }
    }

    private fun apiStats(session: IHTTPSession): Response {
        val sessionId = queryParam(session, "session_id")
        val payload = JSONObject()
            .put("date", SimpleDateFormat("yyyy-MM-dd", Locale.US).format(Date()))
            .put("total_students", db.totalStudents())
        val active = db.getActiveSession()
        val target = sessionId ?: active?.get("session_id")?.toString()
        val records = db.listAttendance(target)
        val presentCount = records.size
        val total = db.totalStudents()
        val avgEngagement = if (presentCount > 0) {
            records.map { toDouble(it["engagement_score"]) }.average()
        } else 0.0
        payload.put("present_count", presentCount)
        payload.put("absent_count", maxOf(0, total - presentCount))
        payload.put("attendance_percentage", if (total > 0) presentCount * 100.0 / total else 0.0)
        payload.put("average_engagement", round1(avgEngagement))
        val studentStats = JSONArray()
        for (r in records) {
            studentStats.put(
                JSONObject()
                    .put("id", r["id"] ?: JSONObject.NULL)
                    .put("name", r["student_name"] ?: "")
                    .put("time", r["time"] ?: "")
                    .put("engagement_score", toDouble(r["engagement_score"]))
                    .put("status", r["status"] ?: "Present")
                    .put("session_id", r["session_id"] ?: JSONObject.NULL)
                    .put("session_title", r["session_title"] ?: JSONObject.NULL)
            )
        }
        payload.put("student_stats", studentStats)
        payload.put("active_session", active?.let { sessionToDict(it) } ?: JSONObject.NULL)
        payload.put("is_running", engine.isRunning.get())
        payload.put("fps", engine.fps)
        payload.put("tracked_students", trackedStudentsJson())
        payload.put("tracked_students_count", engine.trackedStudents.size)
        payload.put(
            "perf", JSONObject()
                .put("detect_ms", round1(engine.perfDetectMs))
                .put("landmark_ms", round1(engine.perfLandmarkMs))
                .put("bitmap_ms", round1(engine.perfBitmapMs))
                .put("frame_w", engine.perfFrameW)
                .put("frame_h", engine.perfFrameH)
        )
        return jsonResponse(payload.toString())
    }

    // ---------------- sessions ----------------

    private fun apiListSessions(session: IHTTPSession): Response {
        // Python: invalid date string falls back to all sessions.
        val date = validDateOrNull(queryParam(session, "date"))
        val sessions = db.listSessions(date)
        val active = db.getActiveSession()
        val arr = JSONArray()
        for (s in sessions) arr.put(sessionToDict(s))
        return jsonResponse(
            JSONObject()
                .put("sessions", arr)
                .put("active_session_id", active?.get("session_id") ?: JSONObject.NULL)
                .put("active_session", active?.let { sessionToDict(it) } ?: JSONObject.NULL)
                .toString()
        )
    }

    private fun apiCreateSession(session: IHTTPSession): Response {
        val body = readJsonBody(session)
        val title = body.optString("title").trim()
        if (title.isEmpty()) return jsonError(Response.Status.BAD_REQUEST, "Session title is required")
        // Python: invalid date string falls back to today.
        val dateStr = validDateOrNull(body.optString("date"))
            ?: SimpleDateFormat("yyyy-MM-dd", Locale.US).format(Date())
        val sessionId = db.createSession(
            title = title,
            course = body.optString("course").takeIf { it.isNotBlank() } ?: title,
            date = dateStr,
            start = body.optString("start_time").takeIf { it.isNotBlank() },
            end = body.optString("end_time").takeIf { it.isNotBlank() },
            room = body.optString("room").takeIf { it.isNotBlank() },
            setActive = body.optBoolean("set_active", true)
        )
        db.clearActiveSessionCache()
        if (body.optBoolean("set_active", true)) {
            try { engine.recognizerBridge().clearCooldowns() } catch (_: Throwable) {}
        }
        val created = db.getSession(sessionId)
        return jsonResponse(
            JSONObject()
                .put("status", "success")
                .put("session", created?.let { sessionToDict(it) } ?: JSONObject.NULL)
                .toString()
        )
    }

    private fun apiGetActiveSession(): Response {
        val active = db.getActiveSession()
        return jsonResponse(
            JSONObject()
                .put("active_session", active?.let { sessionToDict(it) } ?: JSONObject.NULL)
                .toString()
        )
    }

    private fun apiSetActiveSession(session: IHTTPSession): Response {
        val body = readJsonBody(session)
        val sessionId = body.optString("session_id").takeIf { it.isNotBlank() }
            ?: return jsonError(Response.Status.BAD_REQUEST, "session_id is required")
        val success = db.setActiveSession(sessionId)
        if (success) {
            db.clearActiveSessionCache()
            try { engine.recognizerBridge().clearCooldowns() } catch (_: Throwable) {}
        }
        val active = db.getSession(sessionId)
        return jsonResponse(
            JSONObject()
                .put("status", if (success) "success" else "not_found")
                .put("active_session", active?.let { sessionToDict(it) } ?: JSONObject.NULL)
                .toString()
        )
    }

    private fun apiDeleteSession(sessionId: String): Response {
        val success = db.deleteSession(sessionId)
        if (success) {
            db.clearActiveSessionCache()
            try { engine.recognizerBridge().clearCooldowns() } catch (_: Throwable) {}
        }
        val active = db.getActiveSession()
        return jsonResponse(
            JSONObject()
                .put("status", if (success) "success" else "not_found")
                .put("active_session", active?.let { sessionToDict(it) } ?: JSONObject.NULL)
                .toString()
        )
    }

    // ---------------- attendance ----------------

    private fun apiGetAttendance(session: IHTTPSession): Response {
        val sessionId = queryParam(session, "session_id")
        val dateStr = queryParam(session, "date")
        if (sessionId != null) {
            val records = db.listAttendance(sessionId)
            val arr = JSONArray()
            for (r in records) arr.put(attendanceToDict(r))
            return jsonResponse(
                JSONObject()
                    .put("session_id", sessionId)
                    .put("session", db.getSession(sessionId)?.let { sessionToDict(it) } ?: JSONObject.NULL)
                    .put("records", arr)
                    .toString()
            )
        }
        // Python: invalid date string falls back to today.
        val checkDate = validDateOrNull(dateStr)
            ?: SimpleDateFormat("yyyy-MM-dd", Locale.US).format(Date())
        val records = db.listAttendanceByDate(checkDate)
        val arr = JSONArray()
        for (r in records) arr.put(attendanceToDict(r))
        return jsonResponse(
            JSONObject()
                .put("date", checkDate)
                .put("records", arr)
                .toString()
        )
    }

    private fun apiUpdateAttendance(recordId: Int, session: IHTTPSession): Response {
        val body = readJsonBody(session)
        val status = body.optString("status").takeIf { it.isNotBlank() }
            ?: return jsonError(Response.Status.BAD_REQUEST, "status is required")
        val score = if (body.has("engagement_score") && !body.isNull("engagement_score")) {
            try { body.getDouble("engagement_score") } catch (_: Throwable) { null }
        } else null
        val success = db.updateAttendanceStatus(recordId, status, score)
        return jsonResponse(
            JSONObject()
                .put("status", if (success) "success" else "not_found")
                .put("message", "Updated attendance record #$recordId to $status")
                .toString()
        )
    }

    private fun apiManualMark(session: IHTTPSession): Response {
        val body = readJsonBody(session)
        val name = body.optString("student_name").trim()
        if (name.isEmpty()) return jsonError(Response.Status.BAD_REQUEST, "student_name is required")
        var sessionId = body.optString("session_id").takeIf { it.isNotBlank() }
        if (sessionId == null) {
            sessionId = db.getActiveSession()?.get("session_id")?.toString()
        }
        if (sessionId == null) return jsonError(Response.Status.BAD_REQUEST, "No active session found")
        val status = body.optString("status").takeIf { it.isNotBlank() } ?: "Present"
        val score = try { body.optDouble("engagement_score", 100.0) } catch (_: Throwable) { 100.0 }
        val (success, msg) = db.manualMark(name, sessionId, status, score)
        return jsonResponse(
            JSONObject()
                .put("status", if (success) "success" else "error")
                .put("message", msg)
                .toString()
        )
    }

    private fun apiDeleteAttendance(recordId: Int): Response {
        val success = db.deleteAttendance(recordId)
        return jsonResponse(
            JSONObject().put("status", if (success) "success" else "not_found").toString()
        )
    }

    // ---------------- engagement ----------------

    private fun apiEngagement(): Response {
        return jsonResponse(trackedStudentsJson().toString())
    }

    private fun trackedStudentsJson(): JSONObject {
        val obj = JSONObject()
        if (!engine.isRunning.get()) return obj
        for ((name, m) in engine.trackedStudents) {
            obj.put(name, mapToJsonObject(m.toDict()))
        }
        return obj
    }

    // ---------------- students ----------------

    private fun apiListStudents(): Response {
        val arr = JSONArray()
        for (s in db.listStudents()) {
            arr.put(
                JSONObject()
                    .put("id", s["id"] ?: JSONObject.NULL)
                    .put("student_id", s["student_id"] ?: "")
                    .put("name", s["name"] ?: "")
                    .put("email", s["email"] ?: JSONObject.NULL)
                    .put("department", s["department"] ?: JSONObject.NULL)
            )
        }
        return jsonResponse(JSONObject().put("students", arr).toString())
    }

    private fun apiAddStudent(session: IHTTPSession): Response {
        val body = readJsonBody(session)
        val name = body.optString("name").trim()
        if (name.isEmpty()) return jsonError(Response.Status.BAD_REQUEST, "Name is required")
        val studentId = body.optString("student_id").takeIf { it.isNotBlank() }
            ?: name.lowercase().replace(' ', '_')
        val rowId = db.addStudent(
            studentId, name,
            body.optString("email").takeIf { it.isNotBlank() },
            body.optString("department").takeIf { it.isNotBlank() }
        )
        return if (rowId >= 0) {
            jsonResponse(
                JSONObject().put("status", "success").put("id", rowId).toString()
            )
        } else {
            jsonError(Response.Status.INTERNAL_ERROR, "Failed to add student")
        }
    }

    private fun apiDeleteStudent(studentId: String): Response {
        val success = db.deleteStudent(studentId)
        return jsonResponse(
            JSONObject().put("status", if (success) "success" else "not_found").toString()
        )
    }

    /** PATCH /api/students/{id} — update editable details (name/email/department). */
    private fun apiUpdateStudent(studentId: String, session: IHTTPSession): Response {
        val row = db.getStudent(studentId)
            ?: return jsonError(Response.Status.NOT_FOUND, "Student not found")
        val body = readJsonBody(session)
        val oldName = row["name"]?.toString() ?: studentId
        val name = if (body.has("name")) body.optString("name").trim() else oldName
        if (name.isEmpty()) return jsonError(Response.Status.BAD_REQUEST, "Name cannot be empty")
        val email = if (body.has("email")) body.optString("email").ifBlank { null }
            else row["email"]?.toString()
        val dept = if (body.has("department")) body.optString("department").ifBlank { null }
            else row["department"]?.toString()

        if (!db.updateStudent(studentId, name, email, dept)) {
            return jsonError(Response.Status.INTERNAL_ERROR, "Update failed")
        }

        var reencoded = false
        if (oldName != name) {
            // Photo folder follows the name (register convention) — rename it
            // and refresh the gallery label (attendance history keeps old names).
            val base = File(appContext.filesDir, "dataset")
            val oldDir = File(base, oldName)
            val newDir = File(base, name)
            if (oldDir.isDirectory && !newDir.exists()) oldDir.renameTo(newDir)
            val photos = listPhotoFiles(if (newDir.isDirectory) newDir else oldDir)
                .mapNotNull { decodeBitmap(it) }
            if (photos.isNotEmpty()) {
                engine.reregisterStudent(studentId, name, photos)
                photos.forEach { it.recycle() }
                reencoded = true
            }
        }
        return jsonResponse(
            JSONObject().put("status", "success").put("name", name)
                .put("reencoded", reencoded).toString()
        )
    }

    // ---------------- student reference photos ----------------

    /**
     * Photo folder for a student: dataset/[name] (register convention),
     * falling back to dataset/[student_id]. The returned dir may not exist
     * yet (POST creates it).
     */
    private fun studentPhotoDir(studentId: String): File? {
        val row = db.getStudent(studentId) ?: return null
        val name = row["name"]?.toString() ?: studentId
        val base = File(appContext.filesDir, "dataset")
        val byName = File(base, name)
        if (byName.isDirectory) return byName
        val byId = File(base, studentId)
        if (byId.isDirectory) return byId
        return byName
    }

    private fun listPhotoFiles(dir: File): List<File> =
        (dir.listFiles { f ->
            f.isFile && (f.extension.equals("jpg", true) || f.extension.equals("jpeg", true) || f.extension.equals("png", true))
        } ?: emptyArray()).sortedBy { it.name }

    /** GET /api/students/{id}/photos — reference photo list. */
    private fun apiListStudentPhotos(studentId: String): Response {
        val dir = studentPhotoDir(studentId)
            ?: return jsonError(Response.Status.NOT_FOUND, "Student not found")
        val files = listPhotoFiles(dir)
        val arr = JSONArray()
        files.forEachIndexed { i, f ->
            arr.put(
                JSONObject()
                    .put("index", i)
                    .put("name", f.name)
                    .put("url", "/api/students/$studentId/photos/$i")
            )
        }
        return jsonResponse(
            JSONObject().put("photos", arr).put("count", files.size).toString()
        )
    }

    /** GET /api/students/{id}/photos/{index} — one reference photo (JPEG/PNG). */
    private fun apiGetStudentPhoto(studentId: String, index: Int): Response {
        val dir = studentPhotoDir(studentId)
            ?: return jsonError(Response.Status.NOT_FOUND, "Student not found")
        val files = listPhotoFiles(dir)
        if (index < 0 || index >= files.size) {
            return jsonError(Response.Status.NOT_FOUND, "Photo not found")
        }
        val f = files[index]
        val mime = when {
            f.extension.equals("png", true) -> "image/png"
            else -> "image/jpeg"
        }
        return try {
            val resp = NanoHTTPD.newFixedLengthResponse(
                Response.Status.OK, mime, f.inputStream(), f.length()
            )
            resp.addHeader("Cache-Control", "no-cache")
            resp
        } catch (t: Throwable) {
            jsonError(Response.Status.INTERNAL_ERROR, t.message ?: "Read failed")
        }
    }

    /**
     * POST /api/students/{id}/photos — add base64 images and re-encode the
     * student's gallery entry from ALL photos (replace semantics).
     */
    private fun apiAddStudentPhotos(studentId: String, session: IHTTPSession): Response {
        val row = db.getStudent(studentId)
            ?: return jsonError(Response.Status.NOT_FOUND, "Student not found")
        val name = row["name"]?.toString() ?: studentId
        val body = readJsonBody(session)
        val images = body.optJSONArray("images")
        if (images == null || images.length() == 0) {
            return jsonError(Response.Status.BAD_REQUEST, "images array is required")
        }
        return try {
            val dir = studentPhotoDir(studentId) ?: return jsonError(Response.Status.NOT_FOUND, "Student not found")
            dir.mkdirs()
            val ts = SimpleDateFormat("yyyyMMdd_HHmmss", Locale.US).format(Date())
            var added = 0
            for (i in 0 until images.length()) {
                val raw = stripDataUrlPrefix(images.optString(i) ?: "") ?: continue
                val bytes = try {
                    Base64.decode(raw, Base64.DEFAULT)
                } catch (_: Throwable) { continue }
                val bmp = BitmapFactory.decodeByteArray(bytes, 0, bytes.size) ?: continue
                val out = File(dir, "web_${ts}_${System.nanoTime() % 100000}_$added.jpg")
                if (out.outputStream().use { bmp.compress(Bitmap.CompressFormat.JPEG, 92, it) }) added++
                bmp.recycle()
            }
            if (added == 0) {
                return jsonError(Response.Status.BAD_REQUEST, "No valid face images received")
            }
            val encoded = reencodeStudentPhotos(studentId, name)
            val count = listPhotoFiles(dir).size
            jsonResponse(
                JSONObject()
                    .put("status", "success")
                    .put("added", added)
                    .put("photo_count", count)
                    .put("encoded", encoded)
                    .toString()
            )
        } catch (t: Throwable) {
            jsonError(Response.Status.INTERNAL_ERROR, t.message ?: "Add photos failed")
        }
    }

    /** DELETE /api/students/{id}/photos/{index} — remove one photo + re-encode. */
    private fun apiDeleteStudentPhoto(studentId: String, index: Int): Response {
        val row = db.getStudent(studentId)
            ?: return jsonError(Response.Status.NOT_FOUND, "Student not found")
        val name = row["name"]?.toString() ?: studentId
        val dir = studentPhotoDir(studentId)
            ?: return jsonError(Response.Status.NOT_FOUND, "Student not found")
        val files = listPhotoFiles(dir)
        if (index < 0 || index >= files.size) {
            return jsonError(Response.Status.NOT_FOUND, "Photo not found")
        }
        return try {
            files[index].delete()
            val encoded = reencodeStudentPhotos(studentId, name)
            val count = listPhotoFiles(dir).size
            jsonResponse(
                JSONObject()
                    .put("status", "success")
                    .put("remaining", count)
                    .put("encoded", encoded)
                    .toString()
            )
        } catch (t: Throwable) {
            jsonError(Response.Status.INTERNAL_ERROR, t.message ?: "Delete failed")
        }
    }

    /** Rebuild the gallery entry from folder contents (replace semantics). */
    private fun reencodeStudentPhotos(studentId: String, name: String): Boolean {
        val dir = studentPhotoDir(studentId) ?: return false
        val photos = listPhotoFiles(dir).mapNotNull { decodeBitmap(it) }
        return try {
            engine.reregisterStudent(studentId, name, photos) > 0
        } finally {
            photos.forEach { it.recycle() }
        }
    }

    // ---------------- dataset encode + register ----------------

    /** POST /api/encode — re-encode every dataset image (filesDir/dataset/[name]/[star].jpg). */
    private fun apiEncodeDataset(): Response {
        return try {
            val datasetDir = File(appContext.filesDir, "dataset")
            var count = 0
            val dirs = datasetDir.listFiles { f -> f.isDirectory } ?: emptyArray()
            for (dir in dirs) {
                val images = ArrayList<Bitmap>()
                val files = dir.listFiles { f ->
                    f.isFile && (f.extension.equals("jpg", true) || f.extension.equals("jpeg", true) || f.extension.equals("png", true))
                } ?: emptyArray()
                for (f in files) {
                    decodeBitmap(f)?.let { images.add(it) }
                }
                if (images.isNotEmpty()) {
                    engine.registerStudent(dir.name, dir.name, images)
                    images.forEach { it.recycle() }
                    count++
                }
            }
            jsonResponse(
                JSONObject()
                    .put("status", "success")
                    .put("message", "Encoded $count students")
                    .toString()
            )
        } catch (t: Throwable) {
            jsonError(Response.Status.INTERNAL_ERROR, (t.message ?: "Encoding failed"))
        }
    }

    /**
     * POST /api/register-student — full registration: save decoded images to
     * filesDir/dataset/[name]/ FIRST (so re-encode works), then live-encode.
     */
    private fun apiRegisterStudent(session: IHTTPSession): Response {
        val body = readJsonBody(session)
        val name = body.optString("name").trim()
        if (name.isEmpty()) return jsonError(Response.Status.BAD_REQUEST, "Name is required")
        val images = body.optJSONArray("images")
        if (images == null || images.length() == 0) {
            return jsonError(Response.Status.BAD_REQUEST, "At least one face image is required")
        }
        return try {
            val studentDir = File(File(appContext.filesDir, "dataset"), name)
            studentDir.mkdirs()
            val ts = SimpleDateFormat("yyyyMMdd_HHmmss", Locale.US).format(Date())
            val bitmaps = ArrayList<Bitmap>()
            val savedFiles = ArrayList<File>()
            for (i in 0 until images.length()) {
                val b64 = images.optString(i) ?: continue
                val raw = stripDataUrlPrefix(b64) ?: continue
                val bytes = try { Base64.decode(raw, Base64.DEFAULT) } catch (_: Throwable) { continue }
                val bmp = BitmapFactory.decodeByteArray(bytes, 0, bytes.size) ?: continue
                val out = File(studentDir, "web_${ts}_$i.jpg")
                if (out.outputStream().use { bmp.compress(Bitmap.CompressFormat.JPEG, 92, it) }) {
                    savedFiles.add(out)
                    bitmaps.add(bmp)
                } else {
                    bmp.recycle()
                }
            }
            if (bitmaps.isEmpty()) {
                return jsonError(Response.Status.BAD_REQUEST, "No valid face images received")
            }
            val studentId = body.optString("student_id").takeIf { it.isNotBlank() } ?: name.lowercase().replace(' ', '_')
            db.addStudent(
                studentId, name,
                body.optString("email").takeIf { it.isNotBlank() },
                body.optString("department").takeIf { it.isNotBlank() }
            )
            val encodedCount = engine.registerStudent(studentId, name, bitmaps)
            bitmaps.forEach { it.recycle() }
            val encoded = encodedCount > 0
            jsonResponse(
                JSONObject()
                    .put("status", "success")
                    .put(
                        "message",
                        "Registered $name: ${bitmaps.size} images saved, " +
                            (if (encoded) "face encoded" else "encoding failed - run Re-encode")
                    )
                    .toString()
            )
        } catch (t: Throwable) {
            jsonError(Response.Status.INTERNAL_ERROR, (t.message ?: "Registration failed"))
        }
    }

    // ---------------- unknown faces queue ----------------

    private fun apiUnknownFaces(session: IHTTPSession): Response {
        val handler = queueHandler ?: return queueUnavailable()
        val cluster = queryParam(session, "cluster") == "true"
        return mapResponse(handler.list(cluster))
    }

    private fun apiClusterify(): Response {
        val handler = queueHandler ?: return queueUnavailable()
        return mapResponse(handler.clusterify())
    }

    private fun apiClearUnknownQueue(): Response {
        val handler = queueHandler ?: return queueUnavailable()
        return mapResponse(handler.clear())
    }

    private fun apiRegisterUnknown(session: IHTTPSession, cluster: Boolean): Response {
        val handler = queueHandler ?: return queueUnavailable()
        val body = readJsonBody(session)
        val name = body.optString("name").trim()
        if (name.isEmpty()) return jsonError(Response.Status.BAD_REQUEST, "Student name is required")
        val filenames = collectFilenames(body)
        if (filenames.isEmpty()) {
            return jsonError(Response.Status.BAD_REQUEST, "At least one face image filename is required")
        }
        val studentId = body.optString("student_id").takeIf { it.isNotBlank() }
            ?: "STU_" + name.uppercase().replace(' ', '_')
        val dept = body.optString("department").takeIf { it.isNotBlank() } ?: "Computer Science"
        val email = body.optString("email").takeIf { it.isNotBlank() }
        return mapResponse(
            if (cluster) handler.registerCluster(filenames, name, studentId, dept, email)
            else handler.register(filenames.first(), name, studentId, dept, email)
        )
    }

    private fun apiIgnoreUnknown(session: IHTTPSession): Response {
        val handler = queueHandler ?: return queueUnavailable()
        val body = readJsonBody(session)
        val filenames = collectFilenames(body)
        if (filenames.isEmpty()) {
            return jsonError(Response.Status.BAD_REQUEST, "filename or filenames required")
        }
        return mapResponse(handler.ignore(filenames))
    }

    private fun collectFilenames(body: JSONObject): List<String> {
        val out = ArrayList<String>()
        body.optJSONArray("filenames")?.let { arr ->
            for (i in 0 until arr.length()) arr.optString(i)?.let { out.add(it) }
        }
        if (out.isEmpty()) body.optString("filename").takeIf { it.isNotBlank() }?.let { out.add(it) }
        return out
    }

    private fun queueUnavailable(): Response =
        jsonError(Response.Status.INTERNAL_ERROR, "queue unavailable")

    // ---------------- CSV export + batch ----------------

    private fun apiExportCsv(session: IHTTPSession): Response {
        val sessionId = queryParam(session, "session_id")
        val dateStr = queryParam(session, "date")
        val records: List<Map<String, Any?>>
        var filename: String
        if (sessionId != null) {
            records = db.listAttendance(sessionId)
            val s = db.getSession(sessionId)
            filename = if (s != null) {
                val clean = "${s["course"]}_${s["title"]}".replace(' ', '_').replace('/', '_')
                "attendance_${clean}_${s["date"]}.csv"
            } else {
                "attendance_$sessionId.csv"
            }
        } else {
            // Python: invalid date string falls back to today.
            val checkDate = validDateOrNull(dateStr)
                ?: SimpleDateFormat("yyyy-MM-dd", Locale.US).format(Date())
            records = db.listAttendanceByDate(checkDate)
            filename = "attendance_$checkDate.csv"
        }
        val sb = StringBuilder()
        sb.append("Student Name,Session ID,Session Title,Course,Date,Time,Engagement Score (%),Status\n")
        for (r in records) {
            sb.append(csvField(r["student_name"]?.toString() ?: "")).append(',')
            sb.append(csvField(r["session_id"]?.toString() ?: "")).append(',')
            sb.append(csvField(r["session_title"]?.toString() ?: "")).append(',')
            sb.append(csvField(r["course"]?.toString() ?: "")).append(',')
            sb.append(csvField(r["date"]?.toString() ?: "")).append(',')
            sb.append(csvField(r["time"]?.toString() ?: "")).append(',')
            sb.append(csvField(String.format(Locale.US, "%.1f", toDouble(r["engagement_score"])))).append(',')
            sb.append(csvField(r["status"]?.toString() ?: "Present")).append('\n')
        }
        val resp = newFixedLengthResponse(Response.Status.OK, MIME_CSV, sb.toString())
        resp.addHeader("Content-Disposition", "attachment; filename=$filename")
        return resp
    }

    /** CSV-quote a field when it contains a comma, quote, or newline (RFC 4180). */
    private fun csvField(v: String): String =
        if (v.contains(',') || v.contains('"') || v.contains('\n') || v.contains('\r')) {
            "\"" + v.replace("\"", "\"\"") + "\""
        } else v

    private fun apiBatchAttendance(session: IHTTPSession): Response {
        val handler = batchHandler ?: return jsonError(Response.Status.INTERNAL_ERROR, "batch handler unavailable")
        val body = readJsonBody(session)
        val rawFolder = body.optString("folder").takeIf { it.isNotBlank() }
            ?: return jsonError(Response.Status.BAD_REQUEST, "folder is required")
        // Path resolution on-device: relative names (e.g. "batch_test" or
        // "Pictures/classroom") resolve against the app's own storage roots —
        // scoped storage blocks arbitrary absolute paths. Absolute paths that
        // exist are still honored (PC backend parity).
        var resolved: File = File(rawFolder)
        if (!resolved.isDirectory) {
            val candidates = listOf(
                File(appContext.getExternalFilesDir(null), rawFolder),
                File(appContext.filesDir, rawFolder),
                File("/sdcard/${rawFolder.trimStart('/')}")
            )
            resolved = candidates.firstOrNull { it.isDirectory } ?: resolved
        }
        return mapResponse(handler.run(resolved.absolutePath))
    }

    // ---------------- tuning ----------------

    private fun apiTuningGet(): Response {
        return jsonResponse(
            JSONObject()
                .put("success", true)
                .put("min_face_size", engine.minFaceSize)
                .put("min_detection_confidence", (engine.minDetectionConfidence * 100).toInt())
                .put("recognition_threshold", (engine.recognitionThreshold * 100).toInt())
                .put("batch_size", 8)
                .put("cache_ttl_seconds", 3.0)
                .put("adaptive_skip_enabled", false)
                .toString()
        )
    }

    private fun apiTuningPost(session: IHTTPSession): Response {
        val body = readJsonBody(session)
        if (body.has("min_face_size")) {
            val v = body.optInt("min_face_size", -1)
            if (v in 10..400) engine.minFaceSize = v
        }
        if (body.has("min_detection_confidence")) {
            val v = body.optDouble("min_detection_confidence", Double.NaN)
            if (!v.isNaN()) {
                val conf = if (v > 1.0) v / 100.0 else v
                if (conf in 0.1..0.99) engine.minDetectionConfidence = conf.toFloat()
            }
        }
        if (body.has("recognition_threshold")) {
            val v = body.optDouble("recognition_threshold", Double.NaN)
            if (!v.isNaN()) {
                val t = if (v > 1.0) v / 100.0 else v
                if (t in 0.1..1.0) engine.recognitionThreshold = t
            }
        }
        return jsonResponse(
            JSONObject()
                .put("success", true)
                .put("message", "Tuning updated")
                .put("min_face_size", engine.minFaceSize)
                .put("min_detection_confidence", (engine.minDetectionConfidence * 100).toInt())
                .put("recognition_threshold", (engine.recognitionThreshold * 100).toInt())
                .toString()
        )
    }

    /** GET /video_feed — multipart/x-mixed-replace stream of engine snapshots (~25 fps). */
    private fun videoFeedResponse(): Response {
        val boundary = "frame"
        val stream = object : InputStream() {
            private var buffer: ByteArray = ByteArray(0)
            private var pos = 0
            private var lastFrameMs = 0L

            /** One multipart frame: --frame\r\nContent-Type: image/jpeg\r\n\r\n<jpeg>\r\n */
            private fun nextChunk(): ByteArray {
                // Pace to ~25 fps (Python: time.sleep(0.04) per yielded frame).
                val now = System.currentTimeMillis()
                val wait = 40 - (now - lastFrameMs)
                if (wait > 0) {
                    try { Thread.sleep(wait) } catch (_: InterruptedException) { }
                }
                lastFrameMs = System.currentTimeMillis()
                val jpeg = engine.snapshotJpeg() ?: blackPlaceholderJpeg()
                val head = ("--$boundary\r\nContent-Type: image/jpeg\r\n" +
                    "Content-Length: ${jpeg.size}\r\n\r\n").toByteArray(Charsets.ISO_8859_1)
                return head + jpeg + "\r\n".toByteArray(Charsets.ISO_8859_1)
            }

            private fun fill() {
                buffer = nextChunk()
                pos = 0
            }

            override fun read(): Int {
                if (pos >= buffer.size) fill()
                val b = buffer[pos]
                pos++
                return b.toInt() and 0xFF
            }

            override fun read(b: ByteArray, off: Int, len: Int): Int {
                if (pos >= buffer.size) fill()
                val n = minOf(len, buffer.size - pos)
                System.arraycopy(buffer, pos, b, off, n)
                pos += n
                return n
            }
        }
        return newChunkedResponse(
            Response.Status.OK, "multipart/x-mixed-replace; boundary=$boundary", stream
        )
    }

    /** Black "Camera stopped / starting" placeholder frame (Python generate_video_stream parity). */
    private fun blackPlaceholderJpeg(): ByteArray {
        val bmp = Bitmap.createBitmap(640, 480, Bitmap.Config.RGB_565)
        try {
            val canvas = android.graphics.Canvas(bmp)
            canvas.drawColor(android.graphics.Color.BLACK)
            val paint = android.graphics.Paint().apply {
                color = android.graphics.Color.WHITE
                textSize = 28f
                isAntiAlias = true
            }
            val msg = if (engine.isRunning.get()) "Camera starting..." else "Camera stopped"
            val sub = if (engine.isRunning.get()) "AI models warming up"
                      else "Click Start in Dashboard or Live Camera"
            canvas.drawText(msg, 160f, 230f, paint)
            paint.color = android.graphics.Color.GRAY
            paint.textSize = 22f
            canvas.drawText(sub, 120f, 280f, paint)
            java.io.ByteArrayOutputStream().use { out ->
                bmp.compress(Bitmap.CompressFormat.JPEG, 80, out)
                return out.toByteArray()
            }
        } finally {
            bmp.recycle()
        }
    }

    // ---------------- SSE ----------------

    /**
     * GET /api/stream/events — SSE telemetry every 500 ms. Starts from
     * [Engine.ssePayload] (engine-derived live fields) and overlays the
     * DB-derived fields (active_session, present/total counts, average
     * engagement from attendance rows) cached for 1.5 s to avoid hammering
     * SQLite — mirroring the Flask event_stream() 1.5 s cache.
     */
    private fun sseStream(session: IHTTPSession): Response {
        val pipe = PipedOutputStream()
        val input = PipedInputStream(pipe, 1 shl 16)
        Thread {
            try {
                val writer = pipe.bufferedWriter(Charsets.UTF_8)
                var lastDbTime = 0L
                var cachedActive: Map<String, Any?>? = null
                var cachedPresent = 0
                var cachedAvgEng = 0.0
                var cachedTotal = 0
                var cachedAbsent = 0
                var cachedPct = 0.0
                while (true) {
                    try {
                        val now = System.currentTimeMillis()
                        if (now - lastDbTime > SSE_CACHE_TTL_MS) {
                            try {
                                cachedActive = db.getActiveSession()
                                val sid = cachedActive?.get("session_id")?.toString()
                                cachedPresent = db.presentCount(sid)
                                cachedTotal = db.totalStudents()
                                cachedAbsent = maxOf(0, cachedTotal - cachedPresent)
                                cachedPct = if (cachedTotal > 0) cachedPresent * 100.0 / cachedTotal else 0.0
                                cachedAvgEng = if (cachedPresent > 0) {
                                    db.listAttendance(sid).map { toDouble(it["engagement_score"]) }.average()
                                } else 0.0
                                lastDbTime = now
                            } catch (t: Throwable) {
                                Log.w(TAG, "SSE DB query error", t)
                            }
                        }
                        val payload = mapToJsonObject(engine.ssePayload()).let { base ->
                            base.put("active_session", cachedActive?.let { sessionToDict(it) } ?: JSONObject.NULL)
                                .put("active_session_id", cachedActive?.get("session_id") ?: JSONObject.NULL)
                                .put("present_count", cachedPresent)
                                .put("total_students", cachedTotal)
                                .put("absent_count", cachedAbsent)
                                .put("attendance_percentage", round1(cachedPct))
                                .put("average_engagement", round1(cachedAvgEng))
                                .put("timestamp", SimpleDateFormat("HH:mm:ss", Locale.US).format(Date()))
                        }
                        writer.write("data: $payload\n\n")
                        writer.flush()
                    } catch (e: IOException) {
                        break  // client disconnected
                    }
                    Thread.sleep(500)
                }
            } catch (_: InterruptedException) {
                Thread.currentThread().interrupt()
            } finally {
                try { pipe.close() } catch (_: Throwable) {}
            }
        }.apply { isDaemon = true; name = "sse-stream-${UUID.randomUUID()}" }.start()

        val resp = newChunkedResponse(Response.Status.OK, "text/event-stream", input)
        resp.addHeader("Cache-Control", "no-cache")
        resp.addHeader("Connection", "keep-alive")
        resp.addHeader("X-Accel-Buffering", "no")
        resp.addHeader("Access-Control-Allow-Origin", "*")
        return resp
    }

    // ---------------- static SPA + files ----------------

    private fun routeGet(session: IHTTPSession, uri: String): Response {
        if (uri == "/video_feed") return videoFeedResponse()
        // Deterministic single-frame endpoint — used by the SPA in the native
        // shell as a polling fallback (some WebViews do not render MJPEG).
        if (uri == "/video_snapshot.jpg") {
            val jpeg = engine.snapshotJpeg()
                ?: return newFixedLengthResponse(Response.Status.SERVICE_UNAVAILABLE, MIME_JSON,
                    """{"error": "Engine not running"}""")
            return newFixedLengthResponse(Response.Status.OK, MIME_JPG,
                ByteArrayInputStream(jpeg), jpeg.size.toLong())
        }
        if (uri == "/exports/" || uri.startsWith("/exports/")) {
            return serveFileFromDir(File(appContext.filesDir, "exports"), uri.removePrefix("/exports/"), MIME_CSV)
        }
        if (uri.startsWith("/unknown/")) {
            return serveFileFromDir(File(appContext.filesDir, "unknown"), uri.removePrefix("/unknown/"), MIME_JPG)
        }
        return serveStatic(uri)
    }

    /** Serve the React SPA from assets/public/ with index.html fallback. */
    private fun serveStatic(uri: String): Response {
        val clean = uri.trim('/').takeIf { it.isNotEmpty() } ?: "index.html"
        val asset = "public/$clean"
        val mime = mimeFor(clean)
        try {
            appContext.assets.open(asset).use { stream ->
                val bytes = stream.readBytes()
                return newFixedLengthResponse(Response.Status.OK, mime, ByteArrayInputStream(bytes), bytes.size.toLong())
            }
        } catch (_: IOException) {
            // fall through to SPA fallback
        } catch (_: Throwable) {
        }
        // SPA fallback: extension-less paths → index.html; real missing files → 404
        return if (clean.contains('.')) {
            jsonError(Response.Status.NOT_FOUND, "Not found: $uri")
        } else {
            serveAssetIndex()
        }
    }

    private fun serveAssetIndex(): Response {
        try {
            appContext.assets.open("public/index.html").use { stream ->
                val bytes = stream.readBytes()
                return newFixedLengthResponse(
                    Response.Status.OK, MIME_HTML, ByteArrayInputStream(bytes), bytes.size.toLong()
                )
            }
        } catch (t: Throwable) {
            return newFixedLengthResponse(
                Response.Status.NOT_FOUND, MIME_HTML,
                "<html><body><h1>Count-On-Me web app not bundled</h1>" +
                    "<p>Run npx cap sync to copy the React build into assets/public.</p></body></html>"
            )
        }
    }

    /** Serve a single file from a filesDir subdirectory (exports/unknown downloads). */
    private fun serveFileFromDir(dir: File, name: String, mime: String): Response {
        val safe = name.substringAfterLast('/')
        val f = File(dir, safe)
        if (!f.isFile) return jsonError(Response.Status.NOT_FOUND, "File not found: $name")
        return try {
            newFixedLengthResponse(Response.Status.OK, mime, f.inputStream(), f.length())
        } catch (t: Throwable) {
            jsonError(Response.Status.NOT_FOUND, "File not found: $name")
        }
    }

    private fun mimeFor(name: String): String = when (name.substringAfterLast('.', "").lowercase()) {
        "html", "htm" -> MIME_HTML
        "js", "mjs" -> MIME_JS
        "css" -> MIME_CSS
        "svg" -> MIME_SVG
        "png" -> MIME_PNG
        "jpg", "jpeg" -> MIME_JPG
        "woff2" -> MIME_WOFF2
        "json" -> MIME_JSON
        "ico" -> MIME_ICON
        "csv" -> MIME_CSV
        else -> "application/octet-stream"
    }

    // ---------------- JSON helpers ----------------

    private fun jsonResponse(body: String): Response =
        newFixedLengthResponse(Response.Status.OK, MIME_JSON, body)

    private fun jsonError(status: Response.Status, message: String): Response =
        newFixedLengthResponse(status, MIME_JSON, JSONObject().put("error", message).toString())

    private fun mapResponse(map: Map<String, Any?>): Response {
        val status = if ((map["error"] as? String) != null) Response.Status.INTERNAL_ERROR
                    else Response.Status.OK
        return newFixedLengthResponse(status, MIME_JSON, mapToJsonObject(map).toString())
    }

    // ---------------- dict shaping (Python to_dict parity) ----------------

    private fun sessionToDict(s: Map<String, Any?>): JSONObject {
        return JSONObject()
            .put("id", s["id"] ?: JSONObject.NULL)
            .put("session_id", s["session_id"] ?: "")
            .put("title", s["title"] ?: "")
            .put("course", s["course"] ?: s["title"] ?: "")
            .put("date", s["date"]?.toString() ?: "")
            .put("start_time", s["start_time"] ?: "")
            .put("end_time", s["end_time"] ?: "")
            .put("room", s["room"] ?: "")
            .put("is_active", (s["is_active"]?.toString() == "1") || (s["is_active"] as? Boolean == true))
            .put("created_at", s["created_at"]?.toString() ?: "")
            .put("present_count", toInt(s["present_count"]))
            .put("avg_engagement", round1(toDouble(s["avg_engagement"])))
    }

    private fun attendanceToDict(r: Map<String, Any?>): JSONObject {
        return JSONObject()
            .put("id", r["id"] ?: JSONObject.NULL)
            .put("name", r["student_name"] ?: "")
            .put("student_name", r["student_name"] ?: "")
            .put("student_id", r["student_id"] ?: JSONObject.NULL)
            .put("session_id", r["session_id"] ?: "")
            .put("session_title", r["session_title"] ?: r["session_id"] ?: "")
            .put("course", r["course"] ?: "")
            .put("date", r["date"]?.toString() ?: "")
            .put("time", r["time"] ?: "")
            .put("engagement_score", round1(toDouble(r["engagement_score"])))
            .put("status", r["status"] ?: "Present")
            .put("created_at", r["created_at"]?.toString() ?: "")
    }

    private fun mapToJsonObject(m: Map<*, *>): JSONObject {
        val o = JSONObject()
        for ((k, v) in m) {
            o.put(k.toString(), when (v) {
                null -> JSONObject.NULL
                is Map<*, *> -> mapToJsonObject(v)
                is List<*> -> listToJsonArray(v)
                is Array<*> -> listToJsonArray(v.toList())
                else -> v
            })
        }
        return o
    }

    private fun listToJsonArray(l: List<*>): JSONArray {
        val a = JSONArray()
        for (v in l) a.put(when (v) {
            null -> JSONObject.NULL
            is Map<*, *> -> mapToJsonObject(v)
            is List<*> -> listToJsonArray(v)
            else -> v
        })
        return a
    }

    private fun toDouble(v: Any?): Double = when (v) {
        null -> 0.0
        is Double -> v
        is Long -> v.toDouble()
        is Int -> v.toDouble()
        is Float -> v.toDouble()
        is Number -> v.toDouble()
        is String -> v.toDoubleOrNull() ?: 0.0
        else -> 0.0
    }

    private fun toInt(v: Any?): Int = when (v) {
        null -> 0
        is Int -> v
        is Long -> v.toInt()
        is Number -> v.toInt()
        is String -> v.toIntOrNull() ?: 0
        else -> 0
    }

    private fun round1(v: Double): Double = kotlin.math.round(v * 10.0) / 10.0

    private fun stripDataUrlPrefix(s: String): String? {
        val t = s.trim()
        return if (t.startsWith("data:")) {
            val idx = t.indexOf(',')
            if (idx < 0) null else t.substring(idx + 1)
        } else t
    }

    private fun decodeBitmap(f: File): Bitmap? = try {
        BitmapFactory.decodeFile(f.absolutePath)
    } catch (_: Throwable) {
        null
    }
}

/**
 * Glue between the engine and the server layer:
 *  - [Engine.DbBridge] delegates to [Database]
 *  - [Engine.UnknownQueueBridge] persists unknown face crops to
 *    filesDir/unknown/ as `yyyy-MM-dd_HH-mm-ss_t_[trackKey].jpg`, capped at
 *    [Engine.UNKNOWN_MAX_ENTRIES] entries (oldest evicted first).
 */
class EngineHost(
    private val appContext: Context,
    private val engine: Engine?,
    private val db: Database
) : Engine.DbBridge, Engine.UnknownQueueBridge {

    constructor(appContext: Context, db: Database) : this(appContext, null, db)

    companion object {
        private const val TAG = "EngineHost"
        private val TS_FMT = SimpleDateFormat("yyyy-MM-dd_HH-mm-ss", Locale.US)
    }

    override fun markAttendance(name: String, engagementScore: Double, sessionId: String?): Boolean =
        db.markAttendance(name, engagementScore, sessionId)

    override fun activeSessionId(): String? = db.activeSessionId()

    override fun writeEngagementScore(name: String, score: Double) =
        db.writeEngagementScore(name, score)

    override fun totalStudents(): Int = db.totalStudents()

    override fun presentCount(sessionId: String?): Int = db.presentCount(sessionId)

    override fun saveUnknownFace(jpeg: ByteArray, trackKey: String) {
        try {
            val dir = File(appContext.filesDir, "unknown")
            dir.mkdirs()
            val name = "${TS_FMT.format(Date())}_t_$trackKey.jpg"
            File(dir, name).writeBytes(jpeg)
            // Cap the queue at 50 entries — delete oldest first (mtime order).
            val files = dir.listFiles() ?: return
            if (files.size > Engine.UNKNOWN_MAX_ENTRIES) {
                files.sortedBy { it.lastModified() }
                    .take(files.size - Engine.UNKNOWN_MAX_ENTRIES)
                    .forEach { it.delete() }
            }
        } catch (t: Throwable) {
            Log.e(TAG, "saveUnknownFace failed", t)
        }
    }
}