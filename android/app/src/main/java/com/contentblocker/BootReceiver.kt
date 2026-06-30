package com.contentblocker

import android.content.BroadcastReceiver
import android.content.Context
import android.content.Intent
import android.net.VpnService

/**
 * Auto-starts the VPN after device reboot.
 * If VPN permission was already granted by the user (prepare() returns null),
 * the service starts silently. Otherwise nothing happens — the user needs to
 * open the app once to grant permission.
 */
class BootReceiver : BroadcastReceiver() {
    override fun onReceive(context: Context, intent: Intent) {
        if (intent.action != Intent.ACTION_BOOT_COMPLETED) return

        val prefs = context.getSharedPreferences("blocker", Context.MODE_PRIVATE)
        if (prefs.getString("dns_server", "").isNullOrEmpty()) return

        // VpnService.prepare() returns null when permission is already granted
        if (VpnService.prepare(context) != null) return

        Intent(context, BlockerVpnService::class.java)
            .apply { action = BlockerVpnService.ACTION_START }
            .also { context.startForegroundService(it) }
    }
}
