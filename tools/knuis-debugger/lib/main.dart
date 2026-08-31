import 'package:flutter/material.dart';
import 'package:flutter_inappwebview/flutter_inappwebview.dart';

void main() {
  runApp(const KnuisDebuggerApp());
}

class KnuisDebuggerApp extends StatelessWidget {
  const KnuisDebuggerApp({super.key});

  @override
  Widget build(BuildContext context) {
    return MaterialApp(
      debugShowCheckedModeBanner: false,
      title: 'KNUIS Debugger',
      theme: ThemeData(
        colorScheme: ColorScheme.fromSeed(seedColor: Colors.blue),
      ),
      home: const DebugHomePage(),
    );
  }
}

class DebugHomePage extends StatefulWidget {
  const DebugHomePage({super.key});

  @override
  State<DebugHomePage> createState() => _DebugHomePageState();
}

class _DebugHomePageState extends State<DebugHomePage> {
  InAppWebViewController? _controller;

  bool _loaded = false;

  @override
  void initState() {
    super.initState();
  }

  Future<void> _dumpMenuIndex() async {
    try {
      final result = await _controller!.evaluateJavascript(
        source: '''
(() => {

    try {

        const menuObj = _my_Page01_listMenu;

        if (!menuObj || !menuObj.arrData) {
            return JSON.stringify({
                error: 'menu dataset not found'
            });
        }

        const data = menuObj.arrData;

        const ids = data.menu_id1 || [];
        const names = data.menu_nm1 || [];
        const paths = data.filepath || [];

        const result = [];

        for (let i = 0; i < ids.length; i++) {

            if (!ids[i]) continue;

            result.push({
                menuId: ids[i],
                menuName: names[i],
                filepath: paths[i],
            });
        }

        return JSON.stringify(result);

    } catch (e) {

        return JSON.stringify({
            error: e.toString(),
        });
    }
})();
''',
      );

      debugPrint('========== MENU INDEX ==========');

      debugPrint(result.toString());
    } catch (e) {
      debugPrint('MENU INDEX ERROR: $e');
    }
  }

  Future<void> _openTimetableMenu() async {
    try {
      await _controller!.evaluateJavascript(
        source: '''
(() => {

    const left =
      document.querySelector("#LeftFrame")
        ?.contentWindow;

    if (!left) {
        throw new Error("LeftFrame not found");
    }

    left.Page00.funcLeft.fn_runFileMDI(
      "1000000062",
      0
    );
})();
''',
      );

      debugPrint('시간표 메뉴 열기 완료');
    } catch (e) {
      debugPrint('시간표 메뉴 열기 실패: $e');
    }
  }

  Future<void> _dumpIframeList() async {
    try {
      final result = await _controller!.evaluateJavascript(
        source: '''
(() => {

    try {

        return Array
            .from(document.querySelectorAll("iframe"))
            .map(v => ({
                id: v.id,
                src: v.src,
            }));

    } catch (e) {

        return {
            error: e.toString(),
        };
    }
})();
''',
      );

      debugPrint('========== IFRAME LIST ==========');

      debugPrint(result.toString());
    } catch (e) {
      debugPrint('IFRAME LIST ERROR: $e');
    }
  }

  Future<void> _dumpTimetableData() async {
    try {
      final result = await _controller!.evaluateJavascript(
        source: '''
(() => {

    return new Promise(resolve => {

        const waitFrame = () => {

            try {

                const iframe =
                    document.querySelector("#WHHSKV0580");

                if (!iframe) {

                    console.log("WHHSKV0580 iframe waiting...");

                    setTimeout(waitFrame, 1000);
                    return;
                }

                const frame = iframe.contentWindow;

                if (!frame) {

                    resolve(JSON.stringify({
                        error: "iframe contentWindow not found"
                    }));

                    return;
                }

                frame.Page00.F_TOPMENU.QueryG1();

                setTimeout(() => {

                    try {

                        const g1 =
                            frame.Webcrea.GetObjectById("G1");

                        if (!g1 || !g1.arrData) {

                            resolve(JSON.stringify({
                                error: "G1 arrData not found"
                            }));

                            return;
                        }

                        resolve(
                            JSON.stringify(g1.arrData)
                        );

                    } catch (e) {

                        resolve(JSON.stringify({
                            error: e.toString(),
                        }));
                    }

                }, 2000);

            } catch (e) {

                resolve(JSON.stringify({
                    error: e.toString(),
                }));
            }
        };

        waitFrame();
    });
})();
''',
      );

      debugPrint('========== TIMETABLE ==========');

      debugPrint(result.toString());
    } catch (e) {
      debugPrint('TIMETABLE ERROR: $e');
    }
  }

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      appBar: AppBar(title: const Text('KNUIS Debugger')),
      body: Column(
        children: [
          Expanded(
            child: InAppWebView(
              initialUrlRequest: URLRequest(
                url: WebUri('https://portal.kongju.ac.kr'),
              ),
              initialSettings: InAppWebViewSettings(
                javaScriptEnabled: true,
                javaScriptCanOpenWindowsAutomatically: true,
                mediaPlaybackRequiresUserGesture: false,
                useShouldOverrideUrlLoading: true,
                allowsInlineMediaPlayback: true,
                iframeAllow: 'camera; microphone',
                userAgent:
                    'Mozilla/5.0 (iPhone; CPU iPhone OS 17_0 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.0 Mobile/15E148 Safari/604.1',
              ),
              onWebViewCreated: (controller) {
                _controller = controller;
              },
              shouldOverrideUrlLoading: (controller, navigationAction) async {
                final url = navigationAction.request.url?.toString() ?? '';

                debugPrint('[NAV] 이동 요청: $url');

                return NavigationActionPolicy.ALLOW;
              },
              onLoadStart: (controller, url) {
                debugPrint('[NAV] 로딩 시작: ${url.toString()}');
              },
              onLoadStop: (controller, url) async {
                debugPrint('[NAV] 로딩 완료: ${url.toString()}');

                final currentUrl = url.toString();

                if (currentUrl.contains('m_sso.jsp')) {
                  debugPrint('[AUTH] SSO 로그인 페이지 감지');
                }

                if (currentUrl == 'https://portal.kongju.ac.kr/' ||
                    currentUrl == 'https://portal.kongju.ac.kr') {
                  debugPrint('[PORTAL] root portal 감지 → index.jsp 이동');

                  await controller.loadUrl(
                    urlRequest: URLRequest(
                      url: WebUri('https://portal.kongju.ac.kr/index.jsp'),
                    ),
                  );

                  return;
                }

                if (currentUrl.contains('portal.kongju.ac.kr/index.jsp')) {
                  debugPrint('[PORTAL] 포털 메인 진입 완료');

                  await Future.delayed(const Duration(seconds: 2));

                  final result = await controller.evaluateJavascript(
                    source: '''
(() => {

    try {

        const iframe =
            document.querySelector("iframe");

        if (!iframe) {
            return "IFRAME_NOT_FOUND";
        }

        iframe.click();

        return "IFRAME_CLICKED";

    } catch (e) {

        return e.toString();
    }
})();
''',
                  );

                  debugPrint('[KNUIS] iframe 클릭 결과: ${result.toString()}');
                }

                if (currentUrl.contains('crossurl.jsp')) {
                  debugPrint('[KNUIS] crossurl.jsp 감지');
                }

                if (currentUrl.contains('knuis-s.kongju.ac.kr')) {
                  debugPrint('[KNUIS] 통합정보시스템 진입 성공');
                }

                if (!_loaded) {
                  setState(() {
                    _loaded = true;
                  });
                }
              },
              onReceivedServerTrustAuthRequest: (controller, challenge) async {
                debugPrint(
                  '[SSL] 인증서 우회 승인: ${challenge.protectionSpace.host}',
                );

                return ServerTrustAuthResponse(
                  action: ServerTrustAuthResponseAction.PROCEED,
                );
              },
              onConsoleMessage: (controller, consoleMessage) {
                debugPrint('[JS] ${consoleMessage.message}');
              },
            ),
          ),
          Container(
            padding: const EdgeInsets.all(12),
            child: Wrap(
              spacing: 12,
              runSpacing: 12,
              children: [
                ElevatedButton(
                  onPressed: _loaded ? _dumpMenuIndex : null,
                  child: const Text('메뉴 인덱스 출력'),
                ),
                ElevatedButton(
                  onPressed: _loaded ? _dumpIframeList : null,
                  child: const Text('iframe 목록 출력'),
                ),
                ElevatedButton(
                  onPressed: _loaded ? _openTimetableMenu : null,
                  child: const Text('시간표 메뉴 열기'),
                ),
                ElevatedButton(
                  onPressed: _loaded ? _dumpTimetableData : null,
                  child: const Text('시간표 데이터 출력'),
                ),
              ],
            ),
          ),
        ],
      ),
    );
  }
}
