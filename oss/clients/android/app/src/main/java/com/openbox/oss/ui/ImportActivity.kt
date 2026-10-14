package com.openbox.oss.ui

import android.app.Activity
import android.content.Intent
import android.os.Bundle
import android.widget.Toast
import com.openbox.oss.api.PanelApi
import com.openbox.oss.api.TokenStore
import kotlinx.coroutines.CoroutineScope
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.launch
import kotlinx.coroutines.withContext

/**
 * Handles openbox:// ss:// vless:// vmess:// trojan:// deep links:
 * pushes the link to the panel as a client subscription (sync push),
 * so the node lands on the router. Falls back to a toast when unpaired.
 */
class ImportActivity : Activity() {

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        val link = intent?.dataString
        if (link.isNullOrBlank()) {
            finish()
            return
        }
        val store = TokenStore(this)
        if (!store.isPaired()) {
            Toast.makeText(this, "请先配对", Toast.LENGTH_SHORT).show()
            startActivity(Intent(this, PairingActivity::class.java))
            finish()
            return
        }
        CoroutineScope(Dispatchers.IO).launch {
            val msg = try {
                val res = PanelApi(store.baseUrl()!!, store)
                    .syncPush("import-${System.currentTimeMillis()}", link)
                "已导入 ${res.added} 个节点"
            } catch (e: Exception) {
                "导入失败：${e.message}"
            }
            withContext(Dispatchers.Main) {
                Toast.makeText(this@ImportActivity, msg, Toast.LENGTH_SHORT).show()
                startActivity(Intent(this@ImportActivity, MainActivity::class.java))
                finish()
            }
        }
    }
}
