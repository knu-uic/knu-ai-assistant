/// KNU AI Assistant — FastAPI 백엔드 통신 서비스.
///
/// Flutter APP이 SERVER의 REST API와 HTTP 통신하는 계층.
/// dio 패키지를 사용하며, Singleton 패턴으로 관리.
///
/// 사용법:
///   final answer = await ApiService.instance.chat('장학금 알려줘');
///   final notices = await ApiService.instance.getNotices(category: '장학');
///   final user = await ApiService.instance.getUserProfile('20201234');
library;

import 'package:dio/dio.dart';

/// 백엔드 서버 주소. 개발 환경에서는 실제 LAN IP를 사용해야
/// 에뮬레이터/기기에서 접근 가능하다.
/// 프로덕션에서는 도메인으로 교체.
const String _defaultBaseUrl = 'http://10.0.2.2:8000'; // Android 에뮬레이터

class ApiService {
  ApiService._();

  static final ApiService instance = ApiService._();

  /// 서버 주소 (에어플레이/웹/배포 환경에 따라 변경 필요)
  String _baseUrl = _defaultBaseUrl;

  late final Dio _dio = Dio(
    BaseOptions(
      baseUrl: _baseUrl,
      connectTimeout: const Duration(seconds: 10),
      receiveTimeout: const Duration(seconds: 90), // RAG는 오래 걸릴 수 있음
      headers: {'Content-Type': 'application/json'},
    ),
  );

  /// 서버 주소 변경 (앱 설정에서 변경 가능)
  void setBaseUrl(String url) {
    _baseUrl = url;
    _dio.options.baseUrl = url;
  }

  String get baseUrl => _baseUrl;

  // ── 에러 핸들링 ──────────────────────────────────────────────

  /// 공통 에러 핸들링. 에러 메시지를 파싱해 사용자 친화적 문자열 반환.
  String _handleError(DioException e) {
    if (e.response != null) {
      final statusCode = e.response?.statusCode;
      final detail = e.response?.data?['detail'] as String?;
      return detail ?? '서버 오류 (HTTP $statusCode)';
    }
    if (e.type == DioExceptionType.connectionTimeout ||
        e.type == DioExceptionType.receiveTimeout) {
      return '서버 연결 시간 초과. 네트워크 상태를 확인해주세요.';
    }
    if (e.type == DioExceptionType.connectionError) {
      return '서버에 연결할 수 없습니다. 서버가 실행 중인지 확인해주세요.';
    }
    return '네트워크 오류: ${e.message}';
  }

  // ── 헬스체크 ────────────────────────────────────────────────

  /// 서버 연결 상태 확인
  Future<bool> checkHealth() async {
    try {
      final res = await _dio.get('/api/health');
      return res.statusCode == 200;
    } catch (_) {
      return false;
    }
  }

  // ── 챗봇 ─────────────────────────────────────────────────────

  /// AI 챗봇에 질문하고 답변 반환
  Future<ChatResult> chat(String question, {String? major}) async {
    try {
      final res = await _dio.post(
        '/api/chat',
        data: {'question': question, 'major': ?major},
      );

      final data = res.data as Map<String, dynamic>;
      return ChatResult(
        answer: data['answer'] ?? '',
        grounded: data['grounded'],
        fidelity: (data['fidelity'] as num?)?.toDouble(),
        verifierNote: data['verifier_note'],
        categories: List<String>.from(data['categories'] ?? []),
        expandedQuery: data['expanded_query'],
      );
    } on DioException catch (e) {
      throw ApiException(_handleError(e));
    }
  }

  // ── 공지사항 ─────────────────────────────────────────────────

  /// 공지사항 목록 조회
  Future<List<NoticeItem>> getNotices({
    String? category,
    String? major,
    int limit = 20,
  }) async {
    try {
      final res = await _dio.get(
        '/api/notices',
        queryParameters: {
          'category': ?category,
          'major': ?major,
          'limit': limit,
        },
      );

      final data = res.data as Map<String, dynamic>;
      final notices = (data['notices'] as List<dynamic>?) ?? [];
      return notices
          .map((n) => NoticeItem.fromJson(n as Map<String, dynamic>))
          .toList();
    } on DioException catch (e) {
      throw ApiException(_handleError(e));
    }
  }

  // ── 시간표 ──────────────────────────────────────────────────

  /// 학생 시간표 조회
  Future<TimetableResult> getTimetable(String studentId) async {
    try {
      final res = await _dio.get('/api/timetable/$studentId');
      final data = res.data as Map<String, dynamic>;
      return TimetableResult(
        timetable: data['timetable'] as Map<String, dynamic>?,
        studentId: data['student_id'] ?? studentId,
        name: data['name'],
        major: data['major'],
        year: data['year'],
      );
    } on DioException catch (e) {
      throw ApiException(_handleError(e));
    }
  }

  // ── 사용자 프로필 ──────────────────────────────────────────

  /// 사용자 프로필 조회
  Future<UserProfile> getUserProfile(String studentId) async {
    try {
      final res = await _dio.get('/api/user/$studentId');
      final data = res.data as Map<String, dynamic>;
      return UserProfile.fromJson(data);
    } on DioException catch (e) {
      throw ApiException(_handleError(e));
    }
  }

  // ── 검색 ────────────────────────────────────────────────────

  /// 의미 기반 공지 검색
  Future<List<SearchResult>> search(
    String query, {
    String? major,
    String? category,
    int limit = 10,
  }) async {
    try {
      final res = await _dio.get(
        '/api/search',
        queryParameters: {
          'q': query,
          'major': ?major,
          'category': ?category,
          'limit': limit,
        },
      );

      final data = res.data as Map<String, dynamic>;
      final results = (data['results'] as List<dynamic>?) ?? [];
      return results
          .map((r) => SearchResult.fromJson(r as Map<String, dynamic>))
          .toList();
    } on DioException catch (e) {
      throw ApiException(_handleError(e));
    }
  }

  // ── 포털 동기화 ─────────────────────────────────────────────

  /// KNUIS 포털에서 시간표/성적/졸업정보를 서버 DB로 동기화.
  ///
  /// 서버가 30~120초 걸리는 크롤링을 백그라운드 잡으로 처리하므로,
  /// 접수번호(job_id)를 받고 2초 간격으로 완료를 폴링한다.
  /// 폴링 한 번 한 번은 짧은 요청이라 와이파이↔LTE 전환 등으로
  /// 연결이 끊겨도 다음 폴링에서 자연 복구된다.
  ///
  /// [onProgress]는 "시간표 가져오는 중" 같은 진행 단계 문구를 전달한다
  /// (UI 표시용, 선택).
  Future<PortalSyncResult> syncPortal({
    required String studentId,
    required String password,
    void Function(String step)? onProgress,
  }) async {
    try {
      final startRes = await _dio.post(
        '/api/portal/sync/start',
        data: {'student_id': studentId, 'password': password},
      );
      final jobId = (startRes.data as Map<String, dynamic>)['job_id'] as String;

      // 잡 타임아웃(서버 180초) + 여유. 초과 시 루프 종료 후 예외.
      final deadline = DateTime.now().add(const Duration(seconds: 240));
      while (DateTime.now().isBefore(deadline)) {
        final res = await _dio.get('/api/portal/sync/$jobId');
        final data = res.data as Map<String, dynamic>;
        final status = data['status'] as String;

        if (status == 'done') {
          return PortalSyncResult.fromJson(
            data['result'] as Map<String, dynamic>,
          );
        }
        if (status == 'failed') {
          throw ApiException(
            (data['detail'] as String?) ?? '동기화에 실패했습니다.',
          );
        }
        final step = data['step'] as String?;
        if (step != null) onProgress?.call(step);

        await Future.delayed(const Duration(seconds: 2));
      }
      throw ApiException('동기화 시간이 초과되었습니다. 잠시 후 다시 시도해주세요.');
    } on DioException catch (e) {
      throw ApiException(_handleError(e));
    }
  }
}

// ─────────────────────────────────────────────────────────────────
// 데이터 모델
// ─────────────────────────────────────────────────────────────────

/// API 에러
class ApiException implements Exception {
  final String message;
  ApiException(this.message);
  @override
  String toString() => 'ApiException: $message';
}

/// 챗봇 답변 결과
class ChatResult {
  final String answer;
  final bool? grounded;
  final double? fidelity;
  final String? verifierNote;
  final List<String> categories;
  final String? expandedQuery;

  ChatResult({
    required this.answer,
    this.grounded,
    this.fidelity,
    this.verifierNote,
    this.categories = const [],
    this.expandedQuery,
  });
}

/// 공지사항 항목
class NoticeItem {
  final String url;
  final String title;
  final String? content;
  final String? summary;
  final String? postedAt;
  final String? startDate;
  final String? endDate;
  final String? category;
  final List<String>? target;
  final List<String>? keywords;
  final String? sourceName;

  NoticeItem({
    required this.url,
    required this.title,
    this.content,
    this.summary,
    this.postedAt,
    this.startDate,
    this.endDate,
    this.category,
    this.target,
    this.keywords,
    this.sourceName,
  });

  factory NoticeItem.fromJson(Map<String, dynamic> json) {
    return NoticeItem(
      url: json['url'] ?? '',
      title: json['title'] ?? '',
      content: json['content'],
      summary: json['summary'],
      postedAt: json['posted_at'],
      startDate: json['start_date'],
      endDate: json['end_date'],
      category: json['category'],
      target: json['target'] != null ? List<String>.from(json['target']) : null,
      keywords: json['keywords'] != null
          ? List<String>.from(json['keywords'])
          : null,
      sourceName: json['source_name'],
    );
  }
}

/// 시간표 조회 결과
class TimetableResult {
  final Map<String, dynamic>? timetable;
  final String studentId;
  final String? name;
  final String? major;
  final int? year;

  TimetableResult({
    this.timetable,
    required this.studentId,
    this.name,
    this.major,
    this.year,
  });
}

/// 사용자 프로필
class UserProfile {
  final String studentId;
  final String? name;
  final String? major;
  final int? year;
  final List<String> interests;
  final Map<String, dynamic>? timetable;
  final Map<String, dynamic>? gradeDistribution;
  final Map<String, dynamic>? cumulativeGrades;

  UserProfile({
    required this.studentId,
    this.name,
    this.major,
    this.year,
    this.interests = const [],
    this.timetable,
    this.gradeDistribution,
    this.cumulativeGrades,
  });

  factory UserProfile.fromJson(Map<String, dynamic> json) {
    return UserProfile(
      studentId: json['student_id'] ?? '',
      name: json['name'],
      major: json['major'],
      year: json['year'],
      interests: List<String>.from(json['interests'] ?? []),
      timetable: json['timetable'] as Map<String, dynamic>?,
      gradeDistribution: json['grade_distribution'] as Map<String, dynamic>?,
      cumulativeGrades: json['cumulative_grades'] as Map<String, dynamic>?,
    );
  }
}

/// 포털 동기화 결과
class PortalSyncResult {
  final bool success;
  final String message;
  final bool timetableSynced;
  final bool gradeDistributionSynced;
  final bool cumulativeGradesSynced;
  final bool graduationSynced;

  PortalSyncResult({
    required this.success,
    required this.message,
    this.timetableSynced = false,
    this.gradeDistributionSynced = false,
    this.cumulativeGradesSynced = false,
    this.graduationSynced = false,
  });

  factory PortalSyncResult.fromJson(Map<String, dynamic> json) {
    return PortalSyncResult(
      success: json['success'] ?? false,
      message: json['message'] ?? '',
      timetableSynced: json['timetable_synced'] ?? false,
      gradeDistributionSynced: json['grade_distribution_synced'] ?? false,
      cumulativeGradesSynced: json['cumulative_grades_synced'] ?? false,
      graduationSynced: json['graduation_synced'] ?? false,
    );
  }
}

/// 검색 결과
class SearchResult {
  final String url;
  final String title;
  final String? snippet;
  final double score;
  final String? postedAt;
  final String? startDate;
  final String? endDate;
  final String? category;
  final String? summary;

  SearchResult({
    required this.url,
    required this.title,
    this.snippet,
    this.score = 0.0,
    this.postedAt,
    this.startDate,
    this.endDate,
    this.category,
    this.summary,
  });

  factory SearchResult.fromJson(Map<String, dynamic> json) {
    return SearchResult(
      url: json['url'] ?? '',
      title: json['title'] ?? '',
      snippet: json['snippet'],
      score: (json['score'] as num?)?.toDouble() ?? 0.0,
      postedAt: json['posted_at'],
      startDate: json['start_date'],
      endDate: json['end_date'],
      category: json['category'],
      summary: json['summary'],
    );
  }
}
