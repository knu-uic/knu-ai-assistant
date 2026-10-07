package kr.ac.kongju.knupick.ui

import androidx.compose.foundation.Canvas
import androidx.compose.foundation.background
import androidx.compose.foundation.border
import androidx.compose.foundation.clickable
import androidx.compose.foundation.layout.*
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.material3.*
import androidx.compose.runtime.*
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clip
import androidx.compose.ui.geometry.Offset
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.semantics.contentDescription
import androidx.compose.ui.semantics.semantics
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.text.style.TextOverflow
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import kr.ac.kongju.knupick.data.*

private val courseColors = listOf(Color(0xFFE1EDFF), Color(0xFFE2F3EA), Color(0xFFFFEEDB), Color(0xFFECE5FF), Color(0xFFFFE4EB))

/** A bounded calendar: the entire week shares the actual remaining screen height. */
@Composable internal fun WeekCalendar(grid: WeekTimetable, modifier: Modifier = Modifier) {
    val blocks = remember(grid) { timetableBlocks(grid) }
    var selected by remember(grid) { mutableStateOf<Lesson?>(null) }
    selected?.let { lesson ->
        AlertDialog(onDismissRequest = { selected = null }, title = { Text(lesson.name) },
            text = { Column(verticalArrangement = Arrangement.spacedBy(12.dp)) {
                Text("${lesson.day}요일 · ${lesson.period}")
                Text(lesson.time.ifBlank { "시간 정보 없음" })
                Text(lesson.room.ifBlank { "강의실 정보 없음" })
            } }, confirmButton = { TextButton(onClick = { selected = null }) { Text("닫기") } })
    }
    Column(modifier.clip(RoundedCornerShape(12.dp)).background(Color.White)
        .border(1.dp, Color(0xFFE2E8F1), RoundedCornerShape(12.dp))) {
        Row(Modifier.fillMaxWidth().height(32.dp).background(Soft), verticalAlignment = Alignment.CenterVertically) {
            Box(Modifier.width(42.dp), contentAlignment = Alignment.Center) { Text("교시", color = Muted, fontSize = 10.sp) }
            grid.days.forEach { day -> Box(Modifier.weight(1f), contentAlignment = Alignment.Center) {
                Text(day, color = Blue, fontSize = 12.sp, fontWeight = FontWeight.Bold)
            } }
        }
        if (grid.rows.isEmpty()) return@Column
        Row(Modifier.weight(1f).fillMaxWidth()) {
            Column(Modifier.width(42.dp).fillMaxHeight()) {
                grid.rows.forEach { row -> Box(Modifier.weight(1f).fillMaxWidth().border(.5.dp, Color(0xFFEEF2F7)),
                    contentAlignment = Alignment.Center) {
                    Column(horizontalAlignment = Alignment.CenterHorizontally) {
                        Text(row.period, fontSize = 9.sp, fontWeight = FontWeight.SemiBold, color = Muted, maxLines = 1)
                        Text(row.time.substringBefore('~'), fontSize = 8.sp, color = Muted, maxLines = 1)
                    }
                } }
            }
            grid.days.indices.forEach { day ->
                BoxWithConstraints(Modifier.weight(1f).fillMaxHeight()) {
                    val slotHeight = maxHeight / grid.rows.size
                    Canvas(Modifier.fillMaxSize()) {
                        val step = size.height / grid.rows.size
                        for (index in 0..grid.rows.size) drawLine(Color(0xFFEEF2F7),
                            Offset(0f, step * index), Offset(size.width, step * index), 1.dp.toPx())
                        drawLine(Color(0xFFEEF2F7), Offset.Zero, Offset(0f, size.height), 1.dp.toPx())
                    }
                    blocks.filter { it.dayIndex == day }.forEach { block ->
                        val lesson = block.lesson
                        val height = slotHeight * block.rowSpan
                        val key = lesson.name.substringBefore('(').trim()
                        Column(Modifier.offset(y = slotHeight * block.startRow).height(height).fillMaxWidth().padding(2.dp)
                            .clip(RoundedCornerShape(5.dp)).background(courseColors[key.hashCode().ushr(1) % courseColors.size])
                            .clickable { selected = lesson }
                            .semantics { contentDescription = "${lesson.day}요일 ${lesson.period} ${lesson.time}, ${lesson.name}, ${lesson.room}" }
                            .padding(horizontal = 4.dp, vertical = 3.dp), verticalArrangement = Arrangement.spacedBy(2.dp)) {
                            Text(key, color = Ink, fontSize = if (grid.days.size > 5) 9.sp else 10.sp,
                                lineHeight = 12.sp, fontWeight = FontWeight.SemiBold,
                                maxLines = if (height < 34.dp) 1 else if (height < 62.dp) 2 else 4, overflow = TextOverflow.Ellipsis)
                            if (lesson.room.isNotBlank() && height >= 54.dp) Text(lesson.room, color = Muted,
                                fontSize = 8.sp, lineHeight = 10.sp, maxLines = 2, overflow = TextOverflow.Ellipsis)
                        }
                    }
                }
            }
        }
    }
}
