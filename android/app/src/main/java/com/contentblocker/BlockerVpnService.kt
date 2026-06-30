package com.contentblocker

import android.app.*
import android.content.Intent
import android.net.VpnService
import android.os.Build
import androidx.core.app.NotificationCompat

/**
 * VPN service that routes all DNS traffic through our content-blocker server.
 *
 * Architecture:
 *  - Creates a TUN interface with a fake DNS IP (10.0.0.2) in its route table.
 *  - Android resolves all DNS via 10.0.0.2, which lands on the TUN fd.
 *  - DnsProxy reads those packets, forwards them to the real DNS server
 *    (using protect() so the socket bypasses the VPN), and writes the
 *    response back into the TUN fd.
 *  - Only the fake DNS IP is routed through the VPN — all other traffic
 *    flows normally, keeping battery impact minimal.
 */
class BlockerVpnService : VpnService() {

    companion object {
        const val ACTION_START  = "com.contentblocker.START"
        const val ACTION_STOP   = "com.contentblocker.STOP"
        private const val CHANNEL_ID = "blocker_vpn"
        private const val NOTIF_ID   = 1

        @Volatile var isRunning = false
    }

    private var vpnFd: ParcelFileDescriptor? = null
    private var proxy: DnsProxy? = null
    private var proxyThread: Thread? = null

    override fun onStartCommand(intent: Intent?, flags: Int, startId: Int): Int {
        return when (intent?.action) {
            ACTION_STOP -> { stopVpn(); START_NOT_STICKY }
            else        -> { startVpn(); START_STICKY    }
        }
    }

    private fun startVpn() {
        if (isRunning) return

        val prefs = getSharedPreferences("blocker", MODE_PRIVATE)
        val dnsServer = prefs.getString("dns_server", "").orEmpty()
        if (dnsServer.isEmpty()) { stopSelf(); return }

        createNotificationChannel()
        startForeground(NOTIF_ID, buildNotification())

        val fd = Builder()
            .setSession("ContentBlocker")
            .addAddress(DnsProxy.VPN_ADDRESS, 32)
            .addRoute(DnsProxy.FAKE_DNS_IP, 32)   // only DNS IP through VPN tunnel
            .addDnsServer(DnsProxy.FAKE_DNS_IP)
            .setBlocking(true)
            .establish()
            ?: run { stopSelf(); return }

        vpnFd    = fd
        isRunning = true

        val p = DnsProxy(this, fd.fileDescriptor, dnsServer)
        proxy = p
        proxyThread = Thread(p::run, "dns-proxy").also { it.isDaemon = true; it.start() }
    }

    private fun stopVpn() {
        isRunning = false
        proxy?.running = false
        proxyThread?.interrupt()
        runCatching { vpnFd?.close() }
        vpnFd = null
        stopForeground(STOP_FOREGROUND_REMOVE)
        stopSelf()
    }

    override fun onDestroy() {
        stopVpn()
        super.onDestroy()
    }

    // ── Notification ───────────────────────────────────────────────────────

    private fun createNotificationChannel() {
        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.O) {
            val channel = NotificationChannel(
                CHANNEL_ID,
                "VPN Status",
                NotificationManager.IMPORTANCE_LOW,
            ).apply { description = "Content Blocker VPN" }
            getSystemService(NotificationManager::class.java)
                ?.createNotificationChannel(channel)
        }
    }

    private fun buildNotification(): Notification {
        val openApp = PendingIntent.getActivity(
            this, 0,
            Intent(this, MainActivity::class.java),
            PendingIntent.FLAG_IMMUTABLE,
        )
        return NotificationCompat.Builder(this, CHANNEL_ID)
            .setContentTitle(getString(R.string.notif_title))
            .setContentText(getString(R.string.notif_text))
            .setSmallIcon(android.R.drawable.ic_lock_lock)
            .setContentIntent(openApp)
            .setOngoing(true)
            .build()
    }
}
