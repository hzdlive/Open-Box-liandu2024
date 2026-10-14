package com.openbox.oss.ui

import android.app.Activity
import android.content.Intent
import android.net.VpnService
import android.os.Bundle
import android.widget.Button
import android.widget.LinearLayout
import android.widget.TextView
import com.openbox.oss.api.PanelApi
import com.openbox.oss.api.ProxyMode
import com.openbox.oss.api.TokenStore
import com.openbox.oss.sync.SyncWorker
import com.openbox.oss.vpn.ProxyVpnService
import com.openbox.oss.wifi.WifiPauseReceiver
import kotlinx.coroutines.CoroutineScope
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.launch
import kotlinx.coroutines.withContext

/**
 * Thin status UI. Real logic lives in api/ vpn/ sync/ wifi/.
 */
class MainActivity : Activity() {

    private lateinit var statusView: TextView
    private var wifiReceiver: android.content.BroadcastReceiver? = null

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        val store = TokenStore(this)
        if (!store.isPaired()) {
            startActivity(Intent(this, PairingActivity::class.java))
            finish()
            return
        }

        val layout = LinearLayout(this).apply {
            orientation = LinearLayout.VERTICAL
            setPadding(48, 48, 48, 48)
        }
        statusView = TextView(this)
        val btnToggle = Button(this).apply { text = "启动 / 停止" }
        val btnMode = Button(this).apply { text = "切换模式" }
        val btnUnpair = Button(this).apply { text = "解除配对" }
        layout.addView(statusView)
        layout.addView(btnToggle)
        layout.addView(btnMode)
        layout.addView(btnUnpair)
        setContentView(layout)

        btnToggle.setOnClickListener { toggleVpn() }
        btnMode.setOnClickListener { cycleMode() }
        btnUnpair.setOnClickListener {
            store.clear()
            stopVpn()
            startActivity(Intent(this, PairingActivity::class.java))
            finish()
        }

        wifiReceiver = WifiPauseReceiver.register(this)
        SyncWorker.schedule(this)
        refreshStatus()
    }

    override fun onDestroy() {
        wifiReceiver?.let { unregisterReceiver(it) }
        super.onDestroy()
    }

    private fun api(): PanelApi {
        val store = TokenStore(this)
        return PanelApi(store.baseUrl()!!, store)
    }

    private fun refreshStatus() {
        CoroutineScope(Dispatchers.IO).launch {
            val text = try {
                val s = api().status()
                "running=${s.running} mode=${s.mode} rev=${s.rev}"
            } catch (e: Exception) {
                "panel unreachable: ${e.message}"
            }
            withContext(Dispatchers.Main) { statusView.text = text }
        }
    }

    private var vpnOn = false

    private fun toggleVpn() {
        if (vpnOn) stopVpn() else {
            val intent = VpnService.prepare(this)
            if (intent != null) {
                @Suppress("DEPRECATION")
                startActivityForResult(intent, 100)
            } else startVpn()
        }
    }

    private fun startVpn() {
        startForegroundService(Intent(this, ProxyVpnService::class.java).apply {
            action = ProxyVpnService.ACTION_START
        })
        vpnOn = true
    }

    private fun stopVpn() {
        startService(Intent(this, ProxyVpnService::class.java).apply {
            action = ProxyVpnService.ACTION_STOP
        })
        vpnOn = false
    }

    private fun cycleMode() {
        CoroutineScope(Dispatchers.IO).launch {
            try {
                val cur = api().mode()
                val next = when (cur) {
                    ProxyMode.RULE -> ProxyMode.GLOBAL
                    ProxyMode.GLOBAL -> ProxyMode.DIRECT
                    ProxyMode.DIRECT -> ProxyMode.RULE
                }
                api().setMode(next)
            } catch (_: Exception) { }
            refreshStatus()
        }
    }

    @Deprecated("use Activity Result API in production")
    override fun onActivityResult(requestCode: Int, resultCode: Int, data: Intent?) {
        super.onActivityResult(requestCode, resultCode, data)
        if (requestCode == 100 && resultCode == RESULT_OK) startVpn()
    }
}
