// 일회성 라이브 통합 테스트 — 로컬 API+워커+redis+db 필요.
// 실행:
//   flutter test test/portal_sync_live_test.dart \
//     --dart-define=PORTAL_ID=... --dart-define=PORTAL_PW=... --dart-define=JWT=...
// 자격증명이 없으면 자동 skip.
import 'package:flutter_test/flutter_test.dart';
import 'package:knu_app/services/api_service.dart';

const portalId = String.fromEnvironment('PORTAL_ID');
const portalPw = String.fromEnvironment('PORTAL_PW');
const jwt = String.fromEnvironment('JWT');

void main() {
  test(
    'syncPortal live: start → 폴링 → done',
    () async {
      final api = ApiService.instance;
      api.setBaseUrl('http://127.0.0.1:8000');
      api.setAuthToken(jwt);

      final steps = <String>[];
      final result = await api.syncPortal(
        studentId: portalId,
        password: portalPw,
        onProgress: (s) {
          if (steps.isEmpty || steps.last != s) {
            steps.add(s);
            // ignore: avoid_print
            print('[progress] $s');
          }
        },
      );

      // ignore: avoid_print
      print('result: success=${result.success}, message=${result.message}');
      expect(result.success, isTrue);
      expect(result.timetableSynced, isTrue);
      expect(steps, isNotEmpty);
    },
    skip: portalId.isEmpty ? '자격증명 미제공 — 라이브 테스트 skip' : false,
    timeout: const Timeout(Duration(minutes: 5)),
  );
}
