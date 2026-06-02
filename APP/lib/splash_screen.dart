import 'package:flutter/material.dart';

import 'main_screen.dart';
import 'services/auth_service.dart';

class SplashScreen extends StatefulWidget {
  const SplashScreen({super.key});

  @override
  State<SplashScreen> createState() => _SplashScreenState();
}

class _SplashScreenState extends State<SplashScreen> {
  String _statusText = '앱을 시작 중입니다...';

  @override
  void initState() {
    super.initState();
    _navigateToMain();
  }

  Future<void> _navigateToMain() async {
    // 1단계: 앱 초기화
    await Future.delayed(const Duration(milliseconds: 400));
    if (!mounted) return;
    setState(() => _statusText = '포털 연동 상태 확인 중...');

    // 2단계: 포털 상태 확인
    await Future.delayed(const Duration(milliseconds: 200));
    if (!mounted) return;

    final status = await AuthService.instance.getPortalStatus();
    final hasCredentials = await AuthService.instance.hasSavedLogin();

    if (!mounted) return;

    if (hasCredentials && status == AuthService.portalStatusLinked) {
      setState(() => _statusText = '자동 로그인 중...');
      await Future.delayed(const Duration(milliseconds: 300));
    } else if (hasCredentials) {
      setState(() => _statusText = '포털 계정 연동 준비 중...');
      await Future.delayed(const Duration(milliseconds: 300));
    }

    if (!mounted) return;

    Navigator.pushReplacement(
      context,
      MaterialPageRoute(builder: (_) => const MainScreen()),
    );
  }

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      body: Container(
        width: double.infinity,
        height: double.infinity,
        color: Theme.of(context).scaffoldBackgroundColor,
        child: Column(
          mainAxisAlignment: MainAxisAlignment.center,
          children: [
            Icon(
              Icons.school,
              size: 80,
              color: Theme.of(context).colorScheme.primary,
            ),
            const SizedBox(height: 24),
            Text(
              '공주대학교 AI Assistant',
              style: TextStyle(
                fontSize: 28,
                fontWeight: FontWeight.bold,
                color: Theme.of(context).colorScheme.onSurface,
              ),
            ),
            const SizedBox(height: 32),
            const SizedBox(
              height: 24,
              width: 24,
              child: CircularProgressIndicator(strokeWidth: 2.5),
            ),
            const SizedBox(height: 20),
            AnimatedSwitcher(
              duration: const Duration(milliseconds: 400),
              transitionBuilder: (child, animation) {
                return FadeTransition(opacity: animation, child: child);
              },
              child: Text(
                _statusText,
                key: ValueKey(_statusText),
                style: TextStyle(
                  fontSize: 15,
                  color: Theme.of(
                    context,
                  ).colorScheme.onSurface.withValues(alpha: 0.6),
                ),
              ),
            ),
          ],
        ),
      ),
    );
  }
}
