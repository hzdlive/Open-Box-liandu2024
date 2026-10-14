package com.openbox.oss.vpn

import android.app.Notification
import android.app.NotificationChannel
import android.app.NotificationManager
import android.app.PendingIntent
import android.content.Intent
import android.net.VpnService
import android.os.Build
import android.os.ParcelFileDescriptor
import com.openbox.oss.api.PanelApi
import com.openbox.oss.api.ProxyMode
import com.openbox.oss.api.TokenStore
import com.openbox.oss.ui.MainActivity
import java.io.File

/**
 * Local VPN entry point. Mirrors the documented client behavior:
 * the app owns a TUN interface and feeds it to the sing-box core.
 *
 * The core itself comes from the GPL source bundle built via gomobile
 * (libbox.aar, see clients/README.md). Until it is wired in, [startCore]
 * is the single integration seam: hand it the TUN fd + client config JSON.
 */
class ProxyVpnService : VpnService() {

    companion object {
        const val ACTION_START = "com.openbox.oss.vpn.START"
        const val ACTION_STOP = "com.openbox.oss.vpn.STOP"
        private const val NOTIF_ID = 1
        private const val CHANNEL = "vpn"
    }

    private var tunFd: ParcelFileDescriptor? = null
    // private lateinit var box: LibboxService // from libbox.aar once added

    override fun onStartCommand(intent: Intent?, flags: Int, startId: Int): Int {
        when (intent?.action) {
            ACTION_START -> startVpn()
            ACTION_STOP -> stopVpn()
        }
        return START_STICKY
    }

    private fun startVpn() {
        startForeground(NOTIF_ID, notification("Connecting…"))
        val store = TokenStore(this)
        val api = PanelApi(store.baseUrl() ?: return stopSelf(), store)
        val mode = try { api.mode() } catch (e: Exception) { ProxyMode.RULE }

        // 1. Pull the client-tailored sing-box config from the panel.
        val configJson = try {
            api.clientConfig(mode)
        } catch (e: Exception) {
            stopSelf()
            return
        }
        File(filesDir, "client-config.json").writeText(configJson)

        // 2. Bring up the TUN interface (10.8.0.0/24, app-owned).
        val tun = Builder()
            .setSession("OpenBox OSS")
            .addAddress("10.8.0.2", 24)
            .addRoute("0.0.0.0", 0)
            .addRoute("::", 0)
            .addDnsServer("10.8.0.1")
            .setMtu(1500)
            .establish() ?: return stopSelf()
        tunFd = tun

        // 3. Hand fd + config to the core (integration seam).
        startCore(tun.detachFd(), File(filesDir, "client-config.json").absolutePath)

        (getSystemService(NOTIFICATION_SERVICE) as NotificationManager)
            .notify(NOTIF_ID, notification("Connected (${mode.value})"))
    }

    /**
     * Integration seam for libbox.aar (gomobile). The generated bindings
     * expose something like `Libbox.start(fd, configPath)`; adapt here.
     */
    private fun startCore(tunFd: Int, configPath: String) {
        // TODO: wire libbox.aar once built from the GPL source bundle.
        // box = Libbox.newService(tunFd, configPath)
    }

    private fun stopVpn() {
        // TODO: box?.stop()
        try { tunFd?.close() } catch (_: Exception) { }
        tunFd = null
        stopForeground(STOP_FOREGROUND_REMOVE)
        stopSelf()
    }

    override fun onDestroy() {
        stopVpn()
        super.onDestroy()
    }

    private fun notification(text: String): Notification {
        val nm = getSystemService(NOTIFICATION_SERVICE) as NotificationManager
        if (Build.VERSION.SDK_INT >= 26) {
            nm.createNotificationChannel(
                NotificationChannel(CHANNEL, "VPN", NotificationManager.IMPORTANCE_LOW))
        }
        val pi = PendingIntent.getActivity(
            this, 0, Intent(this, MainActivity::class.java),
            PendingIntent.FLAG_IMMUTABLE)
        return Notification.Builder(this, CHANNEL)
            .setContentTitle("OpenBox OSS")
            .setContentText(text)
            .setSmallIcon(android.R.drawable.ic_lock_lock)
            .setContentIntent(pi)
            .build()
    }
}
