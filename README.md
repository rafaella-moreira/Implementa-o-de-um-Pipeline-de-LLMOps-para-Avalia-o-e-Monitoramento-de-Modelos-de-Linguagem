# Implementação de um Pipeline de LLMOps para Avaliação e Monitoramento de Modelos de Linguagem
Projeto para demonstrar os principais conceitos de LLMOps, utilizando Python, Jupyter Notebook, Streamlit, API de LLM, CSV.

## O que o projeto faz

O projeto recebe perguntas de computação, envia a um LLM com duas versões de prompt (A e B, mesmo modelo), registra cada execução em `execucoes.csv`, avalia a qualidade e compara latência, tokens e custo entre as versões.

| Conceito de LLMOps | Onde aparece |
|---|---|
| Versionamento | Dicionário `PROMPTS` em `llmops_core.py` (A-v1, B-v1...) |
| Observabilidade | Latência, tokens e custo medidos em `chamar_llm()` |
| Rastreabilidade | Cada execução gravada em `execucoes.csv` (resposta, data/hora, versão, modelo) |
| Avaliação | Cobertura automática de palavras-chave + nota manual 0 a 5 |
| Comparação de versões | Mesmas perguntas e mesmo modelo, só muda o prompt |
| Melhoria contínua | `recomendar()` e a criação da versão C no notebook |

## Estrutura de arquivos

```
llmops_projeto/
├── llmops_core.py      # lógica do projeto (prompts, API, métricas, CSV)
├── app.py              # interface Streamlit
├── llmops_demo.ipynb   # notebook com o experimento completo
├── perguntas.csv       # conjunto de teste (8 perguntas + resposta esperada + palavras-chave)
├── requirements.txt    # dependências
├── .env.example        # modelo de configuração
└── execucoes.csv       # criado automaticamente na primeira execução
```

## Passo a passo

### 1. Pré-requisitos
- Python 3.10 ou superior (`python --version`)
- Uma chave de API de um provedor de LLM (veja o passo 3)

### 2. Instalar as dependências
Dentro da pasta do projeto:

```bash
python -m venv .venv

# Windows:
.venv\Scripts\Activate.ps1
# Linux / macOS:
source .venv/bin/activate

pip install -r requirements.txt
```

### 3. Obter a chave de API
O projeto usa um provedor com API gratuita do Gemini

### 4. Configurar o `.env`
Copie o modelo e edite:

```bash
# Windows:  
copy .env.example .env
# Linux/macOS:
cp .env.example .env
```

Abra o `.env`, deixe apenas um bloco de provedor ativo e preencha com sua chave API o campo: `LLM_API_KEY`. Se usar API paga, preencha também `PRECO_ENTRADA_POR_MILHAO` e `PRECO_SAIDA_POR_MILHAO` com os preços da página do provedor; com cota gratuita, deixe 0.


### 5. Rodar o experimento no Jupyter

```bash
jupyter notebook llmops_demo.ipynb
```

Execute as células em ordem. O notebook:
1. mostra a configuração e os prompts versionados;
2. executa uma pergunta isolada;
3. roda a bateria (8 perguntas × prompts A e B = 16 execuções);
4. permite avaliar manualmente cada resposta (nota 0 a 5);
5. gera a tabela e os gráficos comparativos.

### 6. Rodar a interface Streamlit

```bash
streamlit run app.py
```

O navegador abre em `http://localhost:8501`. Abas:
- **Executar**: pergunta livre ou do conjunto de teste, escolha do prompt A/B.
- **Bateria de testes**: roda tudo de uma vez.
- **Avaliar**: nota manual de 0 a 5.
- **Comparar versões**: tabela e gráficos de qualidade, latência, tokens e custo.
- **Histórico**: todas as execuções, com download do CSV.

O notebook e o Streamlit gravam no mesmo `execucoes.csv`.