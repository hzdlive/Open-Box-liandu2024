package com.openbox.oss.sync

import android.content.Context
import androidx.datastore.preferences.core.edit
import androidx.datastore.preferences.core.intPreferencesKey
import androidx.datastore.preferences.preferencesDataStore
import androidx.work.CoroutineWorker
import androidx.work.ExistingPeriodicWorkPolicy
import androidx.work.PeriodicWorkRequestBuilder
import androidx.work.WorkManager
import androidx.work.WorkerParameters
import com.openbox.oss.api.PanelApi
import com.openbox.oss.api.TokenStore
import kotlinx.coroutines.flow.first
import kotlinx.coroutines.flow.map
import java.util.concurrent.TimeUnit

private val Context.syncStore by preferencesDataStore("sync")

/**
 * Periodic subscription sync against the panel (docs/client-api.md §5).
 * Pull-only here; pushes happen from the share/import UI directly.
 */
class SyncWorker(ctx: Context, params: WorkerParameters) : CoroutineWorker(ctx, params) {

    override suspend fun doWork(): Result {
        val store = TokenStore(applicationContext)
        if (!store.isPaired()) return Result.success()
        val api = PanelApi(store.baseUrl()!!, store)
        return try {
            val revKey = intPreferencesKey("client_rev")
            val lastRev = applicationContext.syncStore.data.map { it[revKey] ?: 0 }.first()
            val res = api.syncPull(lastRev)
            if (res.nodes.isNotEmpty()) {
                // TODO: upsert into the local node cache (Room) for offline display.
            }
            applicationContext.syncStore.edit { it[revKey] = res.rev }
            Result.success()
        } catch (e: Exception) {
            Result.retry()
        }
    }

    companion object {
        private const val TAG = "openbox-sync"

        fun schedule(ctx: Context) {
            val req = PeriodicWorkRequestBuilder<SyncWorker>(30, TimeUnit.MINUTES)
                .addTag(TAG)
                .build()
            WorkManager.getInstance(ctx).enqueueUniquePeriodicWork(
                TAG, ExistingPeriodicWorkPolicy.KEEP, req)
        }
    }
}
