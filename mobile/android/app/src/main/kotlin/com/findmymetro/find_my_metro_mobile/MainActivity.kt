package com.findmymetro.find_my_metro_mobile

import io.flutter.embedding.android.FlutterActivity
import io.flutter.embedding.engine.FlutterEngine
import io.flutter.plugin.common.MethodChannel
import android.Manifest
import android.content.pm.PackageManager
import android.os.Build
import android.os.Handler
import android.os.Looper
import android.os.SystemClock
import android.telephony.*
import java.security.MessageDigest
import java.util.concurrent.atomic.AtomicBoolean

class MainActivity : FlutterActivity() {
    override fun configureFlutterEngine(flutterEngine: FlutterEngine) {
        super.configureFlutterEngine(flutterEngine)
        MethodChannel(flutterEngine.dartExecutor.binaryMessenger, "findmymetro/phone_context")
            .setMethodCallHandler { call, result ->
                if (call.method != "readCells") {
                    result.notImplemented()
                } else if (checkSelfPermission(Manifest.permission.ACCESS_FINE_LOCATION) != PackageManager.PERMISSION_GRANTED) {
                    result.error("permission_required", "Precise location permission is required for cell readings.", null)
                } else {
                    val manager = getSystemService(TELEPHONY_SERVICE) as? TelephonyManager
                    if (manager == null) {
                        result.success(mapOf("status" to "unavailable", "cells" to emptyList<Any>()))
                    } else {
                        val completed = AtomicBoolean(false)
                        fun finish(items: List<CellInfo>?) {
                            if (!completed.compareAndSet(false, true)) return
                            val cells = (items ?: emptyList()).mapNotNull { cell -> fingerprint(cell) }.distinctBy { it["fingerprint"] }.take(16)
                            result.success(mapOf("status" to if (cells.isEmpty()) "unavailable_or_stale" else "available", "cells" to cells))
                        }
                        try {
                            if (Build.VERSION.SDK_INT >= 29) {
                                manager.requestCellInfoUpdate(mainExecutor, object : TelephonyManager.CellInfoCallback() {
                                    override fun onCellInfo(cellInfo: MutableList<CellInfo>) { finish(cellInfo) }
                                    override fun onError(errorCode: Int, detail: Throwable?) { finish(manager.allCellInfo) }
                                })
                                Handler(Looper.getMainLooper()).postDelayed({
                                    try { finish(manager.allCellInfo) } catch (_: Exception) { finish(null) }
                                }, 5000)
                            } else finish(manager.allCellInfo)
                        } catch (_: Exception) { finish(null) }
                    }
                }
            }
    }

    @Suppress("DEPRECATION")
    private fun fingerprint(cell: CellInfo): Map<String, Any>? {
        val ageMs = (SystemClock.elapsedRealtimeNanos() - cell.timeStamp) / 1_000_000
        if (ageMs < 0 || ageMs >= 30_000) return null
        val identity: String = when (cell) {
            is CellInfoLte -> cell.cellIdentity.let { i ->
                if (i.ci == Int.MAX_VALUE || i.tac == Int.MAX_VALUE) return null
                "lte:${if (Build.VERSION.SDK_INT >= 28) i.mccString else i.mcc}:${if (Build.VERSION.SDK_INT >= 28) i.mncString else i.mnc}:${i.tac}:${i.ci}"
            }
            is CellInfoGsm -> cell.cellIdentity.let { i ->
                if (i.cid == Int.MAX_VALUE || i.lac == Int.MAX_VALUE) return null
                "gsm:${if (Build.VERSION.SDK_INT >= 28) i.mccString else i.mcc}:${if (Build.VERSION.SDK_INT >= 28) i.mncString else i.mnc}:${i.lac}:${i.cid}"
            }
            is CellInfoWcdma -> cell.cellIdentity.let { i ->
                if (i.cid == Int.MAX_VALUE || i.lac == Int.MAX_VALUE) return null
                "wcdma:${if (Build.VERSION.SDK_INT >= 28) i.mccString else i.mcc}:${if (Build.VERSION.SDK_INT >= 28) i.mncString else i.mnc}:${i.lac}:${i.cid}"
            }
            else -> if (Build.VERSION.SDK_INT >= 29 && cell is CellInfoNr) {
                val i = cell.cellIdentity as CellIdentityNr
                if (i.nci == Long.MAX_VALUE || i.tac == Int.MAX_VALUE) return null
                "nr:${i.mccString}:${i.mncString}:${i.tac}:${i.nci}"
            } else return null
        }
        if (identity.contains(":null:") || identity.contains(":2147483647:")) return null
        val hash = MessageDigest.getInstance("SHA-256").digest(identity.toByteArray(Charsets.UTF_8))
            .joinToString("") { "%02x".format(it) }
        // Never return the raw identity, IMSI, IMEI, subscriber ID or number.
        return mapOf("fingerprint" to hash, "age_ms" to ageMs, "registered" to cell.isRegistered)
    }
}
