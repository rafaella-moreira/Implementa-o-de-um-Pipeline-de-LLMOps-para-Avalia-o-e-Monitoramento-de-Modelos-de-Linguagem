import pandas as pd
import streamlit as st

import llmops_core as core

st.set_page_config(page_title="Implementação de um Pipeline de LLMOps para Avaliação e Monitoramento de Modelos de Linguagem", page_icon="", layout="wide")
st.title("Implementação de um Pipeline de LLMOps para Avaliação e Monitoramento de Modelos de Linguagem")
st.caption(
    " "
)

cfg = core.config()


with st.sidebar:
    st.header("Configuração")
    st.markdown(f"**Modelo:** `{core.modelo_ativo()}`")
    st.markdown(f"**Endpoint:** `{cfg['base_url']}`")
    if cfg["simulado"]:
        st.warning("Modo SIMULADO ativo: respostas fictícias, só para testar o fluxo.")
    elif not cfg["api_key"]:
        st.error("LLM_API_KEY não encontrada. Configure o arquivo .env.")
    else:
        st.success("API configurada.")
    st.divider()
    st.subheader("Versões de prompt (versionamento)")
    for chave, info in core.PROMPTS.items():
        st.markdown(f"**{info['versao']}**")
        st.caption(info["texto"])

aba_exec, aba_bateria, aba_aval, aba_comp, aba_hist = st.tabs(
    ["Executar", "Bateria de testes", "Avaliar", "Comparar versões", "Histórico"]
)

perguntas = core.carregar_perguntas()

# Executar
with aba_exec:
    st.subheader("Fazer uma pergunta")
    origem_pergunta = st.radio(
        "Origem da pergunta", ["Digitar livremente", "Escolher do conjunto de teste"], horizontal=True
    )
    pergunta_id, palavras_chave = None, None
    if origem_pergunta == "Digitar livremente":
        pergunta = st.text_area("Pergunta", "Explique o que é uma árvore em grafos.", height=90)
    else:
        escolhido = st.selectbox(
            "Pergunta",
            perguntas["id"].tolist(),
            format_func=lambda i: f"{i}. " + perguntas.loc[perguntas["id"] == i, "pergunta"].iloc[0],
        )
        linha_p = perguntas[perguntas["id"] == escolhido].iloc[0]
        pergunta, pergunta_id, palavras_chave = linha_p["pergunta"], int(escolhido), linha_p["palavras_chave"]

    chave = st.radio(
        "Versão do prompt",
        list(core.PROMPTS.keys()),
        horizontal=True,
        format_func=lambda k: core.PROMPTS[k]["versao"],
    )

    if st.button("Executar", type="primary"):
        if not pergunta.strip():
            st.warning("Digite uma pergunta.")
        else:
            try:
                with st.spinner("Consultando o modelo..."):
                    st.session_state["ultima"] = core.executar_e_registrar(
                        pergunta, chave, pergunta_id=pergunta_id,
                        palavras_chave=palavras_chave, origem="streamlit",
                    )
            except Exception as erro:
                st.session_state.pop("ultima", None)
                st.error(f"Erro: {erro}")

    ultima = st.session_state.get("ultima")
    if ultima:
        st.success(f"Execução {ultima['execucao_id']} registrada em execucoes.csv")
        c1, c2, c3, c4 = st.columns(4)
        c1.metric("Latência", f"{ultima['latencia_s']:.2f} s")
        c2.metric("Tokens de entrada", ultima["tokens_entrada"])
        c3.metric("Tokens de saída", ultima["tokens_saida"])
        c4.metric("Custo estimado", f"US$ {ultima['custo_estimado_usd']:.6f}")
        if ultima["tokens_estimados"]:
            st.caption(" A API não informou o uso: tokens estimados (4 caracteres por token).")
        if ultima["cobertura_auto"] is not None and not pd.isna(ultima["cobertura_auto"]):
            st.info(f"Cobertura automática de palavras-chave: {ultima['cobertura_auto']} / 5")
        st.markdown("**Resposta**")
        st.write(ultima["resposta"])


with aba_bateria:
    st.subheader("Rodar todas as perguntas com as versões escolhidas")
    st.write(
        "Executa cada pergunta do conjunto de teste com cada versão de prompt, "
        "para uma comparação justa (mesmas perguntas, mesmo modelo)."
    )
    versoes = st.multiselect("Versões", list(core.PROMPTS.keys()), default=["A", "B"])
    st.dataframe(perguntas[["id", "pergunta", "resposta_esperada"]], width="stretch", hide_index=True)
    if st.button("Rodar bateria completa"):
        if not versoes:
            st.warning("Escolha ao menos uma versão.")
        else:
            barra = st.progress(0.0, text="Iniciando...")

            def atualizar(feitas, total, msg):
                barra.progress(feitas / total, text=f"{feitas}/{total} · {msg}")

            linhas, erros = core.rodar_bateria(tuple(versoes), perguntas, origem="streamlit-bateria", progresso=atualizar)
            st.success(f"{len(linhas)} execuções registradas.")
            if erros:
                st.error(f"{len(erros)} falharam:")
                st.write(pd.DataFrame(erros, columns=["pergunta_id", "prompt", "erro"]))


with aba_aval:
    st.subheader("Avaliação manual (rubrica de 0 a 5)")
    with st.expander("Ver rubrica"):
        st.markdown(
            "Considere **correção**, **clareza** e **completude**:\n\n"
            "- **5**: correta, clara e completa\n"
            "- **4**: correta e clara, falta um detalhe\n"
            "- **3**: correta, mas incompleta ou confusa\n"
            "- **2**: parcialmente correta\n"
            "- **1**: majoritariamente incorreta\n"
            "- **0**: errada ou sem relação com a pergunta"
        )
    log = core.carregar_log()
    pendentes = log[log["qualidade_manual"].isna()] if not log.empty else log
    if pendentes.empty:
        st.info("Não há execuções pendentes de avaliação.")
    else:
        st.write(f"{len(pendentes)} execuções sem nota manual.")
        ids = pendentes["execucao_id"].tolist()
        sel = st.selectbox(
            "Execução",
            ids,
            format_func=lambda i: f"{i} · prompt {pendentes.loc[pendentes['execucao_id'] == i, 'prompt_versao'].iloc[0]}"
            f" · {pendentes.loc[pendentes['execucao_id'] == i, 'pergunta'].iloc[0][:50]}",
        )
        linha = pendentes[pendentes["execucao_id"] == sel].iloc[0]
        st.markdown(f"**Pergunta:** {linha['pergunta']}")
        if not pd.isna(linha["pergunta_id"]):
            esperada = perguntas.loc[perguntas["id"] == int(linha["pergunta_id"]), "resposta_esperada"]
            if not esperada.empty:
                st.markdown(f"**Resposta esperada:** {esperada.iloc[0]}")
        st.markdown("**Resposta do modelo:**")
        st.write(linha["resposta"])
        nota = st.slider("Nota", 0, 5, 3)
        if st.button("Salvar nota"):
            core.atualizar_nota_manual(sel, nota)
            st.rerun()


with aba_comp:
    st.subheader("Comparação entre versões de prompt")
    log = core.carregar_log()
    if log.empty:
        st.info("Ainda não há execuções. Rode a bateria de testes primeiro.")
    else:
        modelos = sorted(log["modelo"].dropna().unique().tolist())
        modelo_sel = st.selectbox("Filtrar por modelo", modelos, index=len(modelos) - 1)
        dados = log[log["modelo"] == modelo_sel]
        resumo = core.resumo_por_prompt(dados)
        st.dataframe(resumo, width="stretch")

        col1, col2, col3 = st.columns(3)
        with col1:
            st.markdown("**Qualidade média (0–5)**")
            st.bar_chart(resumo["qualidade_media"])
        with col2:
            st.markdown("**Latência média (s)**")
            st.bar_chart(resumo["latencia_media_s"])
        with col3:
            st.markdown("**Tokens de saída (média)**")
            st.bar_chart(resumo["tokens_saida_medio"])

        st.markdown("**Nota por pergunta**")
        por_pergunta = dados.pivot_table(
            index="pergunta_id", columns="prompt_versao", values="nota_final", aggfunc="mean"
        ).round(2)
        st.dataframe(por_pergunta, width="stretch")

        st.markdown("**Apoio à decisão (melhoria contínua)**")
        st.text(core.recomendar(resumo))
        st.caption(
            "A nota final usa a nota manual quando existe; caso contrário, usa a "
            "cobertura automática de palavras-chave."
        )


with aba_hist:
    st.subheader("Histórico completo (rastreabilidade)")
    log = core.carregar_log()
    if log.empty:
        st.info("Nenhuma execução registrada ainda.")
    else:
        st.dataframe(log.sort_values("timestamp", ascending=False), width="stretch", hide_index=True)
        st.download_button(
            "Baixar execucoes.csv",
            log.to_csv(index=False).encode("utf-8"),
            file_name="execucoes.csv",
            mime="text/csv",
        )
