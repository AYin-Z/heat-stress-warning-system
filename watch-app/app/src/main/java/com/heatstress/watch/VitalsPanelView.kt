package com.heatstress.watch

import android.content.Context
import android.graphics.Canvas
import android.graphics.Color
import android.graphics.Paint
import android.graphics.RectF
import android.graphics.Typeface
import android.util.AttributeSet
import android.view.View
import java.util.Locale

/** A80 320x380 watch-face presentation for the current monitoring state. */
class VitalsPanelView @JvmOverloads constructor(
    context: Context,
    attrs: AttributeSet? = null
) : View(context, attrs) {

    var relayConnected: Boolean = false
        set(value) { field = value; refresh() }
    var batteryLevel: Int? = null
        set(value) { field = value; refresh() }
    var heartRate: Int? = null
        set(value) { field = value; refresh() }
    var coreTemp: Double? = null
        set(value) { field = value; refresh() }
    var spo2: Int? = null
        set(value) { field = value; refresh() }
    var bpSystolic: Int? = null
        set(value) { field = value; refresh() }
    var bpDiastolic: Int? = null
        set(value) { field = value; refresh() }
    var steps: Int? = null
        set(value) { field = value; refresh() }
    var wornState: Int = -1
        set(value) { field = value; refresh() }
    var gpsAccuracy: Float? = null
        set(value) { field = value; refresh() }
    var alertActive: Boolean = false
        set(value) { field = value; refresh() }

    private val framePaint = Paint(Paint.ANTI_ALIAS_FLAG).apply {
        style = Paint.Style.STROKE
        strokeWidth = 1f
        color = FRAME_COLOR
    }
    private val riskPaint = Paint(Paint.ANTI_ALIAS_FLAG).apply {
        style = Paint.Style.STROKE
        strokeWidth = 4f
        strokeCap = Paint.Cap.ROUND
    }
    private val arcBackgroundPaint = Paint(Paint.ANTI_ALIAS_FLAG).apply {
        style = Paint.Style.STROKE
        strokeWidth = 9f
        strokeCap = Paint.Cap.ROUND
        color = ARC_BACKGROUND
    }
    private val arcValuePaint = Paint(Paint.ANTI_ALIAS_FLAG).apply {
        style = Paint.Style.STROKE
        strokeWidth = 9f
        strokeCap = Paint.Cap.ROUND
    }
    private val valuePaint = Paint(Paint.ANTI_ALIAS_FLAG).apply {
        color = Color.WHITE
        textAlign = Paint.Align.CENTER
        typeface = Typeface.create("sans-serif-condensed", Typeface.BOLD)
    }
    private val unitPaint = Paint(Paint.ANTI_ALIAS_FLAG).apply {
        color = SECONDARY_TEXT
        textAlign = Paint.Align.LEFT
        typeface = Typeface.create("sans-serif-condensed", Typeface.NORMAL)
    }
    private val labelPaint = Paint(Paint.ANTI_ALIAS_FLAG).apply {
        color = SECONDARY_TEXT
        textAlign = Paint.Align.CENTER
        textSize = 12f
        typeface = Typeface.create("sans-serif", Typeface.NORMAL)
    }
    private val iconPaint = Paint(Paint.ANTI_ALIAS_FLAG).apply {
        textAlign = Paint.Align.CENTER
        textSize = 13f
        typeface = Typeface.create("sans-serif", Typeface.BOLD)
    }
    private val statusPaint = Paint(Paint.ANTI_ALIAS_FLAG).apply {
        textSize = 10f
        typeface = Typeface.create("sans-serif", Typeface.NORMAL)
    }
    private val detailPaint = Paint(Paint.ANTI_ALIAS_FLAG).apply {
        color = SECONDARY_TEXT
        textAlign = Paint.Align.CENTER
        textSize = 9f
        typeface = Typeface.create("sans-serif-condensed", Typeface.NORMAL)
    }
    private val frameRect = RectF()
    private val arcRect = RectF()

    override fun onDraw(canvas: Canvas) {
        super.onDraw(canvas)
        val w = width.toFloat()
        val h = height.toFloat()
        if (w <= 0f || h <= 0f) return

        val frameSize = minOf(w - 10f, h - 8f)
        val frameLeft = (w - frameSize) / 2f
        frameRect.set(frameLeft, 4f, frameLeft + frameSize, 4f + frameSize)
        canvas.drawOval(frameRect, framePaint)

        drawHeader(canvas, w)

        riskPaint.color = currentRiskColor()
        canvas.drawLine(w * 0.22f, 34f, w * 0.78f, 34f, riskPaint)

        val gaugeRadius = minOf(w * 0.14f, (h - 70f) * 0.18f)
        val leftX = w * 0.25f
        val rightX = w * 0.75f
        val topY = 104f
        val bottomY = minOf(222f, h - 98f)

        drawGauge(
            canvas, leftX, topY, gaugeRadius,
            heartRate?.toString() ?: "--", "bpm", "心率", HEART_COLOR, "♥"
        )
        drawGauge(
            canvas, rightX, topY, gaugeRadius,
            coreTemp?.let { String.format(Locale.CHINA, "%.1f", it) } ?: "--.-",
            "℃", "核心", coreColor(), "△"
        )
        drawGauge(
            canvas, leftX, bottomY, gaugeRadius,
            spo2?.toString() ?: "--", "%", "血氧", SPO2_COLOR, "O₂"
        )
        drawGauge(
            canvas, rightX, bottomY, gaugeRadius,
            bloodPressureText(), "mmHg", "血压", BP_COLOR, "BP"
        )

        val detailY = h - 14f
        detailPaint.color = STEPS_COLOR
        canvas.drawText("步数 ${steps ?: "--"}", w * 0.18f, detailY, detailPaint)
        detailPaint.color = wornColor()
        canvas.drawText(wornText(), w * 0.50f, detailY, detailPaint)
        detailPaint.color = if (gpsAccuracy == null) SECONDARY_TEXT else NORMAL_COLOR
        canvas.drawText(gpsText(), w * 0.82f, detailY, detailPaint)
    }

    private fun drawHeader(canvas: Canvas, width: Float) {
        statusPaint.textAlign = Paint.Align.LEFT
        statusPaint.color = if (relayConnected) NORMAL_COLOR else CAUTION_COLOR
        canvas.drawText(if (relayConnected) "中继已连接" else "中继连接中", width * 0.28f, 22f, statusPaint)

        statusPaint.textAlign = Paint.Align.RIGHT
        statusPaint.color = SECONDARY_TEXT
        canvas.drawText("电量 ${batteryLevel?.let { "$it%" } ?: "--%"}", width * 0.72f, 22f, statusPaint)
    }

    private fun drawGauge(
        canvas: Canvas,
        centerX: Float,
        centerY: Float,
        radius: Float,
        value: String,
        unit: String,
        label: String,
        color: Int,
        icon: String
    ) {
        arcRect.set(centerX - radius, centerY - radius, centerX + radius, centerY + radius)
        canvas.drawArc(arcRect, START_ANGLE, ARC_SWEEP, false, arcBackgroundPaint)

        if (!value.startsWith("--")) {
            arcValuePaint.color = color
            canvas.drawArc(arcRect, START_ANGLE, ARC_SWEEP, false, arcValuePaint)
        }

        valuePaint.textSize = when {
            value.length >= 6 -> 17f
            value.length >= 4 -> 20f
            else -> 24f
        }
        canvas.drawText(value, centerX, centerY + 2f, valuePaint)

        unitPaint.textSize = if (unit == "mmHg") 7f else 9f
        val valueHalfWidth = valuePaint.measureText(value) / 2f
        canvas.drawText(unit, centerX + valueHalfWidth + 2f, centerY - 2f, unitPaint)

        iconPaint.color = color
        canvas.drawText(icon, centerX, centerY + radius * 0.48f, iconPaint)
        canvas.drawText(label, centerX, centerY + radius + 16f, labelPaint)
    }

    private fun bloodPressureText(): String =
        if (bpSystolic != null && bpDiastolic != null) "$bpSystolic/$bpDiastolic" else "--/--"

    private fun currentRiskColor(): Int = when {
        alertActive -> DANGER_COLOR
        coreTemp == null -> CAUTION_COLOR
        coreTemp!! >= 39.0 -> DANGER_COLOR
        coreTemp!! >= 38.0 -> WARNING_COLOR
        coreTemp!! >= 37.5 -> CAUTION_COLOR
        else -> NORMAL_COLOR
    }

    private fun coreColor(): Int = currentRiskColor()

    private fun wornText(): String = when (wornState) {
        1 -> "佩戴正常"
        0 -> "请正确佩戴"
        else -> "佩戴检测中"
    }

    private fun wornColor(): Int = when (wornState) {
        1 -> NORMAL_COLOR
        0 -> DANGER_COLOR
        else -> SECONDARY_TEXT
    }

    private fun gpsText(): String = gpsAccuracy?.let { "GPS ${it.toInt()}m" } ?: "GPS 搜索中"

    private fun refresh() {
        contentDescription = buildString {
            append(if (relayConnected) "中继已连接" else "中继连接中")
            append("，电量${batteryLevel ?: "未知"}%")
            append("，心率${heartRate ?: "无数据"}")
            append("，核心温度${coreTemp?.let { String.format(Locale.CHINA, "%.1f", it) } ?: "无数据"}")
            append("，血氧${spo2 ?: "无数据"}")
            append("，血压${bloodPressureText()}")
            append("，步数${steps ?: "无数据"}")
            append("，${wornText()}，${gpsText()}")
        }
        invalidate()
    }

    companion object {
        private const val START_ANGLE = 150f
        private const val ARC_SWEEP = 240f
        private val FRAME_COLOR = Color.rgb(52, 54, 60)
        private val ARC_BACKGROUND = Color.rgb(42, 43, 48)
        private val SECONDARY_TEXT = Color.rgb(157, 160, 166)
        private val HEART_COLOR = Color.rgb(255, 53, 152)
        private val SPO2_COLOR = Color.rgb(0, 222, 200)
        private val BP_COLOR = Color.rgb(255, 123, 46)
        private val STEPS_COLOR = Color.rgb(194, 165, 255)
        private val NORMAL_COLOR = Color.rgb(0, 230, 118)
        private val CAUTION_COLOR = Color.rgb(255, 215, 64)
        private val WARNING_COLOR = Color.rgb(255, 145, 0)
        private val DANGER_COLOR = Color.rgb(255, 23, 68)
    }
}
