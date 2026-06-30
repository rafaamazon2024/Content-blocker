package com.contentblocker

import android.net.VpnService
import java.io.FileDescriptor
import java.io.FileInputStream
import java.io.FileOutputStream
import java.net.DatagramPacket
import java.net.DatagramSocket
import java.net.InetAddress
import java.nio.ByteBuffer
import java.nio.ByteOrder

/**
 * Reads IP packets from the TUN file descriptor.
 * Intercepts DNS queries (UDP port 53 destined for FAKE_DNS_IP),
 * forwards them to the real DNS server, and writes the response back into TUN.
 * All other traffic is ignored (only the DNS IP is routed through the VPN).
 */
class DnsProxy(
    private val vpnService: VpnService,
    private val tunFd: FileDescriptor,
    private val realDnsServer: String,
) {
    companion object {
        const val VPN_ADDRESS = "10.0.0.1"
        const val FAKE_DNS_IP = "10.0.0.2"
        private val FAKE_DNS_BYTES = InetAddress.getByName(FAKE_DNS_IP).address
    }

    @Volatile var running = true

    fun run() {
        val input  = FileInputStream(tunFd)
        val output = FileOutputStream(tunFd)
        val buf    = ByteArray(32767)

        while (running) {
            val len = try {
                input.read(buf)
            } catch (e: Exception) {
                if (running) Thread.sleep(50)
                continue
            }
            if (len < 28) continue  // minimum IPv4 + UDP + 1 byte DNS

            // ── Parse IPv4 header ──────────────────────────────────────────
            val versionIhl = buf[0].toInt() and 0xFF
            if ((versionIhl shr 4) != 4) continue          // not IPv4
            val ihl      = (versionIhl and 0xF) * 4
            val protocol = buf[9].toInt() and 0xFF
            if (protocol != 17) continue                    // not UDP

            // Check destination IP == FAKE_DNS_IP
            if (!buf.sliceArray(16..19).contentEquals(FAKE_DNS_BYTES)) continue

            // ── Parse UDP header ───────────────────────────────────────────
            val srcPort  = buf.u16(ihl)
            val destPort = buf.u16(ihl + 2)
            if (destPort != 53) continue

            val dnsStart = ihl + 8
            val dnsLen   = len - dnsStart
            if (dnsLen <= 0) continue

            val dnsQuery    = buf.copyOfRange(dnsStart, dnsStart + dnsLen)
            val clientSrcPort = srcPort

            // ── Forward to real DNS in a background thread ─────────────────
            Thread {
                try {
                    val sock = DatagramSocket()
                    vpnService.protect(sock)   // bypass VPN so it reaches real internet
                    sock.soTimeout = 5_000

                    val addr = InetAddress.getByName(realDnsServer)
                    sock.send(DatagramPacket(dnsQuery, dnsQuery.size, addr, 53))

                    val respBuf    = ByteArray(4096)
                    val respPacket = DatagramPacket(respBuf, respBuf.size)
                    sock.receive(respPacket)
                    sock.close()

                    val dnsResp = respBuf.copyOf(respPacket.length)
                    val ipPacket = buildIpUdpPacket(
                        srcIp   = FAKE_DNS_IP,
                        dstIp   = VPN_ADDRESS,
                        srcPort = 53,
                        dstPort = clientSrcPort,
                        payload = dnsResp,
                    )
                    synchronized(output) { output.write(ipPacket) }
                } catch (_: Exception) {
                    // Drop unanswered queries silently
                }
            }.start()
        }
    }

    // ── Packet builder ─────────────────────────────────────────────────────

    private fun buildIpUdpPacket(
        srcIp: String, dstIp: String,
        srcPort: Int, dstPort: Int,
        payload: ByteArray,
    ): ByteArray {
        val udpLen   = 8 + payload.size
        val totalLen = 20 + udpLen
        val pkt      = ByteBuffer.allocate(totalLen).order(ByteOrder.BIG_ENDIAN)

        val srcBytes = InetAddress.getByName(srcIp).address
        val dstBytes = InetAddress.getByName(dstIp).address

        // IPv4 header (checksum filled in below)
        pkt.put(0x45.toByte())              // version=4, IHL=5 (20 bytes, no options)
        pkt.put(0)                          // DSCP/ECN
        pkt.putShort(totalLen.toShort())
        pkt.putShort(0)                     // ID (not used — not fragmented)
        pkt.putShort(0x4000.toShort())      // flags: DF, fragment offset 0
        pkt.put(64)                         // TTL
        pkt.put(17)                         // protocol UDP
        pkt.putShort(0)                     // checksum placeholder
        pkt.put(srcBytes)
        pkt.put(dstBytes)

        val checksum = ipChecksum(pkt.array(), 0, 20)
        pkt.putShort(10, checksum.toShort())

        // UDP header (checksum = 0, optional in IPv4)
        pkt.putShort(srcPort.toShort())
        pkt.putShort(dstPort.toShort())
        pkt.putShort(udpLen.toShort())
        pkt.putShort(0)

        pkt.put(payload)
        return pkt.array()
    }

    private fun ipChecksum(data: ByteArray, offset: Int, length: Int): Int {
        var sum = 0
        var i = offset
        while (i < offset + length - 1) {
            sum += ((data[i].toInt() and 0xFF) shl 8) or (data[i + 1].toInt() and 0xFF)
            i += 2
        }
        if ((offset + length) % 2 != 0) {
            sum += (data[offset + length - 1].toInt() and 0xFF) shl 8
        }
        while (sum ushr 16 != 0) sum = (sum and 0xFFFF) + (sum ushr 16)
        return sum.inv() and 0xFFFF
    }

    private fun ByteArray.u16(offset: Int): Int =
        ((this[offset].toInt() and 0xFF) shl 8) or (this[offset + 1].toInt() and 0xFF)
}
