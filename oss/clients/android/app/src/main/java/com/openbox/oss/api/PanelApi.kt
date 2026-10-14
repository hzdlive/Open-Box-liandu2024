package com.openbox.oss.api

import kotlinx.serialization.builtins.ListSerializer
import kotlinx.serialization.json.Json
import okhttp3.MediaType.Companion.toMediaType
import okhttp3.OkHttpClient
import okhttp3.Request
import okhttp3.RequestBody.Companion.toRequestBody
import java.util.concurrent.TimeUnit

/**
 * HTTP client for the panel API (docs/client-api.md).
 *
 * Auth: Bearer <client_token> obtained from the pairing flow
 * (POST /api/pair/confirm). Tokens are stored in [TokenStore], never logged.
 */
class PanelApi(
    private val baseUrl: String,
    private val tokenStore: TokenStore,
) {
    private val json = Json { ignoreUnknownKeys = true; explicitNulls = false }
    private val http = OkHttpClient.Builder()
        .connectTimeout(10, TimeUnit.SECONDS)
        .readTimeout(30, TimeUnit.SECONDS)
        .build()

    private fun req(path: String, authed: Boolean = true): Request.Builder {
        val b = Request.Builder().url(baseUrl.trimEnd('/') + path)
        if (authed) {
            val tok = tokenStore.clientToken()
                ?: throw IllegalStateException("not paired")
            b.header("Authorization", "Bearer $tok")
        }
        return b
    }

    private fun <T> get(path: String, deser: (String) -> T, authed: Boolean = true): T {
        req(path, authed).get().build().let { http.newCall(it).execute() }.use { r ->
            check(r.isSuccessful) { "GET $path -> ${r.code}" }
            return deser(r.body!!.string())
        }
    }

    private fun post(path: String, body: String, authed: Boolean = true): String {
        val rb = body.toRequestBody("application/json".toMediaType())
        req(path, authed).post(rb).build().let { http.newCall(it).execute() }.use { r ->
            check(r.isSuccessful) { "POST $path -> ${r.code}" }
            return r.body!!.string()
        }
    }

    // ---- pairing (no auth; the one-time code is the credential) ----
    fun pairCode(): PairCode =
        json.decodeFromString(PairCode.serializer(), post("/api/pair/code", "{}", authed = false))

    fun pairConfirm(oneTimeToken: String, deviceName: String): PairResult {
        val body = """{"token":"$oneTimeToken","device":"$deviceName"}"""
        val res = json.decodeFromString(
            PairResult.serializer(), post("/api/pair/confirm", body, authed = false))
        tokenStore.save(res.clientToken)
        return res
    }

    // ---- client API ----
    fun status(): ClientStatus =
        get("/api/client/status") { json.decodeFromString(ClientStatus.serializer(), it) }

    fun nodes(): List<NodeInfo> =
        get("/api/client/nodes") { json.decodeFromString(ListSerializer(NodeInfo.serializer()), it) }

    fun groups(): List<GroupInfo> =
        get("/api/client/groups") { json.decodeFromString(ListSerializer(GroupInfo.serializer()), it) }

    fun selectOutbound(group: String, tag: String) {
        post("/api/client/groups/$group/select", """{"tag":"$tag"}""")
    }

    fun clientConfig(mode: ProxyMode, ruleset: String = "follow"): String =
        get("/api/client/config?mode=${mode.value}&ruleset=$ruleset") { it }

    fun mode(): ProxyMode {
        val raw = get("/api/client/mode") { it }
        val v = json.decodeFromString<Map<String, String>>(raw)["mode"]
        return ProxyMode.entries.first { it.value == v }
    }

    fun setMode(mode: ProxyMode) {
        post("/api/client/mode", """{"mode":"${mode.value}"}""")
    }

    fun syncPull(clientRev: Int): SyncPullResult {
        val body = """{"direction":"pull","client_rev":$clientRev}"""
        return json.decodeFromString(
            SyncPullResult.serializer(),
            post("/api/client/subscriptions/sync", body))
    }

    fun syncPush(name: String, content: String, format: String = "auto"): SyncPushResult {
        val esc = content.replace("\\", "\\\\").replace("\"", "\\\"").replace("\n", "\\n")
        val body = """{"direction":"push","name":"$name","content":"$esc","format":"$format"}"""
        return json.decodeFromString(
            SyncPushResult.serializer(),
            post("/api/client/subscriptions/sync", body))
    }

    fun wifiPolicy(): WifiPolicy =
        get("/api/client/wifi-policy") { json.decodeFromString(WifiPolicy.serializer(), it) }
}
