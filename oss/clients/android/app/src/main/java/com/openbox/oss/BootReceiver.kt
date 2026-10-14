package com.openbox.oss

import android.content.BroadcastReceiver
import android.content.Context
import android.content.Intent
import com.openbox.oss.sync.SyncWorker

/** Re-arm periodic sync after reboot. */
class BootReceiver : BroadcastReceiver() {
    override fun onReceive(ctx: Context, intent: Intent) {
        if (intent.action == Intent.ACTION_BOOT_COMPLETED) {
            SyncWorker.schedule(ctx)
        }
    }
}
