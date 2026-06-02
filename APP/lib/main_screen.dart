/// 메인 화면 — 하단 네비게이션으로 홈/시간표/챗봇 탭 전환 + 포털 WebView 관리.
library;

import 'package:flutter/material.dart';

import 'services/auth_service.dart';
import 'widgets/hidden_portal_webview.dart';
import 'settings_screen.dart';
import 'screens/home_screen.dart';
import 'screens/timetable_screen.dart';
import 'screens/chatbot_screen.dart';

class MainScreen extends StatefulWidget {
  const MainScreen({super.key});

  @override
  State<MainScreen> createState() => _MainScreenState();
}

class _MainScreenState extends State<MainScreen> {
  int currentIndex = 0;
  int timetableVersion = 0;
  String? portalStatus;

  // HiddenPortalWebView 관련 상태
  bool _triggerLogin = false;
  bool _sessionRefreshTrigger = false;
  String _loginStudentId = '';
  String _loginPassword = '';

  /// WebView 인스턴스를 캐싱하여 탭 이동 시 재생성/재로그인 방지
  Widget? _cachedWebView;

  @override
  void initState() {
    super.initState();
    _loadPortalStatus();

    // AuthService의 portalStatus 변경 실시간 감지
    AuthService.instance.portalStatusNotifier.addListener(
      _onPortalStatusChanged,
    );
  }

  @override
  void dispose() {
    AuthService.instance.portalStatusNotifier.removeListener(
      _onPortalStatusChanged,
    );
    super.dispose();
  }

  void _onPortalStatusChanged() {
    if (mounted) {
      final newStatus = AuthService.instance.portalStatusNotifier.value;
      if (newStatus != null && newStatus != portalStatus) {
        setState(() {
          portalStatus = newStatus;
        });
      }
    }
  }

  Future<void> _loadPortalStatus() async {
    final status = await AuthService.instance.getPortalStatus();
    final hasCredentials = await AuthService.instance.hasSavedLogin();

    if (mounted) {
      setState(() {
        portalStatus = status ?? AuthService.portalStatusUnlinked;
      });
    }

    // 저장된 credentials가 있으면 status와 관계없이 WebView 실행
    if (hasCredentials) {
      final id = await AuthService.instance.getSavedId();
      final password = await AuthService.instance.getSavedPassword();
      if (id != null && password != null && mounted) {
        setState(() {
          _loginStudentId = id;
          _loginPassword = password;
          if (status == AuthService.portalStatusLinked) {
            _sessionRefreshTrigger = true;
            _triggerLogin = true;
          } else {
            _sessionRefreshTrigger = false;
            _triggerLogin = true;
          }
        });
      }
    }
  }

  String _getPortalStatusEmoji() {
    switch (portalStatus) {
      case AuthService.portalStatusConnecting:
        return '🟡';
      case AuthService.portalStatusLinked:
        return '🟢';
      default:
        return '🔴';
    }
  }

  String _getPortalStatusText() {
    switch (portalStatus) {
      case AuthService.portalStatusConnecting:
        return '연동중..';
      case AuthService.portalStatusLinked:
        return '연동완료';
      default:
        return '미연동';
    }
  }

  void refreshTimetable() {
    setState(() {
      timetableVersion++;
    });
  }

  /// 설정 화면 열기 (push route)
  void _openSettings() {
    Navigator.push(
      context,
      MaterialPageRoute(
        builder: (_) => SettingsScreen(
          portalStatus: portalStatus ?? AuthService.portalStatusUnlinked,
          onPortalStatusChanged: () {
            _loadPortalStatus();
          },
          onStartPortalConnect: _startPortalConnect,
        ),
      ),
    );
  }

  /// 설정 화면에서 포털 계정 연동 버튼 클릭 시 호출
  void _startPortalConnect(String studentId, String password) {
    // 새 계정 정보로 WebView 재생성 필요 → 캐시 초기화
    _cachedWebView = null;
    setState(() {
      _loginStudentId = studentId;
      _loginPassword = password;
      _triggerLogin = true;
      _sessionRefreshTrigger = false;
    });
  }

  /// WebView가 필요할 때 한 번만 생성하여 캐싱
  void _ensureWebView() {
    if (_cachedWebView != null) return;
    if (_loginStudentId.isEmpty || _loginPassword.isEmpty) return;

    _cachedWebView = HiddenPortalWebView(
      key: ValueKey('portal_webview_$_loginStudentId'),
      studentId: _loginStudentId,
      password: _loginPassword,
      triggerLogin: _triggerLogin,
      silentRefresh: _sessionRefreshTrigger,
      onWebViewReady: () {
        debugPrint('[MainScreen] WebView 준비 완료');
      },
      onLoginSuccess: _onLoginSuccess,
      onLoginFailed: _onLoginFailed,
    );
  }

  void _onLoginSuccess() {
    debugPrint('[MainScreen] 포털 연동 성공');
    setState(() {
      portalStatus = AuthService.portalStatusLinked;
    });
    if (mounted) {
      ScaffoldMessenger.of(
        context,
      ).showSnackBar(const SnackBar(content: Text('포털 계정 연동이 완료되었습니다.')));
    }
  }

  void _onLoginFailed(String error) {
    debugPrint('[MainScreen] 포털 연동 실패: $error');
    setState(() {
      portalStatus = AuthService.portalStatusUnlinked;
    });
    AuthService.instance.savePortalStatus(AuthService.portalStatusUnlinked);
    if (mounted) {
      ScaffoldMessenger.of(
        context,
      ).showSnackBar(SnackBar(content: Text('포털 계정 연동 실패: $error')));
    }
  }

  @override
  Widget build(BuildContext context) {
    // WebView가 필요한 상태면 캐싱 실행
    if (_loginStudentId.isNotEmpty && _loginPassword.isNotEmpty) {
      _ensureWebView();
    }

    return Scaffold(
      body: Stack(
        children: [
          [
            HomeScreen(
              portalEmoji: _getPortalStatusEmoji(),
              portalText: _getPortalStatusText(),
              onSettingsTap: _openSettings,
            ),
            TimetableScreen(key: ValueKey(timetableVersion)),
            const ChatbotScreen(),
          ][currentIndex],

          // 캐싱된 WebView 사용 (null이면 미표시)
          ?_cachedWebView,
        ],
      ),

      bottomNavigationBar: BottomNavigationBar(
        currentIndex: currentIndex,
        onTap: (index) {
          setState(() {
            currentIndex = index;
            if (index == 1) {
              timetableVersion++;
            }
          });
        },
        items: const [
          BottomNavigationBarItem(icon: Icon(Icons.home), label: '홈'),
          BottomNavigationBarItem(
            icon: Icon(Icons.calendar_month),
            label: '시간표',
          ),
          BottomNavigationBarItem(icon: Icon(Icons.smart_toy), label: '챗봇'),
        ],
      ),
    );
  }
}
