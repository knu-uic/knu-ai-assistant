"""AI 챗봇 페이지. LangGraph RAG 파이프라인 호출."""

import traceback

import streamlit as st

from retrieval.graph import GRAPH
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
            state_updates = {
                "question": user_input,
                "major": major,
            }
            with st.status("AI 비서가 질문을 확인하고 있습니다... 🌟", expanded=True) as status:
                st.write("🔍 질문 의도를 분석하고 검색 키워드를 정제하고 있어요...")
                for event in GRAPH.stream(
                    state_updates,
                    config={
                        "metadata": {"major": major, "question": user_input},
                        "tags": ["streamlit-chat", f"major:{major}"],
                    },
                    stream_mode="updates"
                ):
                    node_name = list(event.keys())[0]
                    node_output = event[node_name]
                    state_updates.update(node_output)
                    
                    if node_name == "router":
                        status.update(label="캠퍼스 공지사항을 검색하고 있습니다... 📚", state="running")
                        st.write("✓ 질문 분석 완료! 관련 카테고리 선정 및 쿼리 확장 완료")
                        st.write("⚡ 데이터베이스 및 첨부파일 내 관련 정보 수집 중...")
                    elif node_name == "retriever":
                        status.update(label="적절한 답변을 다듬고 요약하는 중입니다... ✍️", state="running")
                        st.write("✓ 정보 수집 완료! Reranker v3 기반 관련도 정렬 완료")
                        st.write("✍️ 수집된 자료를 조율하여 맞춤형 답변을 작성하고 있어요...")
                    elif node_name == "answerer":
                        from config import ENABLE_VERIFIER
                        if ENABLE_VERIFIER:
                            status.update(label="답변의 신뢰성을 자가 검증하고 있습니다... 🛡️", state="running")
                            st.write("✓ 답변 초안 완성!")
                            st.write("🛡️ 컨텍스트 기반 팩트체크 및 할루시네이션 의심 구간 검증 중...")
                
                status.update(label="답변 생성 완료! ✨", state="complete", expanded=False)

            result = state_updates
            answer = result.get("answer", "")
            st.markdown(answer)

            grounded = result.get("grounded")
            fidelity = result.get("fidelity")
            if grounded is not None:
                badge = "✅ 근거 있음" if grounded else "⚠️ 할루시네이션 의심"
                score_str = f" (충실도 {fidelity:.2f})" if fidelity is not None else ""
                st.caption(f"{badge}{score_str} — {result.get('verifier_note', '')}")

            with st.expander("🔍 검색·라우팅 디버그"):
                cats = result.get("categories") or []
                st.caption(f"카테고리: **{', '.join(cats) if cats else '(없음)'}**")
                st.caption(f"확장 쿼리: `{result.get('expanded_query', '')}`")
                st.caption(f"라우터 사유: {result.get('route_rationale', '')}")
                evidence_chunks = result.get("evidence_chunks") or []
                contexts = result.get("contexts") or []

                if evidence_chunks:
                    st.markdown("### 🧩 핵심 검색 청크")

                    for i, ev in enumerate(evidence_chunks, 1):
                        with st.container(border=True):
                            chunk_type = ev.get("chunk_type") or "unknown"
                            attachment_name = ev.get("attachment_name")

                            meta = [f"rerank {ev['score']:.3f}"]
                            meta.append(f"type={chunk_type}")

                            if attachment_name:
                                meta.append(f"attachment={attachment_name}")

                            st.markdown(
                                f"**[{i}] [{ev['title']}]({ev['url']})** · "
                                + " · ".join(meta)
                            )
                            st.code(ev.get("chunk", "")[:1200])

                st.markdown("### 📚 최종 참고 문서")

                if not contexts:
                    st.caption("(검색 결과 없음)")

                for i, c in enumerate(contexts, 1):
                    with st.container(border=True):
                        st.markdown(
                            f"**[{i}] [{c['title']}]({c['url']})** · rerank {c['score']:.3f}"
                        )

                        matched = c.get("matched_chunk") or ""
                        if matched:
                            st.caption("검색 매칭 청크")
                            st.code(matched[:1000])

                        summary = c.get("summary") or ""
                        attachment_names = c.get("attachment_names") or []
                        if summary:
                            st.caption("문서 요약")
                            st.write(summary[:500])
                        if attachment_names:
                            st.caption("첨부파일")
                            for name in attachment_names:
                                st.write(f"- {name}")

                        snippet = c.get("snippet") or ""
                        if snippet:
                            with st.expander("문서 본문 미리보기"):
                                st.code(snippet[:3000])

            st.session_state.chat_history.append({"role": "assistant", "content": answer})
        except Exception as e:
            traceback.print_exc()
            st.exception(e)
            st.session_state.chat_history.append(
                {"role": "assistant", "content": f"답변 생성 실패: {e}"}
            )
