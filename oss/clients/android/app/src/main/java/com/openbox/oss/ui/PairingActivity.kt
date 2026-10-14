package com.openbox.oss.ui

import android.app.Activity
import android.content.Intent
import android.net.Uri
import android.os.Bundle
import android.widget.Button
import android.widget.EditText
import android.widget.LinearLayout
import android.widget.TextView
import android.widget.Toast
import com.openbox.oss.api.PanelApi
import com.openbox.oss.api.TokenStore
import kotlinx.coroutines.CoroutineScope
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.launch
import kotlinx.coroutines.withContext

/**
 * Pairing: scan the panel's QR (or paste the openbox://pair?… URL manually).
 * CameraX + ZXing wiring is the only part left TODO; the confirm flow below
 * is complete and matches POST /api/pair/confirm.
 */
class PairingActivity : Activity() {

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        val layout = LinearLayout(this).apply {
            orientation = LinearLayout.VERTICAL
            setPadding(48, 48, 48, 48)
        }
        val hintView = TextView(this).apply {
            text = "粘贴面板配对链接（openbox://pair?host=…&port=…&token=…）\n" +
                "扫码版需接入 CameraX + ZXing（见 TODO）"
        }
        val input = EditText(this).apply { hint = "openbox://pair?…" }
        val btn = Button(this).apply { text = "配对" }
        layout.addView(hintView)
        layout.addView(input)
        layout.addView(btn)
        setContentView(layout)

        btn.setOnClickListener {
            pair(input.text.toString().trim())
        }
    }

    private fun pair(pairUrl: String) {
        val uri = try { Uri.parse(pairUrl) } catch (e: Exception) {
            toast("链接无效"); return
        }
        val host = uri.getQueryParameter("host")
            ?: run { toast("缺少 host"); return }
        val port = uri.getQueryParameter("port") ?: "8080"
        val token = uri.getQueryParameter("token")
            ?: run { toast("缺少 token"); return }
        val baseUrl = "http://$host:$port"
        CoroutineScope(Dispatchers.IO).launch {
            try {
                val store = TokenStore(this@PairingActivity)
                val api = PanelApi(baseUrl, store)
                val res = api.pairConfirm(token, android.os.Build.MODEL)
                store.saveBaseUrl(baseUrl)
                withContext(Dispatchers.Main) {
                    toast("配对成功")
                    startActivity(Intent(this@PairingActivity, MainActivity::class.java))
                    finish()
                }
            } catch (e: Exception) {
                withContext(Dispatchers.Main) { toast("配对失败：${e.message}") }
            }
        }
    }

    private fun toast(msg: String) =
        Toast.makeText(this, msg, Toast.LENGTH_SHORT).show()
}
