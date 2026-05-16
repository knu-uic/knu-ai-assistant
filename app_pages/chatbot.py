"""AI 챗봇 페이지. LangGraph RAG 파이프라인 호출."""

import streamlit as st

from graph import GRAPH
from ui import get_current_user

user = get_current_user()
major = user.get("major")

st.title("AI 챗봇")

if "chat_history" not in st.session_state:
    st.session_state.chat_history = []

# 빈 대화일 때 환영 메시지 + 제안 프롬프트.
if not st.session_state.chat_history:
    with st.chat_message("assistant"):
        st.markdown(f"안녕하세요 {user.get('name', '학생')}님 👋")
        st.markdown(
            f"{major or '학과 미설정'} · {user.get('year') or '-'}학년에 맞춰 답변해드릴게요. "
            "공지사항·장학·취업·수업자료 무엇이든 물어보세요."
        )
        suggestions = [
            "이번 학기 장학금 신청 일정 알려줘",
            "5월에 마감되는 인턴 공고 정리해줘",
            "캡스톤 디자인 팀 어떻게 신청해?",
        ]
        cols = st.columns(len(suggestions))
        for col, s in zip(cols, suggestions):
            if col.button(s, use_container_width=True):
                st.session_state.pending_input = s
                st.rerun()

# 이전 대화 출력.
for msg in st.session_state.chat_history:
    with st.chat_message(msg["role"]):
        st.markdown(msg["content"])

# 입력: 직접 입력 또는 제안 클릭으로 주입된 값.
user_input = st.chat_input(
    "궁금한 것을 물어보세요. PDF를 업로드하면 예상문제도 만들어드려요."
)
if not user_input and st.session_state.get("pending_input"):
    user_input = st.session_state.pop("pending_input")

if user_input:
    st.session_state.chat_history.append({"role": "user", "content": user_input})
    with st.chat_message("user"):
        st.markdown(user_input)

    with st.chat_message("assistant"):
        try:
            # 방금 append한 사용자 질문은 question으로 따로 보내므로 slice에서 제외.
            recent_history = st.session_state.chat_history[:-1][-4:]
            result = GRAPH.invoke(
                {
                    "question": user_input,
                    "major": major,
                    "history": recent_history,
                },
                config={
                    "metadata": {"major": major, "question": user_input},
                    "tags": ["streamlit-chat", f"major:{major}"],
                },
            )
            answer = result.get("answer", "")
            st.markdown(answer)

            grounded = result.get("grounded")
            fidelity = result.get("fidelity")
            if grounded is not None:
                badge = "✅ 근거 있음" if grounded else "⚠️ 할루시네이션 의심"
                score_str = f" (충실도 {fidelity:.2f})" if fidelity is not None else ""
                st.caption(f"{badge}{score_str} — {result.get('verifier_note', '')}")

            with st.expander("🔍 검색·라우팅 디버그"):
                st.caption(f"의도: **{result.get('intent', '?')}**")
                cats = result.get("categories") or []
                st.caption(f"카테고리: **{', '.join(cats) if cats else '(없음)'}**")
                st.caption(f"확장 쿼리: `{result.get('expanded_query', '')}`")
                st.caption(f"라우터 사유: {result.get('route_rationale', '')}")
                contexts = result.get("contexts") or []
                if not contexts:
                    st.caption("(검색 결과 없음)")
                for c in contexts:
                    st.markdown(
                        f"- [{c['title']}]({c['url']}) · 유사도 {c['score']:.3f}"
                    )

            st.session_state.chat_history.append({"role": "assistant", "content": answer})
        except Exception as e:
            err = f"답변 생성 실패: {e}"
            st.error(err)
            st.session_state.chat_history.append({"role": "assistant", "content": err})
