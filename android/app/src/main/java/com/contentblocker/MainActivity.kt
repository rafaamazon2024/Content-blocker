package com.contentblocker

import android.content.Intent
import android.content.SharedPreferences
import android.net.VpnService
import android.os.Bundle
import android.text.InputType
import android.widget.*
import androidx.activity.result.contract.ActivityResultContracts
import androidx.appcompat.app.AlertDialog
import androidx.appcompat.app.AppCompatActivity

class MainActivity : AppCompatActivity() {

    private lateinit var prefs: SharedPreferences
    private lateinit var btnToggle: Button
    private lateinit var tvStatus: TextView
    private lateinit var tvDnsServer: TextView

    private val vpnPermission = registerForActivityResult(
        ActivityResultContracts.StartActivityForResult()
    ) { result ->
        if (result.resultCode == RESULT_OK) startBlocker()
        else toast("Permissão de VPN negada")
    }

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        setContentView(R.layout.activity_main)

        prefs       = getSharedPreferences("blocker", MODE_PRIVATE)
        btnToggle   = findViewById(R.id.btnToggle)
        tvStatus    = findViewById(R.id.tvStatus)
        tvDnsServer = findViewById(R.id.tvDnsServer)

        if (prefs.getString("dns_server", "").isNullOrEmpty()) {
            showSetupDialog()
        }

        btnToggle.setOnClickListener {
            if (BlockerVpnService.isRunning) {
                promptPin { stopBlocker() }
            } else {
                requestVpnAndStart()
            }
        }

        findViewById<Button>(R.id.btnSetup).setOnClickListener {
            if (BlockerVpnService.isRunning) {
                promptPin { showSetupDialog() }
            } else {
                showSetupDialog()
            }
        }
    }

    override fun onResume() {
        super.onResume()
        refreshUi()
    }

    // ── VPN control ────────────────────────────────────────────────────────

    private fun requestVpnAndStart() {
        if (prefs.getString("dns_server", "").isNullOrEmpty()) {
            toast("Configure o servidor DNS primeiro")
            showSetupDialog()
            return
        }
        val intent = VpnService.prepare(this)
        if (intent != null) vpnPermission.launch(intent) else startBlocker()
    }

    private fun startBlocker() {
        Intent(this, BlockerVpnService::class.java)
            .apply { action = BlockerVpnService.ACTION_START }
            .also { startForegroundService(it) }
        btnToggle.postDelayed(::refreshUi, 600)
    }

    private fun stopBlocker() {
        Intent(this, BlockerVpnService::class.java)
            .apply { action = BlockerVpnService.ACTION_STOP }
            .also { startService(it) }
        btnToggle.postDelayed(::refreshUi, 600)
    }

    // ── UI ─────────────────────────────────────────────────────────────────

    private fun refreshUi() {
        val running = BlockerVpnService.isRunning
        tvStatus.text    = getString(if (running) R.string.status_on else R.string.status_off)
        tvStatus.setTextColor(getColor(if (running) R.color.active else android.R.color.darker_gray))
        btnToggle.text   = getString(if (running) R.string.btn_off else R.string.btn_on)
        btnToggle.backgroundTintList = resources.getColorStateList(
            if (running) R.color.active else R.color.primary, theme
        )
        val dns = prefs.getString("dns_server", "") ?: ""
        tvDnsServer.text = if (dns.isNotEmpty()) "DNS: $dns" else ""
    }

    // ── Dialogs ────────────────────────────────────────────────────────────

    private fun showSetupDialog() {
        val container = LinearLayout(this).apply {
            orientation = LinearLayout.VERTICAL
            setPadding(56, 24, 56, 8)
        }
        val etDns = EditText(this).apply {
            hint = "IP do servidor DNS"
            setText(prefs.getString("dns_server", ""))
        }
        val etPin = EditText(this).apply {
            hint = "PIN para desligar (opcional)"
            inputType = InputType.TYPE_CLASS_NUMBER or InputType.TYPE_NUMBER_VARIATION_PASSWORD
        }
        container.addView(TextView(this).apply { text = "Servidor DNS (VPS):" })
        container.addView(etDns)
        container.addView(TextView(this).apply { text = "PIN de proteção:" ; setPadding(0,16,0,0) })
        container.addView(etPin)

        AlertDialog.Builder(this)
            .setTitle("Configuração")
            .setView(container)
            .setCancelable(false)
            .setPositiveButton("Salvar") { _, _ ->
                val dns = etDns.text.toString().trim()
                val pin = etPin.text.toString().trim()
                if (dns.isEmpty()) { toast("Digite o IP do servidor"); return@setPositiveButton }
                prefs.edit()
                    .putString("dns_server", dns)
                    .putString("pin", pin)
                    .apply()
                toast("Configuração salva")
                refreshUi()
            }
            .show()
    }

    private fun promptPin(onSuccess: () -> Unit) {
        val pin = prefs.getString("pin", "").orEmpty()
        if (pin.isEmpty()) { onSuccess(); return }

        val et = EditText(this).apply {
            hint      = "PIN"
            inputType = InputType.TYPE_CLASS_NUMBER or InputType.TYPE_NUMBER_VARIATION_PASSWORD
        }
        AlertDialog.Builder(this)
            .setTitle("Digite o PIN")
            .setView(et)
            .setPositiveButton("OK") { _, _ ->
                if (et.text.toString() == pin) onSuccess()
                else toast("PIN incorreto")
            }
            .setNegativeButton("Cancelar", null)
            .show()
    }

    private fun toast(msg: String) =
        Toast.makeText(this, msg, Toast.LENGTH_SHORT).show()
}
