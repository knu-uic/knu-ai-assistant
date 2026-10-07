package kr.ac.kongju.knupick.data

import kotlinx.serialization.json.*

data class Lesson(val day: String, val period: String, val time: String, val name: String, val room: String)
data class WeekTimetableRow(val period: String, val time: String, val cells: List<Lesson?>)
data class WeekTimetable(val days: List<String>, val rows: List<WeekTimetableRow>)
data class TimetableBlock(val dayIndex: Int, val startRow: Int, val rowSpan: Int, val lesson: Lesson)
data class CreditRow(val label: String, val standard: String, val taken: String, val deficit: String)
data class GradeGrid(val title: String, val columns: List<String>, val rows: List<List<String>>)

private fun JsonElement?.text(): String = (this as? JsonPrimitive)?.contentOrNull.orEmpty()

/** Merge only identical courses in adjacent real time slots, not across empty hours or day/night gaps. */
fun timetableBlocks(grid: WeekTimetable): List<TimetableBlock> = buildList {
    fun minutes(time: String): Int? {
        val parts = time.trim().split(':')
        if (parts.size != 2) return null
        val hour = parts[0].toIntOrNull() ?: return null
        val minute = parts[1].toIntOrNull() ?: return null
        return if (hour in 0..23 && minute in 0..59) hour * 60 + minute else null
    }
    grid.days.indices.forEach { day ->
        var index = 0
        while (index < grid.rows.size) {
            val first = grid.rows[index].cells.getOrNull(day)
            if (first == null) { index++; continue }
            var last = index
            while (last + 1 < grid.rows.size) {
                val next = grid.rows[last + 1].cells.getOrNull(day) ?: break
                val previous = grid.rows[last].cells.getOrNull(day)!!
                val end = minutes(previous.time.substringAfter('~', "")) ?: break
                val start = minutes(next.time.substringBefore('~')) ?: break
                if (first.name != next.name || first.room != next.room || start - end !in 0..20) break
                last++
            }
            val end = grid.rows[last].cells[day]!!
            val lesson = if (index == last) first else first.copy(period = "${first.period}~${end.period}",
                time = "${first.time.substringBefore('~')}~${end.time.substringAfter('~')}")
            add(TimetableBlock(day, index, last - index + 1, lesson))
            index = last + 1
        }
    }
}

/** Keep empty periods between classes; include weekends only when they contain classes. */
fun weekTimetable(data: JsonElement?): WeekTimetable {
    val rows = ((data as? JsonArray)?.firstOrNull() as? JsonObject)?.get("rows") as? JsonArray
        ?: return WeekTimetable(listOf("월", "화", "수", "목", "금"), emptyList())
    val header = (rows.firstOrNull() as? JsonArray)?.map { it.text() }.orEmpty()
    val columns = header.mapIndexedNotNull { index, value ->
        if (index == 0) null else value.firstOrNull { it in "월화수목금토일" }?.let { it.toString() to index }
    }.toMap()
    val days = listOf("월", "화", "수", "목", "금") + listOf("토", "일").filter { day ->
        val index = columns[day] ?: return@filter false
        rows.drop(1).any { (it as? JsonArray)?.getOrNull(index).text().isNotBlank() }
    }
    val all = rows.drop(1).mapNotNull { raw ->
        val row = raw as? JsonArray ?: return@mapNotNull null
        val periodRaw = row.firstOrNull().text()
        val period = Regex("(\\d+)\\s*교시").find(periodRaw)?.value ?: periodRaw.trim()
        val time = Regex("\\d{1,2}:\\d{2}\\s*~\\s*\\d{1,2}:\\d{2}").find(periodRaw)?.value.orEmpty().replace(" ", "")
        WeekTimetableRow(period, time, days.map { day ->
            val name = columns[day]?.let { row.getOrNull(it).text().trim() }.orEmpty()
            if (name.isEmpty()) null else {
                val split = Regex("^(.*\\))\\s*(.+)$").matchEntire(name)
                Lesson(day, period, time, split?.groupValues?.get(1) ?: name, split?.groupValues?.get(2).orEmpty())
            }
        })
    }
    val first = all.indexOfFirst { row -> row.cells.any { it != null } }
    val last = all.indexOfLast { row -> row.cells.any { it != null } }
    return WeekTimetable(days, if (first < 0) emptyList() else all.subList(first, last + 1))
}

/** Read the portal's original rows without assigning a guessed weekday. */
fun parseTimetable(data: JsonElement?): List<Lesson> {
    val rows = ((data as? JsonArray)?.firstOrNull() as? JsonObject)?.get("rows") as? JsonArray ?: return emptyList()
    val header = (rows.firstOrNull() as? JsonArray)?.map { it.text() } ?: return emptyList()
    return rows.drop(1).flatMap { raw ->
        val row = raw as? JsonArray ?: return@flatMap emptyList()
        val period = row.firstOrNull().text()
        header.mapIndexedNotNull { index, day ->
            if (index == 0 || day.none { it in "월화수목금토일" }) return@mapIndexedNotNull null
            val name = row.getOrNull(index).text().trim()
            if (name.isEmpty()) return@mapIndexedNotNull null
            val split = Regex("^(.*\\))\\s*(.+)$").matchEntire(name)
            Lesson(day.replace("요일", ""),
                Regex("(\\d+)\\s*교시").find(period)?.value ?: period.trim(),
                Regex("\\d{1,2}:\\d{2}\\s*~\\s*\\d{1,2}:\\d{2}").find(period)?.value.orEmpty(),
                split?.groupValues?.get(1) ?: name, split?.groupValues?.get(2).orEmpty())
        }
    }
}

fun parseCredits(data: JsonObject?): List<CreditRow> {
    val result = mutableListOf<CreditRow>()
    fun visit(node: JsonObject, path: List<String>) {
        if ("기준" in node || "취득" in node) {
            val standard = node["기준"].text().ifEmpty { "0" }
            val taken = node["취득"].text().ifEmpty { "0" }
            val deficit = maxOf(0.0, (standard.toDoubleOrNull() ?: 0.0) - (taken.toDoubleOrNull() ?: 0.0))
            result += CreditRow(path.joinToString(" · "), standard, taken,
                if (deficit % 1.0 == 0.0) deficit.toInt().toString() else deficit.toString())
        } else node.forEach { (key, value) -> if (value is JsonObject) visit(value, path + key) }
    }
    if (data != null) visit(data, emptyList())
    return result
}

fun parseGrades(data: JsonObject?): List<GradeGrid> =
    ((data?.get("grids") as? JsonObject)?.values ?: emptyList()).mapNotNull { raw ->
        val grid = raw as? JsonObject ?: return@mapNotNull null
        GradeGrid(grid["title"].text(), (grid["columns"] as? JsonArray)?.map { it.text() }.orEmpty(),
            (grid["rows"] as? JsonArray)?.mapNotNull { (it as? JsonArray)?.map { cell -> cell.text() } }.orEmpty())
    }
