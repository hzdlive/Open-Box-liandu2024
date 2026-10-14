package com.openbox.oss.api

import android.content.Context
import androidx.datastore.preferences.core.edit
import androidx.datastore.preferences.core.stringPreferencesKey
import androidx.datastore.preferences.preferencesDataStore
import kotlinx.coroutines.flow.first
import kotlinx.coroutines.flow.map
import kotlinx.coroutines.runBlocking

private val Context.dataStore by preferencesDataStore("openbox")

/**
 * Encrypted-at-rest would be better (EncryptedFile / Keystore); DataStore
 * keeps the skeleton dependency-free. The token never leaves the device
 * except as an Authorization header to the paired panel.
 */
class TokenStore(private val ctx: Context) {
    private val KEY_TOKEN = stringPreferencesKey("client_token")
    private val KEY_BASE = stringPreferencesKey("panel_base_url")

    fun clientToken(): String? = runBlocking {
        ctx.dataStore.data.map { it[KEY_TOKEN] }.first()
    }

    fun save(token: String) = runBlocking {
        ctx.dataStore.edit { it[KEY_TOKEN] = token }
    }

    fun clear() = runBlocking {
        ctx.dataStore.edit { it.remove(KEY_TOKEN) }
    }

    fun baseUrl(): String? = runBlocking {
        ctx.dataStore.data.map { it[KEY_BASE] }.first()
    }

    fun saveBaseUrl(url: String) = runBlocking {
        ctx.dataStore.edit { it[KEY_BASE] = url }
    }

    fun isPaired(): Boolean = clientToken() != null && baseUrl() != null
}
