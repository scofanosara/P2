# ==========================
# utils.py (final, com fallbacks e debug)
# ==========================
import pandas as pd
import re
import difflib
import unicodedata
import requests
import json
from typing import List, Dict, Any

# -------- Normalização --------
def _strip_accents(s: str) -> str:
    if s is None:
        return ""
    return "".join(c for c in unicodedata.normalize('NFD', s) if not unicodedata.combining(c))

def normalize_text(text: str) -> str:
    text = (text or "").casefold()
    text = _strip_accents(text)
    text = re.sub(r"[^a-z0-9\s]", " ", text)
    text = re.sub(r"\s+", " ", text).strip()
    return text

def extract_tokens(text: str) -> List[str]:
    return normalize_text(text).split()

# -------- Base de dados --------
def _split_kws(s: str) -> List[str]:
    parts = [p.strip() for p in str(s or "").split(";") if p.strip()]
    return [normalize_text(p) for p in parts]

def load_principios(path: str = "data/principios.csv") -> pd.DataFrame:
    df = pd.read_csv(path, dtype=str).fillna("")
    required = {"case_id", "case_title", "case_description", "side",
                "principle", "article", "weight", "keywords"}
    missing = required - set(df.columns)
    if missing:
        raise ValueError(f"Faltam colunas no CSV: {', '.join(sorted(missing))}")

    df["weight"] = pd.to_numeric(df["weight"], errors="coerce").fillna(1).astype(int)
    df["keywords_list"] = df.apply(
        lambda r: list(dict.fromkeys(
            _split_kws(r.get("keywords", "")) +
            _split_kws(r.get("principle", "")) +
            _split_kws(r.get("article", ""))
        )), axis=1
    )
    df["case_id"] = df["case_id"].astype(str)
    df["side"] = df["side"].astype(str).apply(normalize_text)   # "acusacao" / "defesa"
    return df

# -------- Matching --------
def match_by_keywords(user_text: str, keywords_list: List[str], threshold: float = 0.80) -> bool:
    norm = normalize_text(user_text)
    tokens = norm.split()
    for kw in keywords_list:
        if not kw:
            continue
        if kw in norm:
            return True
        if difflib.get_close_matches(kw, tokens, n=1, cutoff=threshold):
            return True
        kw_tokens = kw.split()
        if len(kw_tokens) > 1:
            for i in range(len(tokens) - len(kw_tokens) + 1):
                seq = " ".join(tokens[i:i + len(kw_tokens)])
                if difflib.SequenceMatcher(None, seq, kw).ratio() >= threshold:
                    return True
    return False

# -------- Avaliação --------
def evaluate_arguments(case_id: Any, side: str, user_text: str,
                       df_principios: pd.DataFrame, threshold: float = 0.80) -> Dict[str, Any]:
    case_str = str(case_id)
    side_norm = normalize_text(side)
    df_case_all = df_principios[df_principios["case_id"].astype(str) == case_str]
    df_case = df_case_all[df_case_all["side"] == side_norm]

    matched, recommended = [], []
    score = 0
    found_cache: Dict[int, bool] = {}

    for idx, row in df_case.iterrows():
        found = match_by_keywords(user_text, row["keywords_list"], threshold=threshold)
        found_cache[idx] = found
        if found:
            w = int(row.get("weight", 1))
            score += w
            matched.append({
                "principle": row["principle"],
                "article": row["article"],
                "weight": w,
                "matched_keyword_sample": ";".join(row["keywords_list"][:2])
            })

    for idx, row in df_case.iterrows():
        if not found_cache.get(idx, False):
            recommended.append({
                "principle": row["principle"],
                "article": row["article"],
                "weight": int(row.get("weight", 1)),
                "keywords": row["keywords_list"]
            })

    df_other_side = df_case_all[df_case_all["side"] != side_norm]
    counterarguments = [{
        "principle": r["principle"],
        "article": r["article"],
        "weight": int(r.get("weight", 1)),
        "keywords": r["keywords_list"]
    } for _, r in df_other_side.iterrows()]

    return {
        "score": score,
        "matched": matched,
        "recommended": recommended,
        "counterarguments": counterarguments,
    }

# -------- Integração Câmara (simples, resiliente e com debug) --------
def fetch_proposicoes_camara(q=None, ano=None, tamanho=50, pagina=1):
    """
    Busca robusta na API v2 da Câmara (sem 'ordenarPor'/'ordem' para evitar HTTP 400).
    Estratégia:
      1) Tenta 'busca'=q.
      2) Se falhar/vir vazio, tenta 'busca'=q + ano (se informado).
      3) Fallback: baixa 1–3 páginas sem texto e filtra localmente pela ementa normalizada.
    Retorna dict:
      - items: lista normalizada para o app
      - debug: JSON com tentativas (url, status_code, ok, params, etc.)
    """
    base_url = "https://dadosabertos.camara.leg.br/api/v2/proposicoes"
    headers = {
        "Accept": "application/json",
        "User-Agent": "Streamlit/SimuladorJuridico (+https://anatel.gov.br)"
    }

    def _normalize_items(items):
        out = []
        for item in items:
            sigla = (item.get("siglaTipo") or "").strip()
            numero = str(item.get("numero") or "").strip()
            ano_i = str(item.get("ano") or "").strip()
            sigla_numero = f"{sigla} {numero}/{ano_i}".strip()
            out.append({
                "id": str(item.get("id", "")),
                "siglaNumero": sigla_numero,
                "ano": ano_i,
                "ementa": item.get("ementa", "") or "",
                "urlIntegra": item.get("urlInteiroTeor") or item.get("uri", "")
            })
        return out

    debug_log = []

    def _call(params, label):
        try:
            r = requests.get(base_url, params=params, headers=headers, timeout=25)
            entry = {
                "label": label,
                "url": r.url,
                "status_code": r.status_code,
                "ok": r.ok,
                "elapsed_s": getattr(r.elapsed, "total_seconds", lambda: None)(),
                "params": params
            }
            try:
                j = r.json()
                entry["json_keys"] = list(j.keys())
                dados = j.get("dados", [])
            except Exception as je:
                entry["json_error"] = str(je)
                dados = []
            debug_log.append(entry)
            return (r.ok, dados)
        except Exception as e:
            debug_log.append({"label": label, "error": str(e), "params": params})
            return (False, [])

    # params base mínimos (evita 400)
    params_base = {
        "itens": int(tamanho),
        "pagina": int(pagina),
    }
    if ano:
        params_base["ano"] = str(ano)

    # 1) 'busca' simples
    if q:
        ok, dados = _call({**params_base, "busca": q}, "busca")
        if ok and dados:
            return {"items": _normalize_items(dados),
                    "debug": json.dumps(debug_log, ensure_ascii=False, indent=2)}

    # 2) 'busca' + ano (se informado)
    if q and ano:
        ok, dados = _call({**params_base, "busca": q, "ano": str(ano)}, "busca+ano")
        if ok and dados:
            return {"items": _normalize_items(dados),
                    "debug": json.dumps(debug_log, ensure_ascii=False, indent=2)}

    # 3) Fallback: baixar 1–3 páginas sem texto e filtrar localmente pela ementa
    coletado = []
    max_paginas = max(1, min(3, int(pagina)))  # busca até 3 páginas a partir da pedida
    for p in range(int(pagina), int(pagina) + max_paginas):
        ok, dados = _call({**params_base, "pagina": p}, f"fallback_p{p}")
        if ok and dados:
            coletado.extend(dados)

    if q:
        q_norm = normalize_text(q)
        coletado = [d for d in coletado if q_norm in normalize_text(d.get("ementa", "") or "")]

    return {"items": _normalize_items(coletado),
            "debug": json.dumps(debug_log, ensure_ascii=False, indent=2)}

def proposicao_to_case(proposicao):
    cid = f"camara_{proposicao.get('id')}"
    title = proposicao.get("siglaNumero") or f"Proposição {proposicao.get('id')}"
    desc = proposicao.get("ementa", "")
    return {
        "case_id": cid,
        "case_title": title,
        "case_description": desc,
        "source_url": proposicao.get("urlIntegra", "")
    }

def auto_map_principles(df_princ: pd.DataFrame, proposicao_text: str, new_case_id: str) -> pd.DataFrame:
    proposicao_norm = normalize_text(proposicao_text)
    suggestions = []
    for _, row in df_princ.iterrows():
        kws = row.get("keywords_list", [])
        for kw in kws:
            if kw and kw in proposicao_norm:
                suggestions.append({
                    "case_id": str(new_case_id),
                    "case_title": row.get("case_title", ""),
                    "case_description": proposicao_text[:200],
                    "side": row.get("side", ""),
                    "principle": row.get("principle", ""),
                    "article": row.get("article", ""),
                    "weight": int(row.get("weight", 1)),
                    "keywords": ";".join(kws)
                })
                break
    if suggestions:
        df_new = pd.DataFrame(suggestions)
        df_new["keywords_list"] = df_new["keywords"].apply(
            lambda s: [k.strip().casefold() for k in str(s).split(";") if k.strip()]
        )
        df_new["side"] = df_new["side"].astype(str).apply(normalize_text)
        return df_new
    return pd.DataFrame(columns=df_princ.columns)
