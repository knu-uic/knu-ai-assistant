/// 시간표 화면 — 서버 DB + 로컬 캐시 fallback.
library;

import 'dart:convert';
import 'package:flutter/material.dart';
import 'package:flutter_secure_storage/flutter_secure_storage.dart';

import '../services/auth_service.dart';
import '../services/api_service.dart';

class TimetableScreen extends StatefulWidget {
  const TimetableScreen({super.key});

  @override
  State<TimetableScreen> createState() => _TimetableScreenState();
}

class _TimetableScreenState extends State<TimetableScreen> {
  bool isLoading = true;
  Map<String, dynamic>? timetable;

  @override
  void initState() {
    super.initState();
    loadTimetable();
  }

  Future<void> loadTimetable() async {
    try {
      // 1차: 서버 DB에서 시간표 가져오기
      final id = await AuthService.instance.getSavedId();
      if (id != null) {
        try {
          final result = await ApiService.instance.getTimetable(id);
          if (result.timetable != null && mounted) {
            setState(() {
              timetable = result.timetable;
              isLoading = false;
            });
            return;
          }
        } catch (e) {
          // 서버 조회 실패 시 로컬 캐시로 fallback
        }
      }

      // 2차: 로컬 SecureStorage 캐시에서 읽기
      const storage = FlutterSecureStorage();
      final raw = await storage.read(key: AuthService.timetableCacheKey);

      if (raw == null) {
        throw Exception('저장된 시간표가 없습니다.\n포털 동기화를 먼저 실행해주세요.');
      }

      final decoded = jsonDecode(raw) as Map<String, dynamic>;

      if (!mounted) return;

      setState(() {
        timetable = decoded;
        isLoading = false;
      });
    } catch (e) {
      if (!mounted) return;

      setState(() {
        timetable = {'error': '시간표 로딩 실패\n\n$e'};
        isLoading = false;
      });
    }
  }

  static const Map<String, Color> _dayColors = {
    'MON': Color(0xFFE53935),
    'TUE': Color(0xFFFB8C00),
    'WED': Color(0xFF43A047),
    'THU': Color(0xFF1E88E5),
    'FRI': Color(0xFF8E24AA),
  };

  @override
  Widget build(BuildContext context) {
    final isDark = Theme.of(context).brightness == Brightness.dark;

    return Scaffold(
      appBar: AppBar(title: const Text('시간표'), centerTitle: true),
      body: SafeArea(
        child: Padding(
          padding: const EdgeInsets.all(16),
          child: Column(
            crossAxisAlignment: CrossAxisAlignment.start,
            children: [
              Container(
                width: double.infinity,
                padding: const EdgeInsets.all(20),
                decoration: BoxDecoration(
                  color: isDark ? Colors.grey.shade800 : Colors.white,
                  borderRadius: BorderRadius.circular(16),
                  boxShadow: [BoxShadow(color: Colors.black12, blurRadius: 6)],
                ),
                child: Column(
                  crossAxisAlignment: CrossAxisAlignment.start,
                  children: [
                    Text(
                      '캐시된 시간표',
                      style: TextStyle(
                        fontSize: 20,
                        fontWeight: FontWeight.bold,
                        color: isDark ? Colors.white : null,
                      ),
                    ),
                    const SizedBox(height: 8),
                    Text(
                      '저장된 시간표 데이터를 표시합니다.',
                      style: TextStyle(
                        color: isDark ? Colors.grey.shade400 : Colors.grey,
                      ),
                    ),
                  ],
                ),
              ),
              const SizedBox(height: 20),
              Expanded(
                child: Container(
                  width: double.infinity,
                  padding: const EdgeInsets.all(16),
                  decoration: BoxDecoration(
                    color: isDark ? Colors.grey.shade800 : Colors.white,
                    borderRadius: BorderRadius.circular(16),
                    boxShadow: [
                      BoxShadow(color: Colors.black12, blurRadius: 6),
                    ],
                  ),
                  child: isLoading
                      ? const Center(child: CircularProgressIndicator())
                      : _buildTimetableTable(isDark),
                ),
              ),
            ],
          ),
        ),
      ),
    );
  }

  Widget _buildTimetableTable(bool isDark) {
    if (timetable == null) {
      return const Center(child: Text('시간표 데이터 없음'));
    }

    if (timetable!.containsKey('error')) {
      return Center(child: Text(timetable!['error'].toString()));
    }

    final rawTimeList = timetable!['LTTM_CD'];
    final timeList = rawTimeList is List
        ? rawTimeList.map((e) => e.toString()).toList()
        : <String>[];

    const days = ['MON', 'TUE', 'WED', 'THU', 'FRI'];
    const dayLabels = {
      'MON': '월',
      'TUE': '화',
      'WED': '수',
      'THU': '목',
      'FRI': '금',
    };

    return SingleChildScrollView(
      scrollDirection: Axis.horizontal,
      child: SingleChildScrollView(
        child: DataTable(
          headingRowHeight: 56,
          dataRowMinHeight: 72,
          dataRowMaxHeight: 120,
          columnSpacing: 20,
          dividerThickness: 0.7,
          headingRowColor: WidgetStatePropertyAll(
            isDark ? Colors.grey.shade700 : const Color(0xFFF5F5F5),
          ),
          columns: [
            const DataColumn(label: Text('교시')),
            ...days.map(
              (day) => DataColumn(
                label: Text(
                  dayLabels[day]!,
                  style: TextStyle(
                    fontWeight: FontWeight.bold,
                    color: _dayColors[day],
                  ),
                ),
              ),
            ),
          ],
          rows: List.generate(timeList.length, (index) {
            return DataRow(
              cells: [
                DataCell(
                  SizedBox(
                    width: 140,
                    child: Text(
                      timeList[index].replaceAll('<br>', '\n'),
                      style: const TextStyle(
                        fontSize: 12,
                        fontWeight: FontWeight.bold,
                      ),
                    ),
                  ),
                ),
                ...days.map((day) {
                  final rawDayData = timetable![day];
                  final dayData = rawDayData is List
                      ? rawDayData.map((e) => e.toString()).toList()
                      : <String>[];
                  final value = index < dayData.length ? dayData[index] : '';
                  final isEmpty = value.isEmpty || value == '-';
                  return DataCell(
                    SizedBox(
                      width: 180,
                      child: isEmpty
                          ? const Text(
                              '',
                              style: TextStyle(
                                fontSize: 13,
                                height: 1.4,
                                color: Colors.transparent,
                              ),
                            )
                          : Text(
                              value.replaceAll('\\n', '\n'),
                              style: TextStyle(
                                fontSize: 13,
                                height: 1.4,
                                color: isDark ? Colors.white : null,
                              ),
                            ),
                    ),
                  );
                }),
              ],
            );
          }),
        ),
      ),
    );
  }
}
