# utils.py
import pandas as pd
import re
import difflib
import requests

def load_principios(path="data/principios.csv"):
    df = pd.read_csv(path, dtype=str).fillna("")
    if "weight" in df.columns:
        df["weight"] = pd.to_numeric(df["weight"], errors="coerce").fillna(1).astype(int)
    else:
        df["weight"] = 1
    df["keywords_list"] = df["keywords"].apply(lambda s: [k.strip().lower() for k in s.split(";") if k.strip()])
    df["case_id"] = df["case_id"].astype(str)
    return df

def normalize_text(text):
    if not isinstance(text, str):
        return ""
    text = text.lower()
    text = re.sub(r'[^a-z0-9à-úç\s]', ' ', text)
    text = re.sub(r'\s+', ' ', text).strip()
    return text

def extract_tokens(text):
    text = normalize_text(text)
    return text.split()

def match_by_keywords(user_text, keywords_list, threshold=0.8):
    norm = normalize_text(user_text)
    tokens = extract_tokens(norm)
    for kw in keywords_list:
        if kw in norm:
            return True
        close = difflib.get_close_matches(kw, tokens, n=1, cutoff=threshold)
        if close:
            return True
        kw_tokens = kw.split()
        if len(kw_tokens) > 1:
            for i in range(len(tokens) - len(kw_tokens) + 1):
                seq = " ".join(tokens[i:i+len(kw_tokens)])
                if difflib.SequenceMatcher(None, seq, kw).ratio() >= threshold:
                    return True
    return False

def evaluate_arguments(case_id, side, user_text, df_principios):
    df_case = df_principios[
        (df_principios["case_id"].astype(str) == str(case_id)) &
        (df_principios["side"].str.lower() == side.lower())
    ]

    df_case_all = df_principios[df_principios["case_id"].astype(str) == str(case_id)]

    matched = []
    score = 0

    for _, row in df_case.iterrows():
        if match_by_keywords(user_text, row["keywords_list"]):
            score += int(row["weight"])
            matched.append({
                "principle": row["principle"],
                "article": row["article"],
                "weight": int(row["weight"])
            })

    recommended = []
    for _, row in df_case.iterrows():
        if not match_by_keywords(user_text, row["keywords_list"]):
            recommended.append({
                "principle": row["principle"],
                "article": row["article"],
                "weight": int(row["weight"]),
                "keywords": row["keywords_list"]
            })

    counterarguments = []
    df_other_side = df_case_all[df_case_all["side"].str.lower() != side.lower()]
    for _, row in df_other_side.iterrows():
        counterarguments.append({
            "principle": row["principle"],
            "article": row["article"],
            "weight": int(row["weight"]),
            "keywords": row["keywords_list"]
        })

    return {
        "score": score,
        "matched": matched,
        "recommended": recommended,
        "counterarguments": counterarguments
    }

def fetch_proposicoes_camara(q=None, ano=None, tamanho=50, pagina=1):
    base_url = "https://dadosabertos.camara.leg.br/api/v2/proposicoes"
    params = {"itens": tamanho, "pagina": pagina}
    if q:
        params["descricao"] = q
    if ano:
        params["ano"] = ano
    try:
        resp = requests.get(base_url, params=params, timeout=10)
        resp.raise_for_status()
        data = resp.json().get("dados", [])
        result = []
        for item in data:
            result.append({
                "id": str(item.get("id", "")),
                "siglaNumero": item.get("siglaNumero", ""),
                "ano": item.get("ano", ""),
                "ementa": item.get("ementa", "") or "",
                "urlIntegra": item.get("uri", "")
            })
        return result
    except Exception as e:
        print("Erro ao buscar proposições:", e)
        return []

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

def auto_map_principles(df_princ, proposicao_text, new_case_id):
    proposicao_norm = normalize_text(proposicao_text)
    suggestions = []
    for _, row in df_princ.iterrows():
        kws = row.get("keywords_list", [])
        for kw in kws:
            if not kw:
                continue
            if kw in proposicao_norm:
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
        df_new["keywords_list"] = df_new["keywords"].apply(lambda s: [k.strip().lower() for k in s.split(";") if k.strip()])
        return df_new
    else:
        return pd.DataFrame(columns=df_princ.columns)
