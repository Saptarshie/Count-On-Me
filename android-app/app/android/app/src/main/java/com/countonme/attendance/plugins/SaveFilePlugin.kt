package com.countonme.attendance.plugins

import android.app.DownloadManager
import android.content.Context
import android.net.Uri
import android.os.Environment
import com.getcapacitor.JSObject
import com.getcapacitor.Plugin
import com.getcapacitor.PluginCall
import com.getcapacitor.PluginMethod
import com.getcapacitor.annotation.CapacitorPlugin

/**
 * CSV export bridge — the Android WebView cannot handle <a download> links,
 * so the SPA calls this plugin to hand the file to the system DownloadManager
 * (which saves it into Downloads/ with a completion notification).
 */
@CapacitorPlugin(name = "SaveFile")
class SaveFilePlugin : Plugin() {

    @PluginMethod
    fun saveFile(call: PluginCall) {
        val url = call.getString("url")
            ?: return call.reject("url is required")
        val filename = call.getString("filename") ?: "export.csv"
        try {
            val request = DownloadManager.Request(Uri.parse(url))
                .setTitle(filename)
                .setDescription("Count-On-Me export")
                .setNotificationVisibility(DownloadManager.Request.VISIBILITY_VISIBLE_NOTIFY_COMPLETED)
                .setDestinationInExternalPublicDir(Environment.DIRECTORY_DOWNLOADS, filename)
            val mime = when (filename.substringAfterLast('.', "").lowercase()) {
                "csv" -> "text/csv"
                "jpg", "jpeg" -> "image/jpeg"
                "png" -> "image/png"
                else -> "application/octet-stream"
            }
            request.setMimeType(mime)
            val dm = context.getSystemService(Context.DOWNLOAD_SERVICE) as DownloadManager
            val id = dm.enqueue(request)
            val result = JSObject()
            result.put("status", "queued")
            result.put("id", id)
            call.resolve(result)
        } catch (t: Throwable) {
            val message = "download failed: ${t.message}"
            if (t is Exception) call.reject(message, t) else call.reject(message)
        }
    }
}