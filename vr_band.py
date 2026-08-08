#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
VR 밴드 1년 시계열 백필 — GitHub Actions(서버)에서 매일 실행.
────────────────────────────────────────────────────────────
TQQQ 의 실제 '일별 종가'(최근 ~260거래일)를 받아 매 거래일 평가금(현재 보유주수×종가)을
계산하고, 목표 V 기준 밴드(하단 V×(1-band), 상단 V×(1+band))와 함께 state.json 의
vr_band_hist 에 기록한다. 앱은 이 데이터를 읽어 '1년치 일별' 밴드 그래프를 그린다.
→ 매 거래일 종가가 반영되므로 최신점이 매일 갱신된다.

주의: 과거 시점은 '현재 보유주수·현재 V' 기준의 근사 시계열이다(당시 실제 보유수량·V와
다를 수 있음). 가격 흐름을 반영해 밴드 대비 위치 추이를 보기 위한 참고용.
"""
import os, json, math, datetime

HERE = os.path.dirname(os.path.abspath(__file__))
STATE = os.path.join(HERE, "state.json")

def isnum(x):
    try:
        return x is not None and math.isfinite(float(x))
    except Exception:
        return False

def daily_closes(sym, days=260):
    """최근 days 거래일의 (날짜, 종가). 매 거래일 종가 → 밴드 그래프가 매일 갱신됨."""
    import yfinance as yf
    try:
        h = yf.Ticker(sym).history(period="1y", interval="1d")
        s = h["Close"].dropna()
        out = []
        for dt, px in s.items():
            px = float(px)
            if not (math.isfinite(px) and px > 0):
                continue
            out.append((dt.strftime("%Y-%m-%d"), round(px, 2)))
        return out[-days:]
    except Exception as e:
        print("[warn] daily_closes", sym, e)
        return []

def main():
    with open(STATE, encoding="utf-8") as f:
        state = json.load(f)

    hist = {}
    for v in state.get("vr", []):
        key = v.get("sym")                 # 'tqqq' / 'upro' (앱 키와 동일)
        if not key:
            continue
        sym = key.upper()                  # 'TQQQ' / 'UPRO' (야후 티커)
        ps = float(v.get("ps") or 0)
        V = float(v.get("V") or 0)
        band = float(v.get("band") or 0.15)
        dep = float(v.get("dep") or 0)     # 2주 정기 적립액
        rows = daily_closes(sym)
        if not rows or ps <= 0 or V <= 0:
            print("[skip]", sym, "ps=%s V=%s rows=%d" % (ps, V, len(rows)))
            continue
        N = len(rows)
        # 목표 V 는 라오어 VR에서 매 사이클(2주) 적립·성장으로 커진다 → 밴드가 우상향.
        # 과거 V를 정확히 알 수 없으므로 '적립 반영' 근사로 재구성: 현재 V에서 거래일당 적립(dep/10,
        # 2주≈10거래일)을 빼며 과거로 감. 단 가장 오래된 평가금×0.9 밑으로는 내려가지 않게 하한.
        wdep = dep / 10.0                   # 거래일당 적립 근사(2주 10거래일)
        eval_old = ps * rows[0][1]
        V_start = max(V - wdep * (N - 1), eval_old * 0.9)
        if V_start > V:
            V_start = V * 0.8
        series = []
        for i, (d, px) in enumerate(rows):
            frac = (i / (N - 1)) if N > 1 else 1.0
            Vi = V_start + (V - V_start) * frac      # 과거→현재 우상향(현재 V에 정확히 착지)
            loi = Vi * (1 - band)
            upi = Vi * (1 + band)
            ev = ps * px
            series.append({"date": d, "px": px, "eval": round(ev, 2),
                           "V": round(Vi, 2), "lo": round(loi, 2), "up": round(upi, 2),
                           "buy": ev <= loi, "sell": ev >= upi})
        hist[key] = {"ps": ps, "V": round(V, 2), "band": band,
                     "lo": round(V * (1 - band), 2), "up": round(V * (1 + band), 2),
                     "V_start": round(V_start, 2),
                     "updated": datetime.datetime.utcnow().strftime("%Y-%m-%d"),
                     "rows": series}
        print("[ok]", sym, "%d Fri · eval %.0f~%.0f · V %.0f→%.0f (우상향)"
              % (N, min(r["eval"] for r in series), max(r["eval"] for r in series), V_start, V))

    if hist:
        state["vr_band_hist"] = hist

    # ── 무한매수법 종합차트용 경량 가격 히스토리 (TQQQ·SOXL 일별 종가) ──
    # 앱의 무한매수법 탭이 이 데이터를 읽어 실제 1년 가격선 + 평단/익절선/수익률을 그린다.
    IB_TICKERS = ["TQQQ", "SOXL"]
    ibpx = {}
    for sym in IB_TICKERS:
        rows = daily_closes(sym)
        if not rows:
            print("[skip ib_px]", sym, "no rows")
            continue
        ibpx[sym.lower()] = {
            "updated": datetime.datetime.utcnow().strftime("%Y-%m-%d"),
            "rows": [{"date": d, "px": px} for (d, px) in rows],
        }
        print("[ok ib_px]", sym, "%d일 · %s~%s" % (len(rows), rows[0][0], rows[-1][0]))
    if ibpx:
        state["ib_px_hist"] = ibpx

    if hist or ibpx:
        with open(STATE, "w", encoding="utf-8") as f:
            json.dump(state, f, ensure_ascii=False, indent=2, allow_nan=False)
        print("[written] vr_band_hist:", ", ".join(hist.keys()) or "-",
              "| ib_px_hist:", ", ".join(ibpx.keys()) or "-")
    else:
        print("[nochange] no series computed")

if __name__ == "__main__":
    main()
