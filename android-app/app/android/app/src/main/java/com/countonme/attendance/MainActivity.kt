package com.countonme.attendance

import android.Manifest
import android.content.pm.PackageManager
import android.os.Bundle
import android.util.Log
import androidx.core.app.ActivityCompat
import androidx.core.content.ContextCompat
import com.countonme.attendance.batch.BatchProcessor
import com.countonme.attendance.batch.UnknownQueue
import com.countonme.attendance.engine.Engine
import com.countonme.attendance.plugins.SaveFilePlugin
import com.countonme.attendance.server.Database
import com.countonme.attendance.server.EngineHost
import com.countonme.attendance.server.LocalServer
import com.getcapacitor.BridgeActivity

/**
 * App entry point. Boots the whole offline stack:
 *
 *   Database -> Engine(DbBridge/UnknownQueueBridge via LocalServer's EngineHost)
 *           -> UnknownQueue + BatchProcessor -> LocalServer (127.0.0.1:8971)
 *
 * The WebView (served by Capacitor at https://localhost) talks to the local
 * server over plain HTTP — identical contract to the Flask backend it replaces.
 */
class MainActivity : BridgeActivity() {

    companion object {
        private const val TAG = "MainActivity"
        private const val REQ_CAMERA = 4201
        @Volatile var instance: MainActivity? = null
            private set
    }

    lateinit var database: Database
    lateinit var engine: Engine
    lateinit var server: LocalServer
    lateinit var queue: UnknownQueue
    lateinit var batch: BatchProcessor

    override fun onCreate(savedInstanceState: Bundle?) {
        // Local plugins must be registered BEFORE super.onCreate — the bridge
        // consumes bridgeBuilder inside super.onCreate -> load().
        registerPlugin(SaveFilePlugin::class.java)
        super.onCreate(savedInstanceState)
        instance = this

        // The live engine binds CameraX, which needs the runtime grant; also
        // pre-covers RegisterView's WebView getUserMedia.
        if (ContextCompat.checkSelfPermission(this, Manifest.permission.CAMERA)
                != PackageManager.PERMISSION_GRANTED) {
            ActivityCompat.requestPermissions(this,
                arrayOf(Manifest.permission.CAMERA), REQ_CAMERA)
        }

        try {
            database = Database(this)
            // EngineHost implements the engine's DB + unknown-queue bridges
            // (engine field unused by those bridges; nullable to break the
            // engine<->host construction cycle).
            val host = EngineHost(this, database)
            engine = Engine(this, host, host)
            queue = UnknownQueue(this, engine.mediaPipeline(), engine.embedder(), engine.storeBridge(), database)
            batch = BatchProcessor(this, engine.mediaPipeline(), engine.embedder(), engine.storeBridge(), database)
            server = LocalServer(this, this, engine, database, queue, batch)
            server.startServer()
            // Warm ML runtimes off the UI thread (server must be up first).
            Thread {
                try {
                    engine.warmup()
                    Log.i(TAG, "Engine warmup complete")
                } catch (t: Throwable) {
                    Log.e(TAG, "Engine warmup failed", t)
                }
            }.start()
        } catch (t: Throwable) {
            Log.e(TAG, "Stack boot failed", t)
        }
    }

    override fun onRequestPermissionsResult(
        requestCode: Int, permissions: Array<out String>, grantResults: IntArray
    ) {
        super.onRequestPermissionsResult(requestCode, permissions, grantResults)
        if (requestCode == REQ_CAMERA) {
            val granted = grantResults.isNotEmpty() && grantResults[0] == PackageManager.PERMISSION_GRANTED
            Log.i(TAG, "Camera permission: ${if (granted) "granted" else "DENIED"}")
        }
    }

    override fun onDestroy() {
        if (!isChangingConfigurations) {
            try { engine.shutdown() } catch (_: Throwable) {}
            try { server.stopServer() } catch (_: Throwable) {}
            instance = null
        }
        super.onDestroy()
    }
}