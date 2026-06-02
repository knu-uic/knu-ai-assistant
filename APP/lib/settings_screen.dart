import 'package:flutter/material.dart';
import 'services/auth_service.dart';
import 'services/theme_service.dart';

class SettingsScreen extends StatefulWidget {
  final String portalStatus;
  final VoidCallback onPortalStatusChanged;
  final Function(String studentId, String password) onStartPortalConnect;

  const SettingsScreen({
    super.key,
    required this.portalStatus,
    required this.onPortalStatusChanged,
    required this.onStartPortalConnect,
  });

  @override
  State<SettingsScreen> createState() => _SettingsScreenState();
}

class _SettingsScreenState extends State<SettingsScreen> {
  final TextEditingController _idController = TextEditingController();
  final TextEditingController _passwordController = TextEditingController();
  String? _errorMessage;

  /// 실시간 상태 반영 (AuthService notifier 구독)
  String _currentStatus = '';

  @override
  void initState() {
    super.initState();
    _currentStatus = widget.portalStatus;
    _loadSavedCredentials();

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
    _idController.dispose();
    _passwordController.dispose();
    super.dispose();
  }

  void _onPortalStatusChanged() {
    if (mounted) {
      final newStatus = AuthService.instance.portalStatusNotifier.value;
      if (newStatus != null && newStatus != _currentStatus) {
        setState(() {
          _currentStatus = newStatus;
        });
      }
    }
  }

  Future<void> _loadSavedCredentials() async {
    final id = await AuthService.instance.getSavedId();
    final password = await AuthService.instance.getSavedPassword();

    if (mounted) {
      setState(() {
        _idController.text = id ?? '';
        _passwordController.text = password ?? '';
      });
    }
  }

  Future<void> _connectPortal() async {
    final id = _idController.text.trim();
    final password = _passwordController.text.trim();

    if (id.isEmpty || password.isEmpty) {
      setState(() {
        _errorMessage = '학번과 비밀번호를 입력해주세요.';
      });
      return;
    }

    setState(() {
      _errorMessage = null;
    });

    // 포털 상태를 '확인중'으로 변경 (notifier를 통해 자동 동기화됨)
    await AuthService.instance.savePortalStatus(
      AuthService.portalStatusConnecting,
    );
    await AuthService.instance.saveLoginInfo(studentId: id, password: password);

    widget.onPortalStatusChanged();

    // MainScreen의 HiddenPortalWebView를 통해 로그인 실행
    widget.onStartPortalConnect(id, password);
  }

  Future<void> _disconnect() async {
    await AuthService.instance.clearPortalStatus();
    await AuthService.instance.logout();

    widget.onPortalStatusChanged();

    if (mounted) {
      setState(() {
        _idController.clear();
        _passwordController.clear();
      });

      ScaffoldMessenger.of(
        context,
      ).showSnackBar(const SnackBar(content: Text('포털 계정 연동을 해제했습니다.')));
    }
  }

  String _getPortalStatusEmoji() {
    switch (_currentStatus) {
      case AuthService.portalStatusConnecting:
        return '🟡';
      case AuthService.portalStatusLinked:
        return '🟢';
      default:
        return '🔴';
    }
  }

  String _getPortalStatusText() {
    switch (_currentStatus) {
      case AuthService.portalStatusConnecting:
        return '연동중..';
      case AuthService.portalStatusLinked:
        return '연동완료';
      default:
        return '미연동';
    }
  }

  @override
  Widget build(BuildContext context) {
    final bool isLinked = _currentStatus == AuthService.portalStatusLinked;
    final bool isConnecting =
        _currentStatus == AuthService.portalStatusConnecting;
    final bool showLoginForm = !isLinked && !isConnecting; // 미연동 상태일 때만 로그인폼 표시

    return Scaffold(
      appBar: AppBar(
        leading: IconButton(
          icon: const Icon(Icons.arrow_back),
          onPressed: () => Navigator.pop(context),
        ),
        title: const Text('설정'),
        centerTitle: true,
        actions: [
          Padding(
            padding: const EdgeInsets.only(right: 16),
            child: Center(
              child: Text(
                '${_getPortalStatusEmoji()} ${_getPortalStatusText()}',
                style: const TextStyle(fontSize: 14),
              ),
            ),
          ),
        ],
      ),
      body: SafeArea(
        child: Padding(
          padding: const EdgeInsets.all(20),
          child: Column(
            crossAxisAlignment: CrossAxisAlignment.start,
            children: [
              // 포털 연동 상태 (개선된 UI)
              Container(
                width: double.infinity,
                padding: const EdgeInsets.all(16),
                decoration: BoxDecoration(
                  color: isLinked
                      ? Colors.green.shade50
                      : isConnecting
                      ? Colors.orange.shade50
                      : Colors.white,
                  borderRadius: BorderRadius.circular(12),
                  border: isLinked
                      ? Border.all(color: Colors.green.shade200)
                      : isConnecting
                      ? Border.all(color: Colors.orange.shade200)
                      : null,
                  boxShadow: [BoxShadow(color: Colors.black12, blurRadius: 4)],
                ),
                child: Column(
                  crossAxisAlignment: CrossAxisAlignment.start,
                  children: [
                    // 상단: 아이콘 + 타이틀
                    Row(
                      children: [
                        Icon(
                          Icons.satellite_alt,
                          size: 20,
                          color: isLinked
                              ? Colors.green.shade700
                              : isConnecting
                              ? Colors.orange.shade700
                              : Colors.grey.shade600,
                        ),
                        const SizedBox(width: 8),
                        const Text(
                          '포털 계정 연동',
                          style: TextStyle(
                            fontSize: 16,
                            fontWeight: FontWeight.bold,
                          ),
                        ),
                        const Spacer(),
                        // 상태 배지
                        Container(
                          padding: const EdgeInsets.symmetric(
                            horizontal: 10,
                            vertical: 4,
                          ),
                          decoration: BoxDecoration(
                            color: isLinked
                                ? Colors.green.shade100
                                : isConnecting
                                ? Colors.orange.shade100
                                : Colors.grey.shade200,
                            borderRadius: BorderRadius.circular(12),
                          ),
                          child: Row(
                            mainAxisSize: MainAxisSize.min,
                            children: [
                              if (isConnecting)
                                Padding(
                                  padding: const EdgeInsets.only(right: 4),
                                  child: SizedBox(
                                    width: 12,
                                    height: 12,
                                    child: CircularProgressIndicator(
                                      strokeWidth: 1.5,
                                      color: Colors.orange.shade800,
                                    ),
                                  ),
                                )
                              else
                                Text(
                                  _getPortalStatusEmoji(),
                                  style: const TextStyle(fontSize: 12),
                                ),
                              const SizedBox(width: 2),
                              Text(
                                _getPortalStatusText(),
                                style: TextStyle(
                                  fontSize: 12,
                                  fontWeight: FontWeight.w600,
                                  color: isLinked
                                      ? Colors.green.shade800
                                      : isConnecting
                                      ? Colors.orange.shade800
                                      : Colors.grey.shade700,
                                ),
                              ),
                            ],
                          ),
                        ),
                      ],
                    ),
                    const SizedBox(height: 12),
                    // ID 표시 영역
                    Row(
                      children: [
                        Icon(
                          Icons.badge_outlined,
                          size: 16,
                          color: Colors.grey.shade500,
                        ),
                        const SizedBox(width: 6),
                        Text(
                          _idController.text.isNotEmpty
                              ? 'ID: ${_idController.text}'
                              : 'ID: 미등록',
                          style: TextStyle(
                            fontSize: 14,
                            fontWeight: FontWeight.w500,
                            color: _idController.text.isNotEmpty
                                ? (Theme.of(context).brightness ==
                                          Brightness.dark
                                      ? Colors.white70
                                      : Colors.black87)
                                : Colors.grey,
                          ),
                        ),
                        if (_idController.text.isNotEmpty &&
                            (isLinked || isConnecting)) ...[
                          const Spacer(),
                          Icon(
                            Icons.check_circle,
                            size: 16,
                            color: isLinked ? Colors.green : Colors.orange,
                          ),
                        ],
                      ],
                    ),
                    const SizedBox(height: 8),
                    // 하단 상태 메시지
                    Row(
                      children: [
                        Icon(
                          isLinked
                              ? Icons.check_circle_outline
                              : isConnecting
                              ? Icons.sync
                              : Icons.info_outline,
                          size: 14,
                          color: isLinked
                              ? Colors.green.shade600
                              : isConnecting
                              ? Colors.orange.shade600
                              : Colors.grey.shade500,
                        ),
                        const SizedBox(width: 6),
                        Text(
                          isLinked
                              ? '✅ 포털 계정이 연동되었습니다'
                              : isConnecting
                              ? '🟡 포털 계정 연동 중...'
                              : '🔗 연동이 필요합니다',
                          style: TextStyle(
                            fontSize: 13,
                            color: isLinked
                                ? Colors.green.shade700
                                : isConnecting
                                ? Colors.orange.shade700
                                : Colors.grey.shade600,
                          ),
                        ),
                      ],
                    ),
                  ],
                ),
              ),
              const SizedBox(height: 24),

              // 연동중 표시
              if (isConnecting)
                Container(
                  width: double.infinity,
                  padding: const EdgeInsets.all(12),
                  margin: const EdgeInsets.only(bottom: 16),
                  decoration: BoxDecoration(
                    color: Colors.orange.shade50,
                    borderRadius: BorderRadius.circular(12),
                    border: Border.all(color: Colors.orange.shade200),
                  ),
                  child: Row(
                    children: [
                      const SizedBox(
                        height: 18,
                        width: 18,
                        child: CircularProgressIndicator(strokeWidth: 2),
                      ),
                      const SizedBox(width: 10),
                      Text(
                        '포털 계정 연동 중',
                        style: TextStyle(
                          fontSize: 14,
                          fontWeight: FontWeight.w500,
                          color: Colors.orange.shade800,
                        ),
                      ),
                    ],
                  ),
                ),

              // 연동됨 상태 → 연동 해제 버튼만 표시
              if (isLinked)
                SizedBox(
                  width: double.infinity,
                  height: 48,
                  child: OutlinedButton(
                    onPressed: _disconnect,
                    style: OutlinedButton.styleFrom(
                      foregroundColor: Colors.red,
                      side: const BorderSide(color: Colors.red),
                    ),
                    child: const Text(
                      '연동 해제',
                      style: TextStyle(
                        fontSize: 16,
                        fontWeight: FontWeight.bold,
                      ),
                    ),
                  ),
                ),

              // 미연동 상태 → 로그인 폼 + 연동 버튼 표시 (연동중/연동완료 시에는 숨김)
              if (showLoginForm) ...[
                const SizedBox(height: 8),

                // 학번, 비밀번호, 연동 버튼을 가로로 배치
                Row(
                  crossAxisAlignment: CrossAxisAlignment.start,
                  children: [
                    // 학번 + 비밀번호 컬럼
                    Expanded(
                      flex: 3,
                      child: Column(
                        children: [
                          TextField(
                            controller: _idController,
                            decoration: InputDecoration(
                              hintText: '학번',
                              prefixIcon: const Icon(Icons.person, size: 20),
                              contentPadding: const EdgeInsets.symmetric(
                                vertical: 12,
                                horizontal: 12,
                              ),
                              border: OutlineInputBorder(
                                borderRadius: BorderRadius.circular(8),
                              ),
                            ),
                          ),
                          const SizedBox(height: 8),
                          TextField(
                            controller: _passwordController,
                            obscureText: true,
                            decoration: InputDecoration(
                              hintText: '비밀번호',
                              prefixIcon: const Icon(Icons.lock, size: 20),
                              contentPadding: const EdgeInsets.symmetric(
                                vertical: 12,
                                horizontal: 12,
                              ),
                              border: OutlineInputBorder(
                                borderRadius: BorderRadius.circular(8),
                              ),
                            ),
                          ),
                        ],
                      ),
                    ),
                    const SizedBox(width: 8),
                    // 연동 버튼 (우측에 박스 형태)
                    SizedBox(
                      width: 80,
                      height: 88, // 두 TextField 높이 합
                      child: ElevatedButton(
                        onPressed: _connectPortal,
                        style: ElevatedButton.styleFrom(
                          backgroundColor: Colors.blue,
                          shape: RoundedRectangleBorder(
                            borderRadius: BorderRadius.circular(8),
                          ),
                          padding: const EdgeInsets.symmetric(vertical: 0),
                        ),
                        child: const Text(
                          '연동',
                          style: TextStyle(
                            fontSize: 15,
                            fontWeight: FontWeight.bold,
                            color: Colors.white,
                          ),
                        ),
                      ),
                    ),
                  ],
                ),
                const SizedBox(height: 12),

                // 에러 메시지
                if (_errorMessage != null)
                  Text(
                    _errorMessage!,
                    style: const TextStyle(color: Colors.red, fontSize: 14),
                  ),
              ],
              // 스크롤 가능하도록 Spacer + 다크모드 토글 추가
              const Spacer(),

              // 다크모드 토글
              Container(
                width: double.infinity,
                padding: const EdgeInsets.all(16),
                decoration: BoxDecoration(
                  color: Theme.of(context).brightness == Brightness.dark
                      ? Colors.grey.shade800
                      : Colors.white,
                  borderRadius: BorderRadius.circular(12),
                  boxShadow: [BoxShadow(color: Colors.black12, blurRadius: 4)],
                ),
                child: Row(
                  mainAxisAlignment: MainAxisAlignment.spaceBetween,
                  children: [
                    Row(
                      children: [
                        Icon(
                          Theme.of(context).brightness == Brightness.dark
                              ? Icons.dark_mode
                              : Icons.light_mode,
                          size: 20,
                          color: Theme.of(context).brightness == Brightness.dark
                              ? Colors.amber.shade300
                              : Colors.orange.shade700,
                        ),
                        const SizedBox(width: 10),
                        const Text(
                          '다크모드',
                          style: TextStyle(
                            fontSize: 16,
                            fontWeight: FontWeight.w500,
                          ),
                        ),
                      ],
                    ),
                    Switch(
                      value: ThemeService.instance.isDarkMode,
                      onChanged: (_) => ThemeService.instance.toggleTheme(),
                      activeTrackColor: Colors.blue,
                    ),
                  ],
                ),
              ),
              const SizedBox(height: 16),
            ],
          ),
        ),
      ),
    );
  }
}
