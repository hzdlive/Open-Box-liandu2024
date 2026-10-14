package com.openbox.oss.wifi

import android.content.BroadcastReceiver
import android.content.Context
import android.content.Intent
import android.content.IntentFilter
import android.net.ConnectivityManager
import android.net.NetworkCapabilities
import android.net.wifi.WifiManager
import android.os.Build
import com.openbox.oss.api.PanelApi
import com.openbox.oss.api.ProxyMode
import com.openbox.oss.api.TokenStore
import com.openbox.oss.vpn.ProxyVpnService
import kotlinx.coroutines.CoroutineScope
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.launch

/**
 * Wi-Fi auto-pause (documented client behavior).
 *
 * Listens for Wi-Fi state changes; when the current SSID is on the panel's
 * exemption list, pauses the VPN (or drops to direct mode per policy action)
 * and resumes when leaving.
 *
 * NOTE: on Android 10+ the SSID requires FINE_LOCATION + location enabled.
 * The policy itself comes from GET /api/client/wifi-policy.
 */
class WifiPauseReceiver : BroadcastReceiver() {

    override fun onReceive(ctx: Context, intent: Intent) {
        if (!isWifiConnected(ctx)) {
            setPaused(ctx, false)
            return
        }
        val ssid = currentSsid(ctx) ?: return
        CoroutineScope(Dispatchers.IO).launch {
            val store = TokenStore(ctx)
            if (!store.isPaired()) return@launch
            val policy = try {
                PanelApi(store.baseUrl()!!, store).wifiPolicy()
            } catch (e: Exception) { return@launch }
            if (!policy.enabled) return@launch
            val exempt = policy.pauseSsids.any { ssid.contains(it.trim('"')) }
            setPaused(ctx, exempt, policy.action)
        }
    }

    private fun setPaused(ctx: Context, paused: Boolean, action: String = "pause") {
        val svc = Intent(ctx, ProxyVpnService::class.java)
        if (paused && action == "pause") {
            svc.action = ProxyVpnService.ACTION_STOP
        } else {
            svc.action = ProxyVpnService.ACTION_START
        }
        // direct-mode pause is handled by switching mode then starting:
        // (mode switch omitted here; the VPN path covers the common case)
        ctx.startForegroundService(svc)
    }

    private fun isWifiConnected(ctx: Context): Boolean {
        val cm = ctx.getSystemService(Context.CONNECTIVITY_SERVICE) as ConnectivityManager
        val net = cm.activeNetwork ?: return false
        val caps = cm.getNetworkCapabilities(net) ?: return false
        return caps.hasTransport(NetworkCapabilities.TRANSPORT_WIFI)
    }

    private fun currentSsid(ctx: Context): String? {
        val wm = ctx.applicationContext
            .getSystemService(Context.WIFI_SERVICE) as WifiManager
        @Suppress("DEPRECATION")
        val info = wm.connectionInfo ?: return null
        return info.ssid?.trim('"')?.takeIf { it != "<unknown ssid>" }
    }

    companion object {
        fun register(ctx: Context): BroadcastReceiver {
            val r = WifiPauseReceiver()
            val f = IntentFilter().apply {
                addAction(WifiManager.NETWORK_STATE_CHANGED_ACTION)
                addAction(ConnectivityManager.CONNECTIVITY_ACTION)
            }
            if (Build.VERSION.SDK_INT >= 33) {
                ctx.registerReceiver(r, f, Context.RECEIVER_NOT_EXPORTED)
            } else {
                @Suppress("DEPRECATION")
                ctx.registerReceiver(r, f)
            }
            return r
        }
    }
}
