/// 홈 화면 — 포털 연동 상태 표시, 시간표/공지/장학 정보 카드 + 서버 API 연동.
library;

import 'package:flutter/material.dart';

import '../widgets/info_card.dart';
import '../services/api_service.dart';

class HomeScreen extends StatefulWidget {
  final String portalEmoji;
  final String portalText;
  final VoidCallback onSettingsTap;

  const HomeScreen({
    super.key,
    required this.portalEmoji,
    required this.portalText,
    required this.onSettingsTap,
  });

  @override
  State<HomeScreen> createState() => _HomeScreenState();
}

class _HomeScreenState extends State<HomeScreen> {
  List<NoticeItem> _notices = [];
  bool _noticesLoading = true;
  String? _noticesError;

  bool get _isConnecting => widget.portalEmoji == '🟡';
  bool get _isLinked => widget.portalEmoji == '🟢';

  @override
  void initState() {
    super.initState();
    _loadNotices();
  }

  Future<void> _loadNotices() async {
    try {
      final notices = await ApiService.instance.getNotices(limit: 5);
      if (mounted) {
        setState(() {
          _notices = notices;
          _noticesLoading = false;
        });
      }
    } catch (e) {
      if (mounted) {
        setState(() {
          _noticesError = e.toString();
          _noticesLoading = false;
        });
      }
    }
  }

  String _getInfoCardMessage(String cardType) {
    if (_isConnecting) {
      return '🟡 포털 연동 중입니다. 잠시만 기다려주세요.';
    }
    if (_isLinked) {
      switch (cardType) {
        case 'timetable':
          return '🟢 캐시된 시간표 데이터를 표시합니다.';
        case 'notice':
          return '🟢 학사 공지 데이터를 준비 중입니다.';
        case 'scholarship':
          return '🟢 장학 데이터를 준비 중입니다.';
        default:
          return '🟢 포털이 연동되었습니다.';
      }
    }
    switch (cardType) {
      case 'timetable':
        return '🔴 포털 연동 후 시간표를 확인하세요.';
      case 'notice':
        return '🔴 포털 연동 후 학사 공지를 확인하세요.';
      case 'scholarship':
        return '🔴 포털 연동 후 장학 정보를 확인하세요.';
      default:
        return '🔴 설정에서 포털 계정을 연동해주세요.';
    }
  }

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      appBar: AppBar(
        title: const Text('공주대학교 AI Assistant'),
        actions: [
          _PortalStatusBadge(
            emoji: widget.portalEmoji,
            text: widget.portalText,
            isConnecting: _isConnecting,
            isLinked: _isLinked,
          ),
          IconButton(
            onPressed: widget.onSettingsTap,
            icon: const Icon(Icons.settings),
          ),
        ],
      ),
      body: SafeArea(
        child: Padding(
          padding: const EdgeInsets.all(20),
          child: Column(
            crossAxisAlignment: CrossAxisAlignment.start,
            children: [
              const SizedBox(height: 12),
              _HeaderMessage(
                text: _getInfoCardMessage('header'),
                portalEmoji: widget.portalEmoji,
                isConnecting: _isConnecting,
                isLinked: _isLinked,
              ),
              const SizedBox(height: 32),
              Expanded(
                child: ListView(
                  children: [
                    InfoCard(
                      title: '오늘 시간표',
                      content: _getInfoCardMessage('timetable'),
                      icon: Icons.schedule,
                    ),
                    const SizedBox(height: 16),

                    // 최신 공지사항 (서버 API에서 가져옴)
                    if (_noticesLoading)
                      const InfoCard(
                        title: '최신 공지',
                        content: '공지사항을 불러오는 중...',
                        icon: Icons.campaign,
                      )
                    else if (_noticesError != null)
                      InfoCard(
                        title: '최신 공지',
                        content: '공지사항 로딩 실패',
                        icon: Icons.error_outline,
                      )
                    else if (_notices.isEmpty)
                      const InfoCard(
                        title: '최신 공지',
                        content: '등록된 공지사항이 없습니다.',
                        icon: Icons.campaign,
                      )
                    else
                      _NoticeListCard(notices: _notices),

                    const SizedBox(height: 16),
                    InfoCard(
                      title: '장학 정보',
                      content: _getInfoCardMessage('scholarship'),
                      icon: Icons.school,
                    ),
                  ],
                ),
              ),
            ],
          ),
        ),
      ),
    );
  }
}

/// 최신 공지사항을 보여주는 카드
class _NoticeListCard extends StatelessWidget {
  final List<NoticeItem> notices;

  const _NoticeListCard({required this.notices});

  static const Map<String, String> _categoryIcons = {
    '장학': '💰',
    '수강': '📚',
    '취업(진로)': '💼',
    '행사(공모전)': '🏆',
    '일반(기타)': '📌',
  };

  @override
  Widget build(BuildContext context) {
    final isDark = Theme.of(context).brightness == Brightness.dark;

    return Container(
      padding: const EdgeInsets.all(20),
      decoration: BoxDecoration(
        color: isDark ? Colors.grey.shade800 : Colors.white,
        borderRadius: BorderRadius.circular(16),
        boxShadow: [BoxShadow(color: Colors.black12, blurRadius: 8)],
      ),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          const Row(
            children: [
              Icon(Icons.campaign, size: 32),
              SizedBox(width: 16),
              Text(
                '최신 공지',
                style: TextStyle(fontSize: 18, fontWeight: FontWeight.bold),
              ),
            ],
          ),
          const SizedBox(height: 12),
          ...notices.map((notice) {
            final icon = _categoryIcons[notice.category] ?? '📌';
            return Padding(
              padding: const EdgeInsets.only(bottom: 8),
              child: Row(
                crossAxisAlignment: CrossAxisAlignment.start,
                children: [
                  Text(icon, style: const TextStyle(fontSize: 14)),
                  const SizedBox(width: 8),
                  Expanded(
                    child: Text(
                      notice.title,
                      style: TextStyle(
                        fontSize: 14,
                        color: isDark ? Colors.white : Colors.black87,
                      ),
                      maxLines: 2,
                      overflow: TextOverflow.ellipsis,
                    ),
                  ),
                ],
              ),
            );
          }),
        ],
      ),
    );
  }
}

class _PortalStatusBadge extends StatelessWidget {
  final String emoji;
  final String text;
  final bool isConnecting;
  final bool isLinked;

  const _PortalStatusBadge({
    required this.emoji,
    required this.text,
    required this.isConnecting,
    required this.isLinked,
  });

  @override
  Widget build(BuildContext context) {
    return Padding(
      padding: const EdgeInsets.only(right: 4),
      child: Center(
        child: AnimatedSwitcher(
          duration: const Duration(milliseconds: 300),
          transitionBuilder: (child, animation) {
            return FadeTransition(
              opacity: animation,
              child: ScaleTransition(scale: animation, child: child),
            );
          },
          child: Container(
            key: ValueKey('$emoji$text'),
            padding: const EdgeInsets.symmetric(horizontal: 10, vertical: 4),
            decoration: BoxDecoration(
              color: isLinked
                  ? Colors.green.shade50
                  : isConnecting
                  ? Colors.orange.shade50
                  : Colors.grey.shade200,
              borderRadius: BorderRadius.circular(16),
              border: isLinked
                  ? Border.all(color: Colors.green.shade200)
                  : isConnecting
                  ? Border.all(color: Colors.orange.shade200)
                  : null,
            ),
            child: Row(
              mainAxisSize: MainAxisSize.min,
              children: [
                AnimatedSwitcher(
                  duration: const Duration(milliseconds: 400),
                  transitionBuilder: (child, animation) {
                    return RotationTransition(turns: animation, child: child);
                  },
                  child: isConnecting
                      ? SizedBox(
                          key: const ValueKey('spinner'),
                          width: 14,
                          height: 14,
                          child: CircularProgressIndicator(
                            strokeWidth: 2,
                            color: Colors.orange.shade700,
                          ),
                        )
                      : Text(
                          emoji,
                          key: ValueKey('emoji_$emoji'),
                          style: const TextStyle(fontSize: 13),
                        ),
                ),
                const SizedBox(width: 4),
                AnimatedDefaultTextStyle(
                  duration: const Duration(milliseconds: 300),
                  style: TextStyle(
                    fontSize: 13,
                    fontWeight: FontWeight.w500,
                    color: isLinked
                        ? Colors.green.shade800
                        : isConnecting
                        ? Colors.orange.shade800
                        : Colors.grey.shade700,
                  ),
                  child: Text(text),
                ),
              ],
            ),
          ),
        ),
      ),
    );
  }
}

class _HeaderMessage extends StatelessWidget {
  final String text;
  final String portalEmoji;
  final bool isConnecting;
  final bool isLinked;

  const _HeaderMessage({
    required this.text,
    required this.portalEmoji,
    required this.isConnecting,
    required this.isLinked,
  });

  @override
  Widget build(BuildContext context) {
    return AnimatedSwitcher(
      duration: const Duration(milliseconds: 300),
      transitionBuilder: (child, animation) {
        return FadeTransition(opacity: animation, child: child);
      },
      child: Text(
        text,
        key: ValueKey('header_$portalEmoji'),
        style: TextStyle(
          fontSize: 16,
          color: isLinked
              ? Colors.green.shade700
              : isConnecting
              ? Colors.orange.shade700
              : Colors.grey,
        ),
      ),
    );
  }
}
