import 'dart:async';
import 'package:flutter/material.dart';
import 'package:flutter_inappwebview/flutter_inappwebview.dart';
import '../services/auth_service.dart';

class HiddenPortalWebView extends StatefulWidget {
  final String studentId;
  final String password;
  final bool triggerLogin;

  /// 세션 갱신 모드: 로그인 성공/실패 콜백 없이 백그라운드에서만 실행
  final bool silentRefresh;

  final VoidCallback onWebViewReady;
  final VoidCallback onLoginSuccess;
  final Function(String error) onLoginFailed;

  const HiddenPortalWebView({
    super.key,
    required this.studentId,
    required this.password,
    required this.triggerLogin,
    this.silentRefresh = false,
    required this.onWebViewReady,
    required this.onLoginSuccess,
    required this.onLoginFailed,
  });

  @override
  State<HiddenPortalWebView> createState() => _HiddenPortalWebViewState();
}

class _HiddenPortalWebViewState extends State<HiddenPortalWebView> {
  InAppWebViewController? webViewController;

  bool portalReady = false;
  bool loginTried = false;
  bool loginCompleted = false;
  bool rsaRecoveryTried = false;

  int loginRetryCount = 0;
  final int maxLoginRetry = 3;

  Timer? _loginPageWatchdogTimer;
  int _reloadCount = 0;
  final int _maxReloadCount = 3;

  void _startLoginPageWatchdog(InAppWebViewController controller) {
    _loginPageWatchdogTimer?.cancel();
    if (_reloadCount >= _maxReloadCount) {
      debugPrint('[WATCHDOG] 최대 새로고침 횟수 초과 → 실패 처리');
      widget.onLoginFailed('포털 로그인 페이지 로딩 시간 초과 (네트워크 확인 필요)');
      return;
    }
    debugPrint('[WATCHDOG] 20초 타이머 시작: 포털 SSO 로그인 페이지 대기 중');
    _loginPageWatchdogTimer = Timer(const Duration(seconds: 20), () async {
      if (loginTried || loginCompleted) return;
      _reloadCount++;
      debugPrint(
        '[WATCHDOG] SSO 미감지 → 새로고침 시도 ($_reloadCount/$_maxReloadCount)',
      );
      try {
        await controller.loadUrl(
          urlRequest: URLRequest(url: WebUri('https://portal.kongju.ac.kr/')),
        );
      } catch (e) {
        debugPrint('[WATCHDOG] 새로고침 실패: $e');
      }
    });
  }

  void _cancelLoginPageWatchdog() {
    _loginPageWatchdogTimer?.cancel();
    _loginPageWatchdogTimer = null;
  }

  /// 포털 메인 페이지인지 확인 (sso/login/loginP 제외 = 로그인 완료 상태)
  bool _isPortalMainPage(String url) {
    return url.contains('portal.kongju.ac.kr') &&
        !url.contains('loginP.jsp') &&
        !url.contains('sso') &&
        !url.contains('Login') &&
        !url.contains('login');
  }

  /// 포털 메인 페이지 진입 = 로그인 성공
  Future<void> _onLoginCompleted() async {
    if (loginCompleted) return;
    loginCompleted = true;
    _cancelLoginPageWatchdog();

    debugPrint('[AUTH] 포털 메인 페이지 감지 → 로그인 성공');

    await AuthService.instance.savePortalStatus(AuthService.portalStatusLinked);

    // silentRefresh 모드에서는 콜백을 호출하지 않음
    if (!widget.silentRefresh) {
      widget.onLoginSuccess();
    }
  }

  @override
  void dispose() {
    _cancelLoginPageWatchdog();
    super.dispose();
  }

  @override
  void didUpdateWidget(covariant HiddenPortalWebView oldWidget) {
    super.didUpdateWidget(oldWidget);

    // 이미 로그인 완료 상태면 재로그인하지 않음
    if (loginCompleted) {
      debugPrint('[AUTH] 이미 로그인 완료됨 → 재로그인 시도 안 함');
      return;
    }

    if (widget.triggerLogin && !oldWidget.triggerLogin) {
      debugPrint('[AUTH] 로그인 트리거 활성화 → 자동 로그인 플로우 시작');
      loginTried = false;
      loginCompleted = false;
      rsaRecoveryTried = false;
      loginRetryCount = 0;
      _reloadCount = 0;

      if (webViewController != null) {
        webViewController!.loadUrl(
          urlRequest: URLRequest(url: WebUri('https://portal.kongju.ac.kr/')),
        );
      }
    }
  }

  @override
  Widget build(BuildContext context) {
    return Offstage(
      offstage: true,
      child: SizedBox(
        width: 1,
        height: 1,
        child: InAppWebView(
          initialUrlRequest: URLRequest(
            url: WebUri('https://portal.kongju.ac.kr/'),
          ),
          initialSettings: InAppWebViewSettings(
            javaScriptEnabled: true,
            useShouldOverrideUrlLoading: true,
            javaScriptCanOpenWindowsAutomatically: true,
            userAgent:
                "Mozilla/5.0 (iPhone; CPU iPhone OS 17_0 like Mac OS X) "
                "AppleWebKit/605.1.15 (KHTML, like Gecko) "
                "Version/17.0 Mobile/15E148 Safari/604.1",
            mixedContentMode: MixedContentMode.MIXED_CONTENT_ALWAYS_ALLOW,
            domStorageEnabled: true,
            cacheMode: CacheMode.LOAD_DEFAULT,
          ),

          onWebViewCreated: (controller) {
            webViewController = controller;
            debugPrint('[WebView] 웹뷰 생성 완료');
          },

          onReceivedServerTrustAuthRequest: (controller, challenge) async {
            debugPrint('[SSL] 인증서 우회 승인: ${challenge.protectionSpace.host}');
            return ServerTrustAuthResponse(
              action: ServerTrustAuthResponseAction.PROCEED,
            );
          },

          shouldOverrideUrlLoading: (controller, action) async {
            final url = action.request.url.toString();
            debugPrint('[NAV] 이동 요청: $url');

            // 포털 메인 페이지로 이동 중이고 로그인 시도 후면 성공
            if (!loginCompleted &&
                portalReady &&
                _isPortalMainPage(url) &&
                loginTried) {
              await _onLoginCompleted();
            }

            return NavigationActionPolicy.ALLOW;
          },

          onLoadStart: (controller, url) {
            debugPrint('[NAV] 로딩 시작: ${url?.toString() ?? ''}');
          },

          onLoadStop: (controller, url) async {
            final currentUrl = url?.toString() ?? '';
            debugPrint('[NAV] 로딩 완료: $currentUrl');

            // ── 1. 포털 최초 진입 감지 ──
            if (!portalReady && currentUrl.contains('portal.kongju.ac.kr')) {
              portalReady = true;
              debugPrint('[AUTH] 포털 최초 진입 → onWebViewReady 호출');
              widget.onWebViewReady();
            }

            // ── 2. loginP.jsp: SSO 리다이렉트 예정 → Watchdog 해제 ──
            if (currentUrl.contains('loginP.jsp')) {
              debugPrint('[AUTH] loginP.jsp 감지 (SSO로 리다이렉트 예정)');
              _cancelLoginPageWatchdog();
            }

            // ── 3. 포털 메인 페이지 (로그인 완료 후) → 즉시 성공 처리 ──
            if (!loginCompleted &&
                portalReady &&
                _isPortalMainPage(currentUrl) &&
                loginTried) {
              await _onLoginCompleted();
              return;
            }

            // ── 4. SSO 로그인 페이지 감지 → 자동 로그인 시도 ──
            final bool isSsoPage =
                currentUrl.contains('sso') ||
                currentUrl.contains('loginP') ||
                currentUrl.contains('Login') ||
                currentUrl.contains('login');

            if (isSsoPage && widget.triggerLogin && !loginTried) {
              loginTried = true;
              _cancelLoginPageWatchdog();
              debugPrint('[AUTH] SSO 로그인 페이지 감지: $currentUrl → 1.5초 후 로그인 시도');
              await Future.delayed(const Duration(milliseconds: 1500));
              await tryAutoLoginWithRetry();
              return;
            }

            // ── 5. 초기 포털 진입 (아직 로그인 안 함) → Watchdog 시작 ──
            if (portalReady &&
                _isPortalMainPage(currentUrl) &&
                !loginTried &&
                !loginCompleted) {
              debugPrint('[AUTH] 포털 메인 직접 진입 (아직 로그인 안 됨) → Watchdog 시작');
              _startLoginPageWatchdog(controller);
            }
          },

          onJsAlert: (controller, jsAlertRequest) async {
            final message = jsAlertRequest.message ?? '';
            debugPrint('[JS ALERT] $message');

            final isRsaError =
                message.contains('Invalid RSA public key') ||
                message.contains('bitLength') ||
                message.contains('RSA');

            if (isRsaError && !rsaRecoveryTried) {
              rsaRecoveryTried = true;
              debugPrint('[RSA] RSA 초기화 오류 감지 → alert 자동 confirm 후 진행');
            }

            return JsAlertResponse(
              handledByClient: true,
              action: JsAlertResponseAction.CONFIRM,
            );
          },

          onJsConfirm: (controller, jsConfirmRequest) async {
            debugPrint('[JS CONFIRM] ${jsConfirmRequest.message}');
            return JsConfirmResponse(
              handledByClient: true,
              action: JsConfirmResponseAction.CONFIRM,
            );
          },

          onReceivedError: (controller, request, error) async {
            final url = request.url.toString();
            final desc = error.description;
            debugPrint('[ERROR] 로딩 오류: $desc ($url)');

            if (desc.contains('TLS') ||
                desc.contains('SSL') ||
                desc.contains('보안 연결') ||
                desc.contains('certificate') ||
                error.type == WebResourceErrorType.FAILED_SSL_HANDSHAKE) {
              debugPrint('[TLS] SSL/TLS 오류 → 3초 후 재시도');
              await Future.delayed(const Duration(seconds: 3));
              try {
                await controller.loadUrl(
                  urlRequest: URLRequest(
                    url: WebUri('https://portal.kongju.ac.kr/'),
                  ),
                );
              } catch (e) {
                debugPrint('[TLS] 재시도 실패: $e');
              }
              return;
            }

            if (error.type == WebResourceErrorType.HOST_LOOKUP) {
              widget.onLoginFailed('네트워크 연결 오류: 인터넷 연결을 확인해주세요.');
            }
          },
        ),
      ),
    );
  }

  // ──────────────────────────────────────────────
  // 자동 로그인 (재시도 포함)
  // ──────────────────────────────────────────────
  Future<void> tryAutoLoginWithRetry() async {
    if (loginTried && loginRetryCount > 0) return;

    while (loginRetryCount < maxLoginRetry && !loginCompleted) {
      loginRetryCount++;
      debugPrint('[AUTH] 자동 로그인 시도: $loginRetryCount/$maxLoginRetry');

      final success = await tryAutoLogin();
      if (success) {
        debugPrint('[AUTH] 로그인 폼 제출 성공 → 포털 메인 페이지 대기 중');
        return;
      }

      final waitSeconds = loginRetryCount * 2;
      debugPrint('[AUTH] 로그인 실패 → $waitSeconds초 후 재시도');
      await Future.delayed(Duration(seconds: waitSeconds));
    }

    if (!loginCompleted) {
      debugPrint('[AUTH] 자동 로그인 최종 실패 (모든 시도 소진)');
      // silentRefresh 모드에서는 실패 시 연결 상태로 전환 (재시도 유도)
      if (widget.silentRefresh) {
        await AuthService.instance.savePortalStatus(
          AuthService.portalStatusConnecting,
        );
      }
      widget.onLoginFailed('자동 로그인 실패: 아이디/비밀번호를 확인하거나 포털 상태를 확인하세요.');
    }
  }

  // ──────────────────────────────────────────────
  // JS로 로그인 폼 입력 + 제출
  // ──────────────────────────────────────────────
  Future<bool> tryAutoLogin() async {
    try {
      debugPrint('[AUTH] 로그인 JS 실행');

      // DOM 구조 정보 수집 (디버깅)
      final domInfo = await webViewController?.evaluateJavascript(
        source: """
(function() {
  const inputs = Array.from(document.querySelectorAll('input')).map(i =>
    'tag=' + i.tagName + ' type=' + i.type + ' name=' + i.name + ' id=' + i.id
  );
  const forms = document.forms.length;
  const url = window.location.href;
  return JSON.stringify({ url, forms, inputs: inputs.slice(0, 10) });
})();
""",
      );
      debugPrint('[AUTH] DOM 정보: $domInfo');

      // 실제 로그인 시도
      final result = await webViewController?.evaluateJavascript(
        source:
            """
(function() {

  // ── 입력 필드 탐색 ──
  const idSelectors = [
    'input[name="sg_uid"]',
    '#frmIlban\\.sg_uid',
    'input[id*="uid"]',
    'input[id*="id"]',
    'input[name*="id"]',
    'input[placeholder*="아이디"]',
    'input[placeholder*="학번"]',
    'input[type="text"]'
  ];
  const pwSelectors = [
    'input[name="sg_pwd"]',
    '#frmIlban\\.sg_pwd',
    'input[id*="pwd"]',
    'input[id*="pw"]',
    'input[name*="pw"]',
    'input[name*="pass"]',
    'input[placeholder*="비밀번호"]',
    'input[type="password"]'
  ];

  let idInput = null;
  let pwInput = null;

  for (const sel of idSelectors) {
    try { idInput = document.querySelector(sel); } catch(e) {}
    if (idInput && idInput.type !== 'hidden') break;
  }
  for (const sel of pwSelectors) {
    try { pwInput = document.querySelector(sel); } catch(e) {}
    if (pwInput) break;
  }

  if (!idInput || !pwInput) {
    const allInputs = Array.from(document.querySelectorAll('input:not([type=hidden])')).map(i => i.name + '/' + i.id + '/' + i.type);
    return 'LOGIN_ELEMENT_NOT_FOUND:' + JSON.stringify(allInputs);
  }

  // ── 값 설정 ──
  function setNativeValue(el, value) {
    const descriptor = Object.getOwnPropertyDescriptor(window.HTMLInputElement.prototype, 'value');
    if (descriptor && descriptor.set) {
      descriptor.set.call(el, value);
    } else {
      el.value = value;
    }
    el.dispatchEvent(new Event('input', { bubbles: true }));
    el.dispatchEvent(new Event('change', { bubbles: true }));
    el.dispatchEvent(new KeyboardEvent('keyup', { bubbles: true }));
  }

  setNativeValue(idInput, '${widget.studentId}');
  setNativeValue(pwInput, '${widget.password}');

  // ── 버튼 탐색 (광범위) ──
  const btnSelectors = [
    '#frmIlban\\.pb_i_login',
    'input[type="submit"]',
    'input[type="button"]',
    'input[type="image"]',
    'button[type="submit"]',
    'button:not([type])',
    'button',
    '[onclick*="login"]',
    '[onclick*="Login"]',
    '[onclick*="fn_"]',
    'a.btn',
    '.login-btn',
    '.btnLogin',
    '.loginBtn',
    '.btn-login'
  ];

  let loginBtn = null;
  for (const sel of btnSelectors) {
    const candidates = document.querySelectorAll(sel);
    for (const c of candidates) {
      const style = window.getComputedStyle(c);
      if (style.display !== 'none' && style.visibility !== 'hidden') {
        loginBtn = c;
        break;
      }
    }
    if (loginBtn) break;
  }

  if (loginBtn) {
    loginBtn.click();
    return 'BTN_CLICKED:' + (loginBtn.id || loginBtn.name || loginBtn.tagName);
  }

  // ── JS 함수 직접 호출 (한국 SSO 솔루션 공통 패턴) ──
  const fnNames = ['fn_login', 'fnLogin', 'doLogin', 'goLogin', 'login', 'Login', 'submitLogin', 'loginSubmit'];
  for (const fn of fnNames) {
    if (typeof window[fn] === 'function') {
      try { window[fn](); return 'FN_CALLED:' + fn; } catch(e) {}
    }
  }

  // ── 폼 직접 submit ──
  for (const form of document.forms) {
    const hasIdField = form.querySelector('input[type="text"], input[name*="id"], input[name*="uid"]');
    const hasPwField = form.querySelector('input[type="password"]');
    if (hasIdField || hasPwField) {
      form.submit();
      return 'FORM_SUBMITTED';
    }
  }

  return 'LOGIN_BUTTON_NOT_FOUND';
})();
""",
      );

      debugPrint('[AUTH] 로그인 결과: $result');
      return result != null &&
          !result.toString().startsWith('LOGIN_ELEMENT_NOT_FOUND') &&
          !result.toString().startsWith('LOGIN_BUTTON_NOT_FOUND');
    } catch (e) {
      debugPrint('[AUTH] 로그인 JS 실패: $e');
      return false;
    }
  }
}
