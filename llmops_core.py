import os
import time
import unicodedata
import uuid
from datetime import datetime
from pathlib import Path

import pandas as pd
from dotenv import load_dotenv

BASE_DIR = Path(__file__).resolve().parent
load_dotenv(BASE_DIR / ".env")

LOG_PATH = BASE_DIR / "execucoes.csv"
PERGUNTAS_PATH = BASE_DIR / "perguntas.csv"


PROMPTS = {
    "A": {
        "versao": "A-v1",
        "texto": "Responda à pergunta do usuário.",
    },
    "B": {
        "versao": "B-v1",
        "texto": (
            "Responda com clareza e precisão, explique os conceitos importantes "
            "e utilize um exemplo simples quando ajudar na compreensão. "
            "Se não souber a resposta, informe isso."
        ),
    },
}

COLUNAS = [
    "execucao_id",
    "timestamp",
    "origem",
    "pergunta_id",
    "pergunta",
    "prompt",
    "prompt_versao",
    "modelo",
    "resposta",
    "latencia_s",
    "tokens_entrada",
    "tokens_saida",
    "tokens_estimados",
    "custo_estimado_usd",
    "cobertura_auto",
    "qualidade_manual",
]


def config():
    """Lê a configuração a cada chamada, para refletir mudanças no .env."""
    return {
        "api_key": os.getenv("LLM_API_KEY", "").strip(),
        "base_url": os.getenv("LLM_BASE_URL", "https://api.openai.com/v1").strip(),
        "modelo": os.getenv("LLM_MODEL", "gpt-4o-mini").strip(),
        "preco_entrada": float(os.getenv("PRECO_ENTRADA_POR_MILHAO", "0") or 0),
        "preco_saida": float(os.getenv("PRECO_SAIDA_POR_MILHAO", "0") or 0),
        "simulado": os.getenv("LLM_SIMULADO", "0").strip() == "1",
    }


def modelo_ativo():
    """Nome do modelo que será gravado no log."""
    cfg = config()
    return "simulado" if cfg["simulado"] else cfg["modelo"]


def estimar_tokens(texto):
    """Estimativa (~4 caracteres por token) quando a API não informa o uso."""
    return max(1, len(texto) // 4)


def calcular_custo(tokens_entrada, tokens_saida):
    """Custo estimado em USD, com base nos preços por 1 milhão de tokens do .env."""
    cfg = config()
    return (
        tokens_entrada * cfg["preco_entrada"] + tokens_saida * cfg["preco_saida"]
    ) / 1_000_000


def _normalizar(texto):
    """Minúsculas e sem acentos, para comparar palavras-chave de forma justa."""
    texto = unicodedata.normalize("NFKD", str(texto))
    return "".join(c for c in texto if not unicodedata.combining(c)).lower()


def cobertura_palavras_chave(resposta, palavras_chave):
    """
    Avaliação AUTOMÁTICA simples: fração das palavras-chave
    esperadas que aparecem na resposta, convertida para a escala 0 a 5.
    Retorna None se não houver palavras-chave.
    """
    if not palavras_chave:
        return None
    chaves = [_normalizar(p).strip() for p in str(palavras_chave).split(";") if p.strip()]
    if not chaves:
        return None
    resposta_norm = _normalizar(resposta)
    acertos = sum(1 for c in chaves if c in resposta_norm)
    return round(5 * acertos / len(chaves), 2)


def _resposta_simulada(pergunta, chave_prompt):
    """Resposta só para testar o fluxo sem gastar a API."""
    base = f"Resposta de teste para: {pergunta}"
    if chave_prompt != "A":
        base += " Exemplo simples: "
    return base


def chamar_llm(pergunta, chave_prompt, temperatura=0.2, max_tentativas=3):
    """
    Envia a pergunta ao LLM usando o prompt escolhido e mede latência e uso.
    """
    cfg = config()
    prompt = PROMPTS[chave_prompt]

    if cfg["simulado"]:
        inicio = time.perf_counter()
        time.sleep(0.05)
        texto = _resposta_simulada(pergunta, chave_prompt)
        latencia = time.perf_counter() - inicio
        t_in = estimar_tokens(prompt["texto"] + pergunta)
        t_out = estimar_tokens(texto)
        return {
            "resposta": texto,
            "latencia_s": round(latencia, 3),
            "tokens_entrada": t_in,
            "tokens_saida": t_out,
            "tokens_estimados": True,
        }

    if not cfg["api_key"]:
        raise RuntimeError(
            "LLM_API_KEY não encontrada."
        )

    from openai import OpenAI
    import openai

    cliente = OpenAI(api_key=cfg["api_key"], base_url=cfg["base_url"])
    mensagens = [
        {"role": "system", "content": prompt["texto"]},
        {"role": "user", "content": pergunta},
    ]

    ultimo_erro = None
    for tentativa in range(max_tentativas):
        inicio = time.perf_counter()
        try:
            resp = cliente.chat.completions.create(
                model=cfg["modelo"],
                messages=mensagens,
                temperature=temperatura,
            )
            latencia = time.perf_counter() - inicio
            texto = resp.choices[0].message.content or ""
            uso = getattr(resp, "usage", None)
            if uso is not None and getattr(uso, "prompt_tokens", None) is not None:
                t_in, t_out, estimados = uso.prompt_tokens, uso.completion_tokens, False
            else:
                t_in = estimar_tokens(prompt["texto"] + pergunta)
                t_out = estimar_tokens(texto)
                estimados = True
            return {
                "resposta": texto.strip(),
                "latencia_s": round(latencia, 3),
                "tokens_entrada": t_in,
                "tokens_saida": t_out,
                "tokens_estimados": estimados,
            }
        except (openai.AuthenticationError, openai.NotFoundError, openai.BadRequestError):
            raise  # erro de configuração: repetir não adianta
        except Exception as erro:  # limite de taxa, instabilidade de rede etc.
            ultimo_erro = erro
            if tentativa < max_tentativas - 1:
                time.sleep(2 * (tentativa + 1))
    raise RuntimeError(f"Falha ao chamar a API após {max_tentativas} tentativas: {ultimo_erro}")



def registrar_execucao(linha):
    """Acrescenta uma execução ao CSV """
    df = pd.DataFrame([linha]).reindex(columns=COLUNAS)
    novo = not LOG_PATH.exists()
    df.to_csv(LOG_PATH, mode="a", header=novo, index=False, encoding="utf-8")


def executar_e_registrar(
    pergunta, chave_prompt, pergunta_id=None, palavras_chave=None, origem="app"
):
    """Fluxo completo de UMA execução: chama o LLM, mede, avalia e registra."""
    resultado = chamar_llm(pergunta, chave_prompt)
    linha = {
        "execucao_id": uuid.uuid4().hex[:8],
        "timestamp": datetime.now().isoformat(timespec="seconds"),
        "origem": origem,
        "pergunta_id": pergunta_id,
        "pergunta": pergunta,
        "prompt": chave_prompt,
        "prompt_versao": PROMPTS[chave_prompt]["versao"],
        "modelo": modelo_ativo(),
        "resposta": resultado["resposta"],
        "latencia_s": resultado["latencia_s"],
        "tokens_entrada": resultado["tokens_entrada"],
        "tokens_saida": resultado["tokens_saida"],
        "tokens_estimados": resultado["tokens_estimados"],
        "custo_estimado_usd": round(
            calcular_custo(resultado["tokens_entrada"], resultado["tokens_saida"]), 8
        ),
        "cobertura_auto": cobertura_palavras_chave(resultado["resposta"], palavras_chave),
        "qualidade_manual": None,
    }
    registrar_execucao(linha)
    return linha


def carregar_perguntas():
    """Conjunto de teste: perguntas, respostas esperadas e palavras-chave."""
    return pd.read_csv(PERGUNTAS_PATH, encoding="utf-8")


def carregar_log():
    """Lê o histórico de execuções e cria a coluna 'nota_final'."""
    if not LOG_PATH.exists():
        df = pd.DataFrame(columns=COLUNAS + ["nota_final"])
        return df
    df = pd.read_csv(LOG_PATH, encoding="utf-8")
    for col in ["latencia_s", "tokens_entrada", "tokens_saida", "custo_estimado_usd",
                "cobertura_auto", "qualidade_manual"]:
        df[col] = pd.to_numeric(df[col], errors="coerce")
    # Nota final = nota manual (0-5) quando existe; senão, a cobertura automática.
    df["nota_final"] = df["qualidade_manual"].fillna(df["cobertura_auto"])
    return df


def atualizar_nota_manual(execucao_id, nota):
    """Grava a nota manual (0 a 5) de uma execução já registrada."""
    df = pd.read_csv(LOG_PATH, encoding="utf-8")
    df["qualidade_manual"] = pd.to_numeric(df["qualidade_manual"], errors="coerce")
    df.loc[df["execucao_id"] == execucao_id, "qualidade_manual"] = float(nota)
    df.to_csv(LOG_PATH, index=False, encoding="utf-8")


def rodar_bateria(versoes=("A", "B"), perguntas=None, origem="bateria", progresso=None):
    """
    Executa TODAS as perguntas do conjunto de teste com cada versão de prompt.
    É o que torna a comparação justa: mesmas perguntas, mesmo modelo.
    """
    if perguntas is None:
        perguntas = carregar_perguntas()
    total = len(perguntas) * len(versoes)
    feitas, linhas, erros = 0, [], []
    for _, p in perguntas.iterrows():
        for v in versoes:
            try:
                linhas.append(
                    executar_e_registrar(
                        p["pergunta"], v,
                        pergunta_id=int(p["id"]),
                        palavras_chave=p.get("palavras_chave"),
                        origem=origem,
                    )
                )
            except Exception as erro:
                erros.append((int(p["id"]), v, str(erro)))
            feitas += 1
            if progresso:
                progresso(feitas, total, f"Pergunta {int(p['id'])} · prompt {v}")
    return linhas, erros


def resumo_por_prompt(df):
    """Tabela comparativa: média de qualidade, latência, tokens e custo por versão."""
    if df.empty:
        return pd.DataFrame()
    resumo = (
        df.groupby("prompt_versao")
        .agg(
            execucoes=("execucao_id", "count"),
            qualidade_media=("nota_final", "mean"),
            latencia_media_s=("latencia_s", "mean"),
            tokens_entrada_medio=("tokens_entrada", "mean"),
            tokens_saida_medio=("tokens_saida", "mean"),
            custo_total_usd=("custo_estimado_usd", "sum"),
        )
        .round(4)
    )
    return resumo


def recomendar(resumo):
    """Qual versão manter e quais trade-offs existem?"""
    if resumo.empty or resumo["qualidade_media"].isna().all():
        return "Ainda não há dados de qualidade suficientes para comparar as versões."
    melhor_q = resumo["qualidade_media"].idxmax()
    mais_rapido = resumo["latencia_media_s"].idxmin()
    mais_barato = resumo["custo_total_usd"].idxmin()
    linhas = [
        f"Maior qualidade média: {melhor_q} ({resumo.loc[melhor_q, 'qualidade_media']:.2f} de 5).",
        f"Menor latência média: {mais_rapido} ({resumo.loc[mais_rapido, 'latencia_media_s']:.2f} s).",
        f"Menor custo total estimado: {mais_barato} (US$ {resumo.loc[mais_barato, 'custo_total_usd']:.6f}).",
    ]
    if melhor_q != mais_rapido or melhor_q != mais_barato:
        linhas.append(
            "Há um trade-off: a versão de melhor qualidade não é a mais rápida/barata. "
        )
    else:
        linhas.append(f"A versão {melhor_q} vence em todas as métricas e deve ser mantida.")
    return "\n".join(linhas)
