import 'package:flutter/foundation.dart';
import 'package:flutter_secure_storage/flutter_secure_storage.dart';

class AuthService {
  AuthService._();

  static final AuthService instance = AuthService._();

  final FlutterSecureStorage storage = const FlutterSecureStorage();

  static const String studentIdKey = 'student_id';

  static const String passwordKey = 'student_password';

  static const String timetableCacheKey = 'timetable_cache';

  static const String timetableUpdatedAtKey = 'timetable_updated_at';

  static const String timetableSemesterKey = 'timetable_semester';

  // 포털 상태 관리
  static const String portalStatusKey = 'portal_status';
  static const String portalStatusUnlinked = 'unlinked'; // 미연동
  static const String portalStatusConnecting = 'connecting'; // 확인중
  static const String portalStatusLinked = 'linked'; // 연동됨

  /// 실시간 포털 상태 변경을 감지하는 ValueNotifier
  final ValueNotifier<String?> portalStatusNotifier = ValueNotifier<String?>(
    null,
  );

  Future<void> savePortalStatus(String status) async {
    if (status != portalStatusUnlinked &&
        status != portalStatusConnecting &&
        status != portalStatusLinked) {
      debugPrint('[AUTH] 올바르지 않은 포털 상태: $status');
      return;
    }

    await storage.write(key: portalStatusKey, value: status);
    portalStatusNotifier.value = status;

    debugPrint('[AUTH] 포털 상태 저장: $status');
  }

  Future<String?> getPortalStatus() async {
    return await storage.read(key: portalStatusKey);
  }

  Future<bool> isPortalLinked() async {
    final status = await getPortalStatus();
    return status == portalStatusLinked;
  }

  Future<void> clearPortalStatus() async {
    await storage.delete(key: portalStatusKey);
    portalStatusNotifier.value = portalStatusUnlinked;

    debugPrint('[AUTH] 포털 상태 초기화');
  }

  Future<void> saveLoginInfo({
    required String studentId,
    required String password,
  }) async {
    await storage.write(key: studentIdKey, value: studentId);

    await storage.write(key: passwordKey, value: password);

    debugPrint('로그인 정보 저장 완료');
  }

  Future<String?> getSavedId() async {
    return await storage.read(key: studentIdKey);
  }

  Future<String?> getSavedPassword() async {
    return await storage.read(key: passwordKey);
  }

  Future<bool> hasSavedLogin() async {
    final id = await getSavedId();

    final password = await getSavedPassword();

    return id != null && password != null;
  }

  Future<void> saveTimetableCache({
    required String timetableJson,
    required String semester,
  }) async {
    await storage.write(key: timetableCacheKey, value: timetableJson);

    await storage.write(key: timetableSemesterKey, value: semester);

    await storage.write(
      key: timetableUpdatedAtKey,
      value: DateTime.now().toIso8601String(),
    );

    debugPrint('시간표 캐시 저장 완료');
  }

  Future<String?> getTimetableCache() async {
    return await storage.read(key: timetableCacheKey);
  }

  Future<String?> getTimetableSemester() async {
    return await storage.read(key: timetableSemesterKey);
  }

  Future<String?> getTimetableUpdatedAt() async {
    return await storage.read(key: timetableUpdatedAtKey);
  }

  Future<bool> hasTimetableCache() async {
    final cache = await getTimetableCache();

    return cache != null;
  }

  Future<void> clearTimetableCache() async {
    await storage.delete(key: timetableCacheKey);

    await storage.delete(key: timetableSemesterKey);

    await storage.delete(key: timetableUpdatedAtKey);

    debugPrint('시간표 캐시 삭제 완료');
  }

  Future<void> logout() async {
    await storage.delete(key: studentIdKey);

    await storage.delete(key: passwordKey);

    await clearTimetableCache();

    await clearPortalStatus();

    debugPrint('로그아웃 완료');
  }
}
