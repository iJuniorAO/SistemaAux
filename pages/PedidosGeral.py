import streamlit as st
import requests
import pandas as pd
import numpy as np
import io
import re
from rapidfuzz import process, fuzz
from datetime import datetime, time, timedelta, timezone
from supabase import create_client, Client
from utils import (
    carregar_dados_onedrive,
    carregar_dados_onedrive_rp,
    converte_ultima_modificacao,
)

# --- CONFIGURAÇÃO DA PÁGINA ---
st.set_page_config(page_title="Conversor de Pedidos", layout="wide")

if st.session_state.get("debugger"):
    st.error(":material/Terminal: APP EM TESTE")

# --- BARRA LATERAL (FLAG DO SISTEMA) ---
with st.sidebar:
    st.markdown("## Configurações do Sistema")
    # A FLAG PRINCIPAL:
    sistema = st.pills(
        "Selecione o ERP de Destino:", ["AlterData", "RPOne"], default="RPOne"
    )

    if sistema == "RPOne":
        doc_padrao = st.text_input("Documento Padrão", value="6101")
        link_produto = st.secrets["onedrive"]["links"]["produto_rp"]
        link_produto_extra = None
    if sistema == "AlterData":
        link_produto = st.secrets["onedrive"]["links"]["produto"]
        link_produto_extra = st.secrets["onedrive"]["links"]["produto_extra"]

    IMPLANTACAO = st.toggle("Implantação", value=True)


# --- CONSTANTES ---
AGORA = datetime.now()
DDMMAA = AGORA.strftime("%d%m%y")
AAAAMMDD = AGORA.strftime("%Y%m%d%H%M")[:11]
SEGUNDOS = str(AGORA.second)
# variavel de implantação será usada para caso seja utilizado o txt da AlterData e seja importado para o sistema da RP faça o devido tratamento


REGRAS_PRAZO = [
    ("tolerancia", time(10, 5), "red", "Timer_Off", "Prazo de Pedido Finalizado!"),
    (
        "PRAZO",
        time(10, 0),
        "orange",
        "More_Time",
        "Prazo de Pedido Finalizado! - Tolerância 5 minutos",
    ),
    (
        "aviso1",
        time(9, 45),
        "yellow",
        "Clock_Loader_90",
        "Faltam 15 minutos para fazer pedidos",
    ),
    (
        "aviso2",
        time(9, 0),
        "green",
        "Clock_Loader_60",
        "Falta 1 hora para fazer pedidos",
    ),
]
colunas_produto = [
    "CodProduto",
    "CodGrupo",
    "Descricao",
    "SiglaUn",
    "MinVenda",
    "PrecoUnPd",
    "CodPrincProd",
    "Estoq",
    "Obs",
    "Grade",
    "Falta",
    "Novo",
    "Prom",
    "DescMax",
    "Fam",
]
colunas_produto_extra = ["CodProduto", "Fam", "ListaCodCaract", "DescComplementar"]
colunas_Pedidos = ["QtCx", "Sigla", "Descricao"]


# --- CONEXÃO BD ---
url = st.secrets["connections"]["supabase"]["url"]
key = st.secrets["connections"]["supabase"]["key"]
supabase: Client = create_client(url, key)


# --- FUNÇÕES ---
def abrir_arquivo_txt(arquivo, colunas=None):
    try:
        if isinstance(arquivo, str):
            arquivo = io.StringIO(arquivo)
        return pd.read_csv(
            arquivo, sep="|", header=None, names=colunas, encoding="latin1"
        )
    except Exception as e:
        st.error(f"Erro ao ler arquivo {e}")
        st.stop()


def procuranumero(linha):
    linha = linha.strip()
    partes = linha.split()
    if not partes:
        return None
    codigo_cru = partes.pop(0)

    if re.search(r"\d", codigo_cru):
        match = re.match(r"(\d+)(.*)", codigo_cru)
        if match:
            numero = match.group(1)
            resto_texto = match.group(2)
            if resto_texto:
                partes.insert(0, resto_texto)
            partes.insert(0, numero)
            return " ".join(partes)
    return None


def limpa_texto(uploaded_file):
    conteudo = uploaded_file.read().decode("utf-8")
    linhas = conteudo.splitlines()

    linhas_novas = []
    alteracoes_feitas = 0
    erros_nao_corrigidos = []
    linhas_removidas = 0

    for i, linha in enumerate(linhas):
        num_l = i + 1
        if linha.strip() == "":
            linhas_removidas += 1
            continue

        if linha.strip() != linha:
            linha = linha.strip()

        if IMPLANTACAO:
            if sistema == "RPOne":
                if linha == linha.upper():
                    linha = linha.title()

        colunas = linha.split()
        if len(colunas) >= 1 and not colunas[0].isdigit():
            sugestao = procuranumero(linha)
            if sugestao:
                linhas_novas.append(sugestao)
                alteracoes_feitas += 1
            else:
                linhas_novas.append(linha)
                erros_nao_corrigidos.append(
                    f"Linha {num_l}: Sem correção automática:  \n{linha}."
                )
        else:
            linhas_novas.append(linha)

    texto_corrigido = "\n".join(linhas_novas)
    return io.StringIO(texto_corrigido)


def trata_pedido_loja(df_Import_loja, colunas_Pedidos):
    Linhas_Pedidos = len(df_Import_loja)
    df_Import_loja[colunas_Pedidos] = (
        df_Import_loja[0].astype(str).str.split(" ", n=2, expand=True)
    )
    df_Import_loja = df_Import_loja.drop(columns=[0])

    num = pd.to_numeric(df_Import_loja["QtCx"], errors="coerce")
    df_ok = df_Import_loja[num.notna()].copy()
    df_erro = df_Import_loja[num.isna()].copy()
    df_ok["QtCx"] = df_ok["QtCx"].astype(float)

    return df_ok, df_erro, Linhas_Pedidos


def encontra_melhor_match(descricao_erro, escolhas_base, threshold=60):
    match = process.extractOne(
        descricao_erro, escolhas_base, scorer=fuzz.token_set_ratio
    )
    if match and match[1] >= threshold:
        return pd.Series(
            [match[0], match[1]], index=["Descricao_Sugerida", "Score_Similaridade"]
        )
    return pd.Series([None, 0], index=["Descricao_Sugerida", "Score_Similaridade"])


@st.cache_data(
    ttl=86400, show_spinner="Carregando dados lojas", show_time=True, scope="session"
)
def carregar_lojas_banco_dados():
    try:
        # Traz as colunas pra ambos (AlterData só usa Filial, RPOne usa ambas)
        resposta = (
            supabase.table("Lojas")
            .select("Filial, cod_cliente_loja")
            .order("Filial")
            .execute()
        )
        return pd.DataFrame(resposta.data)
    except Exception as e:
        print(f"Erro ao buscar lojas: {e}")
        return pd.DataFrame()


def confere_prazo_pedido():
    for descricao, horario_limite, cor, icone, msg in REGRAS_PRAZO:
        if AGORA.time() >= horario_limite:
            st.markdown(f"### :{cor}[:material/{icone}:] {msg}")
            return
    st.markdown("### :green[:material/Clock_Loader_10:] Dentro do prazo para Pedidos")


# FUNÇÃO UNIFICADA DE PROCESSAMENTO
def processar_pedidos(df, df_extra, df_Pedido_Loja, sis_flag):
    # df = df[(df["Fam"] != 900000008) & (df["Estoq"] > 0)].copy()
    # DEBBUG - retirado filtro para testes em produção utilizar o filtro acima
    df = df[(df["Fam"] != 900000008)].copy()

    if sis_flag == "AlterData":
        df = df[["CodProduto", "CodGrupo", "Descricao", "Estoq", "Fam"]]
        if df_extra is not None:
            df = df.merge(
                df_extra[["CodProduto", "ListaCodCaract"]], on="CodProduto", how="left"
            )
        CONDICOES = [
            (
                df["ListaCodCaract"].astype(str).str.contains("000002", na=False)
                if "ListaCodCaract" in df.columns
                else False
            ),
            df["CodGrupo"].isin([9, 14]) if "CodGrupo" in df.columns else False,
        ]
        df["TIPO"] = np.select(CONDICOES, ["PESO", "CONG"], default="SECO")

    if sis_flag == "RPOne":
        if df_extra is not None and not df_extra.empty:
            df = df.merge(
                df_extra[["CodProduto", "ListaCodCaract"]], on="CodProduto", how="left"
            )

        CONDICOES = [
            (
                df["ListaCodCaract"].astype(str).str.contains("KG", na=False)
                if "ListaCodCaract" in df.columns
                else False
            ),
            (
                df["TIPO"].isin(["REFRIGERADO", "CONGELADO"])
                if "TIPO" in df.columns
                else False
            ),
        ]
        df["TIPO"] = np.select(
            CONDICOES, ["PESO", "CONG"], default="SECO"
        )  # Padronizado pra TIPO em vez de CLASSE

    df["Codigo"] = df["CodProduto"].astype(str).str.rjust(13)

    df_Pedido_Final = df.merge(
        df_Pedido_Loja[["QtCx", "Descricao"]],
        on="Descricao",
        how="outer",
        indicator=True,
    )

    df_Erro_Desc = df_Pedido_Final[df_Pedido_Final["_merge"] == "right_only"].copy()
    df_Pedido_Final = df_Pedido_Final[df_Pedido_Final["QtCx"].notna()].copy()

    df_Pedido_Final["Descricao"] = (
        df_Pedido_Final["Descricao"].astype(str).str.replace(",", ".")
    )

    if sis_flag == "AlterData":
        ultimo = df_Pedido_Final["Descricao"].astype(str).str.split().str[-1]
        ultimo_numerico = pd.to_numeric(ultimo, errors="coerce")
        df_Pedido_Final["CONV"] = ultimo_numerico.fillna(1).astype(float)
        df_Pedido_Final["TOTAL"] = df_Pedido_Final["QtCx"] * df_Pedido_Final["CONV"]
        df_Pedido_Final["VALOR_STR"] = df_Pedido_Final["TOTAL"].apply(
            lambda x: f"{x:09.3f}".replace(".", ",")
        )
    if sis_flag == "RPOne":
        df_Pedido_Final["PrecoUnPd"] = (
            df_Pedido_Final["PrecoUnPd"] * df_Pedido_Final["QtCx"]
        )
        df_Pedido_Final["TOTAL"] = df_Pedido_Final["QtCx"]
        df_Pedido_Final["VALOR_STR"] = df_Pedido_Final["TOTAL"].apply(
            lambda x: f"{x:03.3f}"
        )

    return df_Pedido_Final, df_Erro_Desc, df


def salvar_pedido_banco_dados(loja, tipo, pedido_gerado, pedido_original, obs=None):
    if loja != "ATACADO":
        try:
            dados = {
                "data_pedido": AGORA.strftime("%Y-%m-%d"),
                "hora_pedido": AGORA.strftime("%H:%M"),
                "loja": loja,
                "tipo_pedido": tipo,
                "pedido_erp": pedido_gerado,  # Padronizado pra string
                "pedido_original": pedido_original.getvalue(),
                "obs": obs,
            }
            supabase.table("PedidosLojas").insert(dados).execute()
            return st.success(
                f":material/Check: Pedido {loja} {tipo} salvo no Banco de Dados!"
            )
        except Exception as e:
            return st.error(
                f":material/Close: ERRO - Não foi possível salvar no BD {e}"
            )
    else:
        return st.info("Pedidos Atacado não são Salvos no Banco de Dados")


def formata_pedido_rp(df_sub, cod_cliente, doc_pad):

    df_sub = df_sub[["CodProduto", "VALOR_STR", "Obs", "PrecoUnPd"]].copy()
    df_sub["CodProduto"] = df_sub["CodProduto"].astype(np.int64).astype(str)
    df_sub = df_sub.fillna("")

    prefixo = f"PV^{DDMMAA}^{doc_pad}^{AAAAMMDD}{cod_cliente}^{cod_cliente}^"
    sufixo = "^^0^512^006^^^V^^0.000^"

    linhas_formatadas = [
        f"{prefixo}{'^'.join(row.astype(str))}{sufixo}" for _, row in df_sub.iterrows()
    ]
    return "\n".join(linhas_formatadas)


# --- INTERFACE STREAMLIT PRINCIPAL ---
st.title(":material/Folder_Check_2: Conversor de Pedidos para Importação")

if not sistema:
    st.error("Selecione o ERP Destino (barra lateral)")

confere_prazo_pedido()
st.space()

tab1, tab2, tab3 = st.tabs(
    [
        ":material/Database: Base de Dados",
        ":material/Database_Upload: Pedidos Lojas",
        ":material/Database_Upload: Pedido Atacado",
    ]
)

# Vars padrão
f_produto_auto = None
f_extra_auto = None
df_lojas = pd.DataFrame()
LOJAS = []
desativa_manual = False
produtos_cadastrados = 0

with tab1:
    st.header(f"Upload de Bases de Dados ({sistema})")
    bd_automatico = st.toggle("Deseja pegar arquivos automaticamente?", value=True)

    if bd_automatico:
        desativa_manual = True
        df_lojas = carregar_lojas_banco_dados()
        LOJAS = df_lojas["Filial"].tolist() if not df_lojas.empty else []

        if sistema == "AlterData":
            if "dados_onedrive" not in st.session_state:
                st.session_state.dados_onedrive = carregar_dados_onedrive(link_produto)
            if "dados_onedrive_extra" not in st.session_state:
                st.session_state.dados_onedrive_extra = carregar_dados_onedrive(
                    link_produto_extra
                )

            response = st.session_state.dados_onedrive
            response_extra = st.session_state.dados_onedrive_extra

            if response["falha"]:
                st.error("Falha ao pegar produto.txt")
            if response_extra["falha"]:
                st.error("Falha ao pegar produto_extra.txt")

            if response["data"]:
                ultima_modificacao_dt = converte_ultima_modificacao(response["data"])
                st.write(
                    f"Ultima modificação base: :red[{ultima_modificacao_dt.strftime('%H:%M:%S')}]  | :red[{ultima_modificacao_dt.strftime('%d/%m/%Y')}]"
                )

            f_produto_auto = response["resp"]
            f_extra_auto = response_extra["resp"]

        if sistema == "RPOne":
            if "dados_onedrive_rp" not in st.session_state:
                st.session_state.dados_onedrive_rp = carregar_dados_onedrive_rp(
                    link_produto
                )

            response = st.session_state.dados_onedrive_rp
            if response["falha"]:
                st.error("Falha ao pegar CSV do ERP")

            if response["data"]:
                ultima_modificacao_dt = converte_ultima_modificacao(response["data"])
                st.write(
                    f"Ultima modificação base: :red[{ultima_modificacao_dt.strftime('%H:%M:%S')}]  | :red[{ultima_modificacao_dt.strftime('%d/%m/%Y')}]"
                )

            f_produto_auto = response["df"]

    col1, col2 = st.columns(2)
    with col1:
        f_produto = st.file_uploader(
            f":material/Barcode: Arquivo {'00001produto.txt' if sistema == 'AlterData' else 'Produtos CSV'}",
            disabled=desativa_manual,
        )
    with col2:
        if sistema == "AlterData":
            f_extra = st.file_uploader(
                ":material/Add: Arquivo 00001produtoextra.txt",
                disabled=desativa_manual,
                type="txt",
            )
        if sistema == "RPOne":
            f_extra = None

with tab2:
    st.header("Upload de Pedidos da Loja")
    f_pedido = st.file_uploader(":material/Article: Pedido Loja.txt", type="txt")
with tab3:
    st.header("Upload de Pedidos do Atacado")
    f_pedido_atacado = st.file_uploader(
        ":material/Article: Pedido Atacado.xlsx", type="xlsx"
    )

if not LOJAS and not df_lojas.empty:
    LOJAS = df_lojas["Filial"].tolist()
elif not LOJAS:
    LOJAS = ["TESTE"]

loja_pedido = st.selectbox(
    ":red[Seleciona Loja]", LOJAS, index=None, placeholder="Seleciona a loja"
)
st.space()

# --- GATILHO DE EXECUÇÃO ---
liberado = (f_produto is not None or desativa_manual) and (f_pedido or f_pedido_atacado)
if liberado:
    if f_pedido and f_pedido_atacado:
        st.error("Inserido Pedido Loja e Pedido Atacado - Informar somente 1")
        st.stop()
    if not loja_pedido:
        st.error(":material/Priority_High: Selecione uma Loja")
        st.stop()

    # Prepara base
    if desativa_manual:
        if sistema == "AlterData":
            df = abrir_arquivo_txt(f_produto_auto, colunas_produto)
            df_extra = abrir_arquivo_txt(f_extra_auto, colunas_produto_extra)
        if sistema == "RPOne":
            df = f_produto_auto
            df_extra = None
    else:
        if sistema == "AlterData":
            df = abrir_arquivo_txt(f_produto, colunas_produto)
            df_extra = abrir_arquivo_txt(f_extra, colunas_produto_extra)
        if sistema == "RPOne":
            df = pd.read_csv(
                f_produto, sep=None, engine="python"
            )  # Caso upado manualmente
            df_extra = None

    produtos_cadastrados = len(df)

    # Importa Pedido da Loja/Atacado
    if f_pedido:
        f_pedido = limpa_texto(f_pedido)
        df_Pedido_Loja, df_Erro_Qt, Linhas_Pedidos = trata_pedido_loja(
            abrir_arquivo_txt(f_pedido), colunas_Pedidos
        )
    else:
        df_pedido_atacado = pd.read_excel(f_pedido_atacado, engine="openpyxl")
        df_pedido_atacado = df_pedido_atacado[
            ["CodProduto", "Descricao", "R$/Un", "QUANTIDADE CX"]
        ].dropna(subset=["QUANTIDADE CX"])
        if df_pedido_atacado.empty:
            st.error("Pedido Em Branco")
            st.stop()

        df_pedido_atacado["Qt Solicitada"] = pd.to_numeric(
            df_pedido_atacado["QUANTIDADE CX"], errors="coerce"
        )
        linhas_com_erro = df_pedido_atacado[df_pedido_atacado["Qt Solicitada"].isna()]
        df_pedido_atacado = df_pedido_atacado.dropna()
        if not linhas_com_erro.empty:
            st.error("Há linhas com formatação errada")
            st.dataframe(linhas_com_erro)

        df_pedido_atacado["Qt Solicitada"] = (
            df_pedido_atacado["QUANTIDADE CX"].astype(int).astype(str)
            + " cx "
            + df_pedido_atacado["Descricao"]
        )
        texto_atacado = "\n".join(df_pedido_atacado["Qt Solicitada"])
        df_Pedido_Loja, df_Erro_Qt, Linhas_Pedidos = trata_pedido_loja(
            abrir_arquivo_txt(io.StringIO(texto_atacado)), colunas_Pedidos
        )

    # Ponto focal unificado
    df_Pedido_Final, df_Erro_Desc, df_Produto_Base = processar_pedidos(
        df, df_extra, df_Pedido_Loja, sistema
    )
    st.write(f"Foram importados: {Linhas_Pedidos} linhas")

    # Tratamento Visualização de Erros
    aplicar_correcao = False
    if not df_Erro_Qt.empty or not df_Erro_Desc.empty:
        with st.expander(
            ":orange[:material/Warning:] Ver Erros de Importação", expanded=True
        ):
            if not df_Erro_Qt.empty:
                st.warning(f"[{len(df_Erro_Qt)}] Linhas com erro na quantidade:")
                st.dataframe(df_Erro_Qt)
            if not df_Erro_Desc.empty:
                st.error(f"[{len(df_Erro_Desc)}] Itens não encontrados na base:")
                lista_base = df_Produto_Base["Descricao"].tolist()
                matches = df_Erro_Desc["Descricao"].apply(
                    lambda x: encontra_melhor_match(x, lista_base)
                )
                df_validacao = pd.concat([df_Erro_Desc, matches], axis=1).sort_values(
                    by="Score_Similaridade", ascending=False
                )

                st.write(
                    f"Encontrados Automaticamente: {df_validacao['Descricao_Sugerida'].notna().sum()}/{df_validacao['Descricao'].notna().sum()} itens"
                )
                grid_correcao = st.dataframe(
                    df_validacao[
                        [
                            "QtCx",
                            "Descricao",
                            "Descricao_Sugerida",
                            "Score_Similaridade",
                        ]
                    ],
                    selection_mode="multi-row",
                    on_select="rerun",
                )

                aplicar_correcao = st.toggle("Usar correções automáticas", value=False)
                if aplicar_correcao:
                    ind_aprovados = grid_correcao["selection"]["rows"]
                    df_Aprovado = df_validacao.iloc[ind_aprovados]
                    mapeamento = dict(
                        zip(df_Aprovado["Descricao"], df_Aprovado["Descricao_Sugerida"])
                    )

                    df_Pedido_Corrigido = df_Pedido_Loja.copy()
                    df_Pedido_Corrigido["Descricao"] = df_Pedido_Corrigido[
                        "Descricao"
                    ].replace(mapeamento)

                    df_Pedido_Final, df_Erro_Desc, _ = processar_pedidos(
                        df, df_extra, df_Pedido_Corrigido, sistema
                    )
    else:
        st.success("Sem erro de exportação")
        st.toast("Todos itens importados", icon="✅")

    # DOWNLOADS DE SUCESSO
    if df_Pedido_Final.empty:
        st.error("ERRO NA IMPORTAÇÃO - Arquivo fora do padrão")
        st.stop()
    else:
        st.divider()
        st.header(
            f":blue[{loja_pedido}] - Baixar Pedidos {sistema} {'- :red[Corrigidos]' if aplicar_correcao else ''}"
        )

        c1, c2, c3 = st.columns(3)
        for tipo, col in [("SECO", c1), ("CONG", c2), ("PESO", c3)]:
            df_sub = df_Pedido_Final[df_Pedido_Final["TIPO"] == tipo]
            with col:
                if not df_sub.empty:
                    st.success(f"[{len(df_sub)}] Pedido {tipo} pronto!")

                    # Logica de formatação depende do sistema
                    if sistema == "AlterData":
                        output = io.StringIO()
                        df_sub[["Codigo", "VALOR_STR"]].to_csv(
                            output, sep="\t", index=False, header=False
                        )
                        formato_arquivo = ".txt"
                        conteudo_arquivo = output.getvalue()
                    if sistema == "RPOne":
                        cod_cliente = (
                            df_lojas.loc[
                                df_lojas["Filial"] == loja_pedido, "cod_cliente_loja"
                            ].iloc[0]
                            if not df_lojas.empty
                            else ""
                        )
                        conteudo_arquivo = formata_pedido_rp(
                            df_sub, cod_cliente, doc_padrao
                        )
                        formato_arquivo = ".apv"

                    st.download_button(
                        label=f":material/Download: Baixar Pedido {tipo}",
                        data=conteudo_arquivo,
                        file_name=f"{AGORA.strftime('%Y%m%d_%HH%MM')}_{loja_pedido}_{tipo}{formato_arquivo}",
                        mime="text/plain",
                        on_click="ignore",
                    )
                    salvar_pedido_banco_dados(
                        loja_pedido,
                        tipo,
                        conteudo_arquivo,
                        f_pedido if f_pedido else io.StringIO(texto_atacado),
                    )
                else:
                    st.info(f"Sem itens para {tipo}")

with st.sidebar:
    st.space()
    st.markdown("### Produtos Base")
    st.write(f"Produtos cadastrados na memória: :blue[{produtos_cadastrados}]")
    if link_produto:
        st.link_button("Acessar Arquivo Principal", link_produto)
    if link_produto_extra:
        st.link_button("Acessar Arquivo Extra", link_produto_extra)
