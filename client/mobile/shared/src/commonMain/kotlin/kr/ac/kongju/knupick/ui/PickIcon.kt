package kr.ac.kongju.knupick.ui

import androidx.compose.foundation.Canvas
import androidx.compose.foundation.layout.size
import androidx.compose.runtime.Composable
import androidx.compose.material3.LocalContentColor
import androidx.compose.ui.Modifier
import androidx.compose.ui.geometry.CornerRadius
import androidx.compose.ui.geometry.Offset
import androidx.compose.ui.geometry.Size
import androidx.compose.ui.graphics.Path
import androidx.compose.ui.graphics.StrokeCap
import androidx.compose.ui.graphics.drawscope.Stroke
import androidx.compose.ui.unit.dp

/** Small code-native outline icons, shared by Android and iOS. */
@Composable fun PickIcon(kind: Int) {
    val color = LocalContentColor.current
    Canvas(Modifier.size(24.dp)) {
        val scale = size.width / 24
        val line = 1.8f * scale
        fun point(x: Float, y: Float) = Offset(x * scale, y * scale)
        fun segment(x: Float, y: Float, xx: Float, yy: Float) = drawLine(color, point(x, y), point(xx, yy), line, StrokeCap.Round)
        when (kind) {
            0 -> {
                val p = Path().apply { moveTo(3 * scale, 10 * scale); lineTo(12 * scale, 3 * scale); lineTo(21 * scale, 10 * scale) }
                drawPath(p, color, style = Stroke(line, cap = StrokeCap.Round))
                segment(5f, 9f, 5f, 21f); segment(5f, 21f, 19f, 21f); segment(19f, 21f, 19f, 9f)
                segment(10f, 21f, 10f, 14f); segment(10f, 14f, 14f, 14f); segment(14f, 14f, 14f, 21f)
            }
            1 -> {
                drawRoundRect(color, point(4f, 3f), Size(16 * scale, 18 * scale), CornerRadius(2 * scale), style = Stroke(line))
                segment(8f, 8f, 16f, 8f); segment(8f, 12f, 16f, 12f); segment(8f, 16f, 13f, 16f)
            }
            2 -> {
                drawRoundRect(color, point(3f, 4f), Size(18 * scale, 14 * scale), CornerRadius(4 * scale), style = Stroke(line))
                segment(7f, 18f, 5f, 21f); segment(5f, 21f, 11f, 18f)
                listOf(8f, 12f, 16f).forEach { drawCircle(color, 1 * scale, point(it, 11f)) }
            }
            3 -> {
                drawRoundRect(color, point(3f, 5f), Size(18 * scale, 16 * scale), CornerRadius(2 * scale), style = Stroke(line))
                segment(3f, 10f, 21f, 10f); segment(8f, 3f, 8f, 7f); segment(16f, 3f, 16f, 7f)
                listOf(7f, 12f, 17f).forEach { drawCircle(color, 1 * scale, point(it, 15f)) }
            }
            5 -> { segment(4f, 6f, 20f, 6f); segment(4f, 12f, 20f, 12f); segment(4f, 18f, 20f, 18f) }
            6 -> { segment(6f, 6f, 18f, 18f); segment(6f, 18f, 18f, 6f) }
            else -> {
                drawCircle(color, 4 * scale, point(12f, 7f), style = Stroke(line))
                drawArc(color, 180f, 180f, false, point(4f, 14f), Size(16 * scale, 14 * scale), style = Stroke(line))
            }
        }
    }
}
