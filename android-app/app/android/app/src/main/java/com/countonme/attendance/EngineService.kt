package com.countonme.attendance

import android.app.Notification
import android.app.NotificationChannel
import android.app.NotificationManager
import android.app.Service
import android.content.Context
import android.content.Intent
import android.os.Build
import android.os.IBinder
import android.util.Log

/**
 * Foreground service that keeps the attendance engine (camera + recognition +
 * embedded server) alive while the user switches apps.
 *
 * Aggressive OEM freezers (ColorOS/Oplus Hans, MIUI, etc.) suspend backgrounded
 * processes within seconds — which starves the CameraX analyzer, disconnects
 * the camera HAL and freezes the local server. A foreground service with a
 * persistent notification opts the process out of that treatment.
 */
class EngineService : Service() {

    companion object {
        private const val TAG = "EngineService"
        private const val CHANNEL_ID = "count_on_me_engine"
        private const val NOTIF_ID = 8971

        fun start(context: Context) {
            val intent = Intent(context, EngineService::class.java)
            if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.O) {
                context.startForegroundService(intent)
            } else {
                context.startService(intent)
            }
        }

        fun stop(context: Context) {
            context.stopService(Intent(context, EngineService::class.java))
        }
    }

    override fun onBind(intent: Intent?): IBinder? = null

    override fun onCreate() {
        super.onCreate()
        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.O) {
            val nm = getSystemService(NotificationManager::class.java)
            nm.createNotificationChannel(
                NotificationChannel(CHANNEL_ID, "Attendance Engine", NotificationManager.IMPORTANCE_LOW)
                    .apply { description = "Keeps live attendance tracking running" }
            )
        }
    }

    override fun onStartCommand(intent: Intent?, flags: Int, startId: Int): Int {
        val builder = if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.O) {
            Notification.Builder(this, CHANNEL_ID)
        } else {
            @Suppress("DEPRECATION")
            Notification.Builder(this)
        }
        val notification = builder
            .setContentTitle("Count-On-Me is recording attendance")
            .setContentText("Live camera, recognition and engagement are running.")
            .setSmallIcon(android.R.drawable.ic_menu_camera)
            .setOngoing(true)
            .build()
        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.Q) {
            startForeground(NOTIF_ID, notification, android.content.pm.ServiceInfo.FOREGROUND_SERVICE_TYPE_CAMERA)
        } else {
            startForeground(NOTIF_ID, notification)
        }
        Log.i(TAG, "Engine foreground service running (camera type)")
        return START_STICKY
    }
}
