package com.openbox.oss.api

import kotlinx.serialization.SerialName
import kotlinx.serialization.Serializable

/** Mirrors docs/client-api.md and the tested /api/client/* surface. */

@Serializable
data class ClientStatus(
    val running: Boolean,
    val version: String? = null,
    @SerialName("uptime_s") val uptimeS: Double? = null,
    val mode: String = "rule",
    val rev: Int = 0,
)

@Serializable
data class NodeInfo(
    val tag: String,
    val protocol: String,
    val server: String,
    val port: Int,
    @SerialName("latency_ms") val latencyMs: Double? = null,
    val ok: Boolean? = null,
)

@Serializable
data class GroupInfo(
    val name: String,
    val type: String,
    val members: List<String> = emptyList(),
)

@Serializable
data class PairCode(val token: String, @SerialName("expires_in") val expiresIn: Int)

@Serializable
data class PairResult(
    @SerialName("client_token") val clientToken: String,
    @SerialName("device_id") val deviceId: Long,
)

@Serializable
data class DeviceInfo(val id: Long, val name: String, @SerialName("created_at") val createdAt: String)

@Serializable
data class SyncPullResult(val rev: Int, val nodes: List<NodeInfo> = emptyList())

@Serializable
data class SyncPushResult(val added: Int, val rev: Int)

@Serializable
data class WifiPolicy(
    val enabled: Boolean = false,
    @SerialName("pause_ssids") val pauseSsids: List<String> = emptyList(),
    val action: String = "pause", // pause | direct
)

enum class ProxyMode(val value: String) {
    GLOBAL("global"), RULE("rule"), DIRECT("direct");
}
