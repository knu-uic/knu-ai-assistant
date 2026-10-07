package kr.ac.kongju.knupick

import kotlinx.serialization.json.Json
import kr.ac.kongju.knupick.data.weekTimetable
import kr.ac.kongju.knupick.data.timetableBlocks
import kotlin.test.*

class WeekTimetableTest {
    @Test fun calendarPreservesEmptyPeriodsAndMapsDaysByHeaderNotCellPosition() {
        val grid = weekTimetable(Json.parseToJsonElement("""[{"rows":[
          ["교시","수요일","월요일","화요일","목요일","금요일","토요일"],
          ["0교시 주간: (08:00~08:50)","","","","","",""],
          ["1교시 주간: (09:00~09:50)","운영체제(01 교수) 9공201","","","","",""],
          ["2교시 주간: (10:00~10:50)","","","","","",""],
          ["3교시 주간: (11:00~11:50)","","자료구조(01 교수) 9공101","","","",""],
          ["4교시 주간: (12:00~12:50)","","","","","",""]
        ]}]"""))
        assertEquals(listOf("월", "화", "수", "목", "금"), grid.days)
        assertEquals(listOf("1교시", "2교시", "3교시"), grid.rows.map { it.period })
        assertEquals("운영체제(01 교수)", grid.rows.first().cells[2]!!.name)
        assertEquals("9공201", grid.rows.first().cells[2]!!.room)
        assertEquals("09:00~09:50", grid.rows.first().time)
        assertTrue(grid.rows[1].cells.all { it == null })
        assertEquals("자료구조(01 교수)", grid.rows.last().cells[0]!!.name)
    }
    @Test fun weekendClassesAreIncludedAndNightPeriodsAreNotCollapsedByNumber() {
        val grid = weekTimetable(Json.parseToJsonElement("""[{"rows":[
          ["교시","월요일","토요일","일요일"],
          ["1교시 주간: (09:00~09:50)","주간 수업","주말 수업",""],
          ["1교시 야간: (18:00~18:50)","야간 수업","","일요일 수업"]
        ]}]"""))
        assertEquals(listOf("월", "화", "수", "목", "금", "토", "일"), grid.days)
        assertEquals(2, grid.rows.size)
        assertEquals("18:00~18:50", grid.rows.last().time)
        assertEquals("주말 수업", grid.rows.first().cells[5]!!.name)
        assertEquals("일요일 수업", grid.rows.last().cells[6]!!.name)
    }
    @Test fun absentOrEmptyDataDoesNotInventClasses() {
        assertTrue(weekTimetable(null).rows.isEmpty())
        assertTrue(weekTimetable(Json.parseToJsonElement("[]")).rows.isEmpty())
        assertTrue(weekTimetable(Json.parseToJsonElement("""[{"rows":[["교시","월요일"],["1교시",""]]}]""")).rows.isEmpty())
    }
    @Test fun consecutiveIdenticalClassesBecomeOneBlockWithTheirFullTimeRange() {
        val grid = weekTimetable(Json.parseToJsonElement("""[{"rows":[
          ["교시","월요일","화요일"],
          ["1교시 (09:00~09:50)","자료구조(01 교수) 9공101","다른 수업"],
          ["2교시 (10:00~10:50)","자료구조(01 교수) 9공101",""],
          ["3교시 (11:00~11:50)","자료구조(01 교수) 9공101",""]
        ]}]"""))
        val blocks = timetableBlocks(grid)
        assertEquals(2, blocks.size)
        val monday = blocks.single { it.dayIndex == 0 }
        assertEquals(0, monday.startRow)
        assertEquals(3, monday.rowSpan)
        assertEquals("1교시~3교시", monday.lesson.period)
        assertEquals("09:00~11:50", monday.lesson.time)
        assertEquals("자료구조(01 교수)", monday.lesson.name)
        assertEquals("9공101", monday.lesson.room)
        assertEquals(1, blocks.single { it.dayIndex == 1 }.rowSpan)
    }
    @Test fun emptyPeriodsRoomChangesAndDayNightGapsKeepSeparateBlocks() {
        val grid = weekTimetable(Json.parseToJsonElement("""[{"rows":[
          ["교시","월요일"],
          ["1교시 (09:00~09:50)","자료구조(01 교수) 9공101"],
          ["2교시 (10:00~10:50)",""],
          ["3교시 (11:00~11:50)","자료구조(01 교수) 9공101"],
          ["4교시 (12:00~12:50)","자료구조(01 교수) 9공102"],
          ["1교시 야간 (18:00~18:50)","자료구조(01 교수) 9공102"]
        ]}]"""))
        val blocks = timetableBlocks(grid)
        assertEquals(listOf(0, 2, 3, 4), blocks.map { it.startRow })
        assertTrue(blocks.all { it.rowSpan == 1 })
    }
    @Test fun missingOrOverlappingTimesDoNotInventAContinuousClass() {
        val grid = weekTimetable(Json.parseToJsonElement("""[{"rows":[
          ["교시","월요일"],
          ["1교시","자료구조"],
          ["2교시 (10:00~10:50)","자료구조"],
          ["3교시 (10:30~11:20)","자료구조"]
        ]}]"""))
        assertTrue(timetableBlocks(grid).all { it.rowSpan == 1 })
    }
}
