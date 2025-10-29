# app.py
import streamlit as st
import pandas as pd
from utils import (
    load_principios, fetch_proposicoes_camara,
    proposicao_to_case, auto_map_principles, evaluate_arguments
)
from io import BytesIO
import csv
import datetime

st.set_page_config(page_title="Simulador Jurídico para Estudantes", layout="wide")
st.title("Simulador Jurídico para Estudantes ⚖️")

# --- Carregar base de princípios (padrão)
DATA_PATH = "data/principios.csv"
df_princ = load_principios(DATA_PATH)

# --- Sidebar: escolher fonte
st.sidebar.header("Fonte de dados")
use_local = st.sidebar.checkbox("Usar base local (principios.csv)", True)
use_camara = st.sidebar.checkbox("Buscar proposições da Câmara", False)

uploaded = st.sidebar.file_uploader("Substituir base local (CSV)", type=["csv"])
if uploaded is not None:
    df_princ = load_principios(uploaded)
    use_local = True

# --- Câmara options
camara_results = []
selected_prop = None
if use_camara:
    st.sidebar.markdown("**Buscar proposições (Câmara)**")
    q = st.sidebar.text_input("Termo de busca (ex.: saúde, plano de saúde)", value="saúde")
    ano = st.sidebar.text_input("Ano (opcional)", value="")
    tamanho = st.sidebar.number_input("Resultados por página", min_value=10, max_value=100, value=30)
    buscar = st.sidebar.button("🔎 Buscar proposições")
    if buscar:
        with st.spinner("Buscando proposições na API da Câmara..."):
            camara_results = fetch_proposicoes_camara(q=q or None, ano=ano or None, tamanho=tamanho, pagina=1)
        if not camara_results:
            st.sidebar.warning("Nenhuma proposição encontrada ou erro na API.")
    # listar resultados
    if camara_results:
        options = [f"{p['siglaNumero']} — {p['ementa'][:80]}... (id={p['id']})" for p in camara_results]
        sel_idx = st.sidebar.selectbox("Selecione uma proposição", options=options)
        sel_i = options.index(sel_idx)
        selected_prop = camara_results[sel_i]
        st.sidebar.write("URL da proposição:", selected_prop.get("urlIntegra"))
        st.sidebar.markdown("---")

# --- Construir lista de casos disponíveis
# Casos locais: extraia casos distintos da base local
cases_local = df_princ[["case_id","case_title","case_description"]].drop_duplicates().to_dict("records")
# Se usamos câmara e há proposicao selecionada, crie um case temporário a partir dela
camara_case = None
if selected_prop:
    camara_case = proposicao_to_case(selected_prop)
    # mostrar resumo
    st.subheader(f"Proposição selecionada: {camara_case['case_title']}")
    st.write(camara_case["case_description"])
    st.write("Fonte:", camara_case.get("source_url","-"))

# Montar seleção de casos (priorizar câmara case se presente)
case_map = {}
for r in cases_local:
    case_map[str(r["case_id"])] = {"case_id": str(r["case_id"]), "case_title": r["case_title"], "case_description": r["case_description"]}
if camara_case:
    case_map[camara_case["case_id"]] = {"case_id": camara_case["case_id"], "case_title": camara_case["case_title"], "case_description": camara_case["case_description"]}

case_keys = list(case_map.keys())
selected_case_key = st.selectbox("Escolha o caso (local ou proposição da Câmara)", options=case_keys, format_func=lambda k: f"{k} — {case_map[k]['case_title']}")
case_info = case_map[selected_case_key]
st.write(case_info["case_description"])

# --- Se o caso selecionado for da câmara e não houver princípios mapeados, oferecer mapeamento automático
temp_added_df = pd.DataFrame()
if selected_case_key.startswith("camara_"):
    # verificar se já existem entradas na base para esse case_id
    existing = df_princ[df_princ["case_id"] == selected_case_key]
    if existing.empty:
        st.info("Não há princípios associados a esta proposição na base local.")
        if st.button("🔁 Mapear automaticamente princípios semelhantes a partir da base"):
            # executa mapeamento
            df_new = auto_map_principles(df_princ, case_info["case_description"], new_case_id=selected_case_key)
            if not df_new.empty:
                # append temporário (na memória) para a sessão
                temp_added_df = df_new
                st.success(f"Foram sugeridos {len(df_new)} princípios para o caso.")
            else:
                st.warning("Nenhuma correspondência automática encontrada. Você pode adicionar manualmente pela base CSV.")
        if not temp_added_df.empty:
            st.write("Princípios sugeridos (temporários):")
            st.dataframe(temp_added_df[["side","principle","article","weight","keywords"]])
else:
    st.write("Caso local selecionado.")

# --- Preparar df_princ efetivo (com eventuais linhas temporárias)
if not temp_added_df.empty:
    df_effective = pd.concat([df_princ, temp_added_df], ignore_index=True)
else:
    df_effective = df_princ.copy()

# --- Interface de argumentação
st.markdown("## Atuar como acusação ou defesa")
side = st.radio("Escolha o lado:", ["acusacao", "defesa"], index=1)
st.markdown("### Escreva seus argumentos / princípios")
user_text = st.text_area("Digite princípios, artigos ou argumentos (ex.: 'direito à saúde; CF 196; dignidade da pessoa humana')", height=180)

if st.button("Avaliar argumentação"):
    with st.spinner("Avaliando..."):
        result = evaluate_arguments(selected_case_key, side, user_text, df_effective)
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

    # relatório CSV
    report_rows = []
    ts = datetime.datetime.now().isoformat(timespec='seconds')
    for m in result["matched"]:
        report_rows.append({
            "timestamp": ts,
            "case_id": selected_case_key,
            "case_title": case_info["case_title"],
            "side": side,
            "principle_matched": m["principle"],
            "article": m["article"],
            "weight": m["weight"]
        })
    for r in result["recommended"]:
        report_rows.append({
            "timestamp": ts,
            "case_id": selected_case_key,
            "case_title": case_info["case_title"],
            "side": side,
            "principle_suggested": r["principle"],
            "article": r["article"],
            "weight": r["weight"]
        })
    if report_rows:
        csv_buf = BytesIO()
        fieldnames = list(report_rows[0].keys())
        writer = csv.DictWriter(csv_buf, fieldnames=fieldnames)
        writer.writeheader()
        for rr in report_rows:
            writer.writerow(rr)
        csv_buf.seek(0)
        st.download_button("📥 Baixar relatório (CSV)", data=csv_buf, file_name=f"relatorio_{selected_case_key}_{side}.csv", mime="text/csv")
