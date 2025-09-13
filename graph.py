# graph.py — 열에너지 방출 그래프(제출·공유·관찰) — Cloud 안정판
# 실행 파일은 반드시 graph.py로 지정하세요.

import json, re, sys, logging, inspect
import pandas as pd
import altair as alt
import streamlit as st

logging.basicConfig(stream=sys.stdout, level=logging.INFO)

ACTIVITY_ID = "2025-heat-curve-01"

st.set_page_config(page_title="열에너지 방출 그래프 그리기", layout="wide")
st.markdown("""<style>
html, body, [class*="css"]{font-family:"Noto Sans KR","Malgun Gothic",system-ui,sans-serif;}
</style>""", unsafe_allow_html=True)
st.title("열에너지 방출 그래프 그리기")
st.caption("시간(분)과 온도(°C)를 표에 입력 → 미리보기 확인 → 제출")

# ---------- Streamlit 버전 호환 shim ----------
def _supports_param(func, name: str) -> bool:
    try: return name in inspect.signature(func).parameters
    except Exception: return False
def _stretch_kwargs_for(func):
    if _supports_param(func, "width"): return {"width": "stretch"}
    if _supports_param(func, "use_container_width"): return {"use_container_width": True}
    return {}
def st_data_editor_stretch(*args, **kwargs):
    f = st.data_editor;   kwargs.update(_stretch_kwargs_for(f)); return f(*args, **kwargs)
def st_dataframe_stretch(*args, **kwargs):
    f = st.dataframe;     kwargs.update(_stretch_kwargs_for(f)); return f(*args, **kwargs)
def st_altair_chart_stretch(chart, **kwargs):
    f = st.altair_chart;  kwargs.update(_stretch_kwargs_for(f)); return f(chart, **kwargs)

# ---------- DB 설정/상태 (오프라인 안전) ----------
@st.cache_resource(show_spinner=False)
def get_db_conf():
    try:
        c = st.secrets["connections"]["mysql"]
        return {"host": c["host"], "port": int(c.get("port",3306)),
                "user": c["user"], "password": c["password"], "database": c["database"]}
    except Exception:
        return None
DB_CONF = get_db_conf()

def probe_db(conf):
    """DB 연결을 한번만 시험. 실패해도 서버는 계속 동작."""
    try:
        import mysql.connector as mc
        conn = mc.connect(host=conf["host"], port=conf["port"], user=conf["user"],
                          password=conf["password"], database=conf["database"],
                          connection_timeout=5, charset="utf8mb4")
        conn.close()
        return True, ""
    except Exception as e:
        return False, str(e)

if DB_CONF:
    _ok, _err = probe_db(DB_CONF)
    DB_STATUS = "ONLINE" if _ok else f"OFFLINE: { _err }"
else:
    DB_STATUS = "OFFLINE: secrets 미설정"
st.info("DB 상태: " + DB_STATUS)

def run_sql(sql: str, params=None, fetch: bool=False):
    if not (DB_CONF and DB_STATUS.startswith("ONLINE")):
        return ([], []) if fetch else None
    import mysql.connector as mc
    conn = mc.connect(host=DB_CONF["host"], port=DB_CONF["port"], user=DB_CONF["user"],
                      password=DB_CONF["password"], database=DB_CONF["database"],
                      connection_timeout=5, charset="utf8mb4")
    conn.autocommit = True
    cur = conn.cursor()
    try:
        cur.execute(sql, params or ())
        if fetch:
            rows = cur.fetchall()
            cols = [d[0] for d in cur.description]
            return rows, cols
    finally:
        try: cur.close(); conn.close()
        except Exception: pass

# ---------- 데이터 조회(캐시) ----------
@st.cache_data(ttl=5, show_spinner=False)
def load_all(activity_id: str):
    try:
        rows, cols = run_sql(
            """
            SELECT g1.id, s.name, s.grade, s.class, g1.submitted_at, g1.data_json
            FROM graph1 g1 JOIN students s ON s.id = g1.id
            WHERE g1.activity_id=%s
            ORDER BY g1.id ASC
            """, (activity_id,), fetch=True
        )
        out=[]
        for r in rows:
            d=dict(zip(cols,r))
            d["data"]=pd.DataFrame(json.loads(d["data_json"]))
            out.append(d)
        return out, None
    except Exception as e:
        return [], str(e)

# ---------- 탭 ----------
tab_submit, tab_dash, tab_detail = st.tabs(["📤 제출(학생)", "📊 대시보드", "🔎 학생 상세"])

# 제출(학생)
with tab_submit:
    with st.form("submit_form"):
        sid = st.text_input("학번(5자리, 예: 10130)", max_chars=5, help="1학년 01반 30번 → 10130")
        init = pd.DataFrame({"시간(분)":[0,1,2,3,4], "온도(°C)":[20.0,None,None,None,None]})
        df = st_data_editor_stretch(
            init, num_rows="dynamic",
            column_config={
                "시간(분)": st.column_config.NumberColumn("시간(분)", min_value=0, max_value=60, step=1),
                "온도(°C)": st.column_config.NumberColumn("온도(°C)", min_value=-20.0, max_value=150.0, step=0.1),
            },
        )
        st.caption("※ 시간 0–60분, 온도 -20–150°C. 모든 셀을 숫자로 채워야 제출됩니다.")

        prev = df.dropna()
        if not prev.empty:
            chart = alt.Chart(prev.sort_values("시간(분)")).mark_line(point=True).encode(
                x=alt.X("시간(분):Q"), y=alt.Y("온도(°C):Q")
            ).properties(title=f"학번 {sid.strip() if sid else ''}", height=280)
            st_altair_chart_stretch(chart)

        if st.form_submit_button("제출"):
            if not re.fullmatch(r"\d{5}", sid or ""):
                st.error("학번은 숫자 5자리여야 합니다. 예: 10130"); st.stop()
            if df.isnull().any().any():
                st.error("빈 칸이 있습니다. 모든 셀을 숫자로 입력하세요."); st.stop()
            if not ((df["시간(분)"].between(0,60)).all() and (df["온도(°C)"].between(-20,150)).all()):
                st.error("허용 범위를 벗어난 값이 있습니다."); st.stop()

            if not DB_STATUS.startswith("ONLINE"):
                st.error("DB가 설정되지 않아 저장할 수 없습니다. Cloud Secrets를 확인하세요.")
            else:
                ok_stu, _ = run_sql("SELECT 1 FROM students WHERE id=%s", (sid,), fetch=True)
                if not ok_stu:
                    st.error("해당 학번이 students 테이블에 없습니다. (교사용: 먼저 students에 등록)")
                else:
                    ordered = df.sort_values("시간(분)")
                    payload = json.dumps(ordered.to_dict(orient="records"), ensure_ascii=False)
                    try:
                        run_sql(
                            """
                            INSERT INTO graph1(activity_id, id, data_json)
                            VALUES (%s, %s, %s)
                            ON DUPLICATE KEY UPDATE data_json=VALUES(data_json),
                                                    submitted_at=CURRENT_TIMESTAMP
                            """,
                            (ACTIVITY_ID, sid, payload)
                        )
                        load_all.clear()
                        st.success("제출 완료! ‘📊 대시보드’에서 전체 결과를 확인하세요.")
                    except Exception as e:
                        st.error(f"[DB오류] 저장 실패: {e}")

# 대시보드
with tab_dash:
    auto = st.toggle("자동 새로고침(10초)", value=True)
    if auto:
        try:
            from streamlit_autorefresh import st_autorefresh
            st_autorefresh(interval=10_000, key="dash_autorefresh")
        except Exception:
            st.info("자동 새로고침 패키지 미설치. (requirements.txt에 streamlit-autorefresh 포함)")

    st.button("🔄 수동 새로고침", on_click=load_all.clear)
    data, err = load_all(ACTIVITY_ID) if DB_STATUS.startswith("ONLINE") else ([], None)
    if err: st.warning(f"[조회 경고] {err}")

    if not data:
        st.info("아직 제출된 데이터가 없습니다.")
    else:
        df_all = pd.DataFrame(
            [{"id":d["id"],"name":d["name"],"grade":d["grade"],"class":d["class"],
              "submitted_at":d["submitted_at"],"data":d["data"]} for d in data]
        ).sort_values("id")

        for (g, c), gdf in df_all.groupby(["grade","class"]):
            st.subheader(f"{g}학년 {c:02d}반")
            cols = st.columns(3)
            for i, row in enumerate(gdf.itertuples(index=False)):
                with cols[i % 3]:
                    st.markdown(f"**학번 {row.id}** — {row.name}")
                    ch = alt.Chart(row.data).mark_line(point=True).encode(
                        x=alt.X("시간(분):Q"), y=alt.Y("온도(°C):Q")
                    ).properties(height=220, title=f"{row.id}")
                    st_altair_chart_stretch(ch)

# 학생 상세
with tab_detail:
    data, _ = load_all(ACTIVITY_ID) if DB_STATUS.startswith("ONLINE") else ([], None)
    opts = [f'{d["id"]} | {d["name"]}' for d in data]
    sel = st.selectbox("학생 선택", opts, index=0 if opts else None)
    if sel:
        tid = sel.split("|")[0].strip()
        tgt = next(d for d in data if d["id"] == tid)
        st.markdown(f"### 학번 {tgt['id']} — {tgt['name']}")
        big = alt.Chart(tgt["data"]).mark_line(point=True).encode(
            x=alt.X("시간(분):Q"), y=alt.Y("온도(°C):Q")
        ).properties(height=420, title=f"{tgt['id']}")
        st_altair_chart_stretch(big)
        st_dataframe_stretch(tgt["data"])
        st.download_button(
            "⬇️ CSV 다운로드",
            data=tgt["data"].to_csv(index=False).encode("utf-8-sig"),
            file_name=f"{ACTIVITY_ID}_{tgt['id']}.csv",
            mime="text/csv",
        )
