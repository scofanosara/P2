# ==========================
# app.py (final, com debug de API)
# ==========================
import streamlit as st
import pandas as pd
from utils import (
    load_principios, fetch_proposicoes_camara,
    proposicao_to_case, auto_map_principles, evaluate_arguments
)
from io import StringIO
import csv
import datetime

st.set_page_config(page_title="Simulador Jurídico para Estudantes", layout="wide")
st.title("Simulador Jurídico para Estudantes ⚖️")

# --- Carregar base local (ou upload)
st.sidebar.header("Fonte de dados")
use_local = st.sidebar.checkbox("Usar base local (data/principios.csv)", True)
uploaded = st.sidebar.file_uploader("Substituir base local (CSV)", type=["csv"])

try:
    if uploaded is not None:
        df_princ = load_principios(uploaded)
        use_local = True
    elif use_local:
        df_princ = load_principios("data/principios.csv")
    else:
        st.warning("Selecione a base local ou envie um CSV.")
        st.stop()
except Exception as e:
    st.error(f"Erro ao carregar a base: {e}")
    st.stop()

# --- Câmara: ligar/desligar busca
use_camara = st.sidebar.checkbox("Buscar proposições da Câmara", False)

# --- Estado dos resultados da Câmara
if "camara_results" not in st.session_state:
    st.session_state.camara_results = []
if "camara_selected_idx" not in st.session_state:
    st.session_state.camara_selected_idx = 0

# Se desmarcar a opção, limpa o estado
if not use_camara:
    st.session_state.camara_results = []
    st.session_state.camara_selected_idx = 0

selected_prop = None

# --- Bloco de busca da Câmara (opcional)
if use_camara:
    st.sidebar.markdown("**Buscar proposições (Câmara)**")
    q = st.sidebar.text_input("Termo de busca (ex.: saúde, plano de saúde)", value="saúde")
    ano = st.sidebar.text_input("Ano (opcional)", value="")
    tamanho = st.sidebar.number_input(
        "Resultados por página", min_value=10, max_value=100, value=30, step=10
    )
    pagina = st.sidebar.number_input("Página", min_value=1, value=1, step=1)

    if st.sidebar.button("🔎 Buscar proposições"):
        with st.spinner("Buscando proposições na API da Câmara..."):
            data = fetch_proposicoes_camara(
                q=q or None, ano=ano or None, tamanho=int(tamanho), pagina=int(pagina)
            )
            # aceita dict (items+debug) ou lista
            if isinstance(data, dict):
                st.session_state.camara_results = data.get("items", [])
                dbg = data.get("debug")
                if dbg:
                    with st.expander("Debug da chamada à API"):
                        st.code(dbg, language="json")
            else:
                st.session_state.camara_results = data

        if st.session_state.camara_results:
            st.sidebar.success(f"{len(st.session_state.camara_results)} resultado(s) encontrados.")
        else:
            st.sidebar.warning("Nenhuma proposição encontrada ou erro na API. Tente outra página ou remova o filtro de ano.")

    camara_results = st.session_state.camara_results

    if camara_results:
        options = [
            f"{i+1:02d}. {p['siglaNumero']} — {p['ementa'][:80]}... (id={p['id']})"
            for i, p in enumerate(camara_results)
        ]
        sel_label = st.sidebar.selectbox(
            "Selecione uma proposição",
            options=options,
            index=min(st.session_state.camara_selected_idx, len(options) - 1),
        )
        st.session_state.camara_selected_idx = options.index(sel_label)
        selected_prop = camara_results[st.session_state.camara_selected_idx]
        st.sidebar.write("URL da proposição:", selected_prop.get("urlIntegra") or "-")
        st.sidebar.markdown("---")

# --- Montar lista de casos: local + (opcional) câmara
cases_local = (
    df_princ[["case_id", "case_title", "case_description"]]
    .drop_duplicates()
    .to_dict("records")
)
camara_case = proposicao_to_case(selected_prop) if selected_prop else None

case_map = {
    str(r["case_id"]): {
        "case_id": str(r["case_id"]),
        "case_title": r["case_title"],
        "case_description": r["case_description"],
    }
    for r in cases_local
}
if camara_case:
    case_map[camara_case["case_id"]] = camara_case

if not case_map:
    st.error("Nenhum caso disponível. Carregue um CSV válido em 'Fonte de dados'.")
    st.stop()

# Ordena chaves de forma inteligente (numéricas primeiro em ordem crescente)
case_keys = sorted(
    case_map.keys(),
    key=lambda k: (not str(k).isdigit(), int(str(k)) if str(k).isdigit() else str(k).lower())
)

selected_case_key = st.selectbox(
    "Escolha o caso (local ou proposição da Câmara)",
    options=case_keys,
    format_func=lambda k: f"{k} — {case_map[k]['case_title']}",
)
case_info = case_map[selected_case_key]
st.subheader(case_info["case_title"])
st.write(case_info["case_description"])

# --- Mapeamento automático (apenas para caso da Câmara sem base local)
temp_added_df = pd.DataFrame()
if selected_case_key.startswith("camara_"):
    existing = df_princ[df_princ["case_id"] == selected_case_key]
    if existing.empty:
        st.info("Não há princípios associados a esta proposição na base local.")
        if st.button("🔁 Mapear automaticamente princípios a partir da base"):
            df_new = auto_map_principles(
                df_princ, case_info["case_description"], new_case_id=selected_case_key
            )
            if not df_new.empty:
                temp_added_df = df_new
                st.success(f"Foram sugeridos {len(df_new)} princípios para o caso.")
                st.dataframe(
                    temp_added_df[["side", "principle", "article", "weight", "keywords"]],
                    use_container_width=True,
                )
            else:
                st.warning("Nenhuma correspondência automática encontrada.")

# --- Base efetiva
df_effective = (
    pd.concat([df_princ, temp_added_df], ignore_index=True)
    if not temp_added_df.empty
    else df_princ.copy()
)

# --- Argumentação
st.markdown("## Atuar como acusação ou defesa")
side_choice = st.radio("Escolha o lado:", ["acusacao", "defesa"], index=1, key="side_radio")

st.markdown("### Escreva seus argumentos / princípios")
user_text = st.text_area(
    "Digite princípios, artigos ou argumentos (ex.: 'direito à saúde; CF 196; dignidade da pessoa humana')",
    height=180,
)

# Debug opcional: mostra o que conta ponto
with st.expander("Debug – ver o que conta ponto neste caso/lado"):
    df_dbg = df_effective[
        (df_effective["case_id"].astype(str) == str(selected_case_key))
        & (df_effective["side"] == side_choice)
    ][["side", "principle", "article", "weight", "keywords", "keywords_list"]]
    st.dataframe(df_dbg, use_container_width=True)

# --- Avaliação e relatório
if st.button("Avaliar argumentação"):
    with st.spinner("Avaliando..."):
        result = evaluate_arguments(selected_case_key, side_choice, user_text, df_effective)

    st.success(f"Pontuação: {result['score']} pontos")

    st.markdown("**Argumentos identificados:**")
    if result["matched"]:
        for m in result["matched"]:
            st.write(f"- {m['principle']} — {m['article']} (peso {m['weight']})")
    else:
        st.info("Nenhum princípio identificado automaticamente — tente usar palavras-chave mais objetivas.")

    st.markdown("**Princípios sugeridos que faltaram:**")
    if result["recommended"]:
        for r in result["recommended"]:
            st.write(f"- {r['principle']} — {r['article']} (peso {r['weight']}) — keywords: {', '.join(r['keywords'])}")
    else:
        st.write("Nenhum princípio faltante catalogado para sua posição.")

    st.markdown("**Argumentos que a parte contrária pode usar:**")
    if result["counterarguments"]:
        for c in result["counterarguments"]:
            st.write(f"- {c['principle']} — {c['article']} (peso {c['weight']})")
    else:
        st.write("Nenhum contra-argumento catalogado para este caso.")

    # Relatório CSV
    rows = []
    ts = datetime.datetime.now().isoformat(timespec="seconds")
    for m in result["matched"]:
        rows.append({
            "timestamp": ts,
            "case_id": selected_case_key,
            "case_title": case_info["case_title"],
            "side": side_choice,
            "status": "matched",
            "principle": m["principle"],
            "article": m["article"],
            "weight": m["weight"],
        })
    for r in result["recommended"]:
        rows.append({
            "timestamp": ts,
            "case_id": selected_case_key,
            "case_title": case_info["case_title"],
            "side": side_choice,
            "status": "recommended",
            "principle": r["principle"],
            "article": r["article"],
            "weight": r["weight"],
        })

    if rows:
        fieldnames = sorted(set().union(*(d.keys() for d in rows)))
        sio = StringIO()
        writer = csv.DictWriter(sio, fieldnames=fieldnames, extrasaction="ignore")
        writer.writeheader()
        for row in rows:
            writer.writerow(row)
        st.download_button(
            "📥 Baixar relatório (CSV)",
            data=sio.getvalue().encode("utf-8"),
            file_name=f"relatorio_{selected_case_key}_{side_choice}.csv",
            mime="text/csv",
        )

st.markdown("---")
st.write(
    "Dicas: use termos objetivos (ex.: 'CF 196', 'direito à saúde', 'furto', 'tipicidade'). "
    "O algoritmo usa palavras-chave para identificar os princípios."
)
