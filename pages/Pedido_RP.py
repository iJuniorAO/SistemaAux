import streamlit as st
import requests
import pandas as pd
import numpy as np
import io
import re
from rapidfuzz import process, fuzz
from datetime import datetime, time, timedelta, timezone
from supabase import create_client, Client
from utils import carregar_dados_onedrive, converte_ultima_modificacao

#   MELHORIAS
#
#    LISTA
#       Mudar index e corrigir para ser igual arquivo txt
#       desativa_manual transformar em função


# --- FUNÇÕES DE PROCESSAMENTO (Adaptadas do seu arquivo original) ---
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
    # Lê as linhas do arquivo
    conteudo = uploaded_file.read().decode("utf-8")
    linhas = conteudo.splitlines()

    linhas_novas = []
    alteracoes_feitas = 0
    erros_nao_corrigidos = []
    linhas_removidas = 0

    # Processamento
    for i, linha in enumerate(linhas):
        num_l = i + 1

        if linha.strip() == "":
            linhas_removidas += 1
            continue

        # Retira espaços em branco extra
        if linha.strip() != linha:
            linha = linha.strip()

        # Tenta corrigir se o código (1ª coluna) não for número
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

    # Prepara o df separando a primeira coluna
    df_Import_loja[colunas_Pedidos] = (
        df_Import_loja[0].astype(str).str.split(" ", n=2, expand=True)
    )
    df_Import_loja = df_Import_loja.drop(
        columns=[0]
    )  # Removido 'Sigla' do drop pois ela é criada no split

    # Separa erros de quantidade
    num = pd.to_numeric(df_Import_loja["QtCx"], errors="coerce")
    df_ok = df_Import_loja[num.notna()].copy()
    df_erro = df_Import_loja[num.isna()].copy()
    df_ok["QtCx"] = df_ok["QtCx"].astype(float)

    return df_ok, df_erro, Linhas_Pedidos


def encontra_melhor_match(descricao_erro, escolhas_base, threshold=60):

    # extractOne retorna (string_encontrada, score, index)
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
        resposta = supabase.table("Lojas").select("Filial").order("Filial").execute()
        return [loja["Filial"] for loja in resposta.data]
    except Exception as e:
        print(f"Erro ao buscar lojas: {e}")
        return []


def confere_prazo_pedido():
    for descricao, horario_limite, cor, icone, msg in REGRAS_PRAZO:
        if AGORA.time() >= horario_limite:
            st.markdown(f"### :{cor}[:material/{icone}:] {msg}")
            return
    st.markdown("### :green[:material/Clock_Loader_10:] Dentro do prazo para Pedidos")


def processar_pedidos(df, df_extra, df_Pedido_Loja):
    df = df[(df["Fam"] != 900000008) & (df["Estoq"] > 0)]
    df = df[["CodProduto", "CodGrupo", "Descricao", "Estoq", "Fam"]]

    df = df.merge(
        df_extra[["CodProduto", "ListaCodCaract"]], on="CodProduto", how="left"
    )

    CONDICOES = [
        df["ListaCodCaract"].astype(str).str.contains("000002", na=False),
        df["CodGrupo"].isin([9, 14]),
    ]
    df["TIPO"] = np.select(CONDICOES, ["PESO", "CONG"], default="SECO")

    # ultimo = df["Descricao"].astype(str).str.split().str[-1]
    # df["CONV"] = np.where(ultimo.str.isdigit(), ultimo, 1).astype(float)
    df["Codigo"] = df["CodProduto"].astype(str).str.rjust(13)

    # df_base = df[["Codigo", "Descricao", "TIPO", "CONV"]].copy()
    df_base = df[["Codigo", "Descricao", "TIPO"]].copy()

    df_Pedido_Final = df_base.merge(
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

    ultimo = df_Pedido_Final["Descricao"].astype(str).str.split().str[-1]
    ultimo_numerico = pd.to_numeric(ultimo, errors="coerce")
    df_Pedido_Final["CONV"] = ultimo_numerico.fillna(1).astype(float)

    df_Pedido_Final["TOTAL"] = df_Pedido_Final["QtCx"] * df_Pedido_Final["CONV"]

    df_Pedido_Final["VALOR_STR"] = df_Pedido_Final["TOTAL"].apply(
        lambda x: f"{x:09.3f}".replace(".", ",")
    )

    return df_Pedido_Final, df_Erro_Desc, df_base


def salvar_pedido_banco_dados(loja, tipo, pedido_erp, pedido_original, obs=None):
    if loja != "ATACADO":
        try:
            dados = {
                "data_pedido": AGORA.strftime("%Y-%m-%d"),
                "hora_pedido": AGORA.strftime("%H:%M"),
                "loja": loja,
                "tipo_pedido": tipo,
                "pedido_erp": pedido_erp.getvalue(),
                "pedido_original": pedido_original.getvalue(),
                "obs": obs,
            }
            supabase.table("PedidosLojas").insert(dados).execute()
            return st.success(
                f":material/Check: Pedido {loja} {tipo} salvo no Banco de Dados!"
            )

        except Exception as e:
            return st.error(
                f":material/Close: ERRO - Não foi possível salvar no Banco de Dados {e}"
            )
    else:
        return st.info("Pedidos Atacado não são Salvo no Banco de Dados")


AGORA = datetime.now()
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
Linhas_Pedidos = 0
link_produto = st.secrets["onedrive"]["links"]["produto"]
link_produto_extra = st.secrets["onedrive"]["links"]["produto_extra"]
desativa_manual = False
produtos_cadastrados = 0
LOJAS = [
    "Abilio Machado",
    "Brigadeiro",
    "Cabana",
    "Cabral",
    "Caete",
    "Centro Betim",
    "Eldorado",
    "Goiania",
    "Jardim Alterosa",
    "Lagoa Santa",
    "Laguna",
    "Laranjeiras",
    "Neves",
    "Nova Contagem",
    "Novo Progresso",
    "Palmital",
    "Para de Minas",
    "Pindorama",
    "Santa Cruz",
    "Santa Helena",
    "Serrano",
    "Silva Lobo",
    "São Luiz",
    "Venda Nova",
    "TESTE",
]

# --- CONFIGURAÇÃO DA PÁGINA ---
st.set_page_config(page_title="Conversor de Pedidos", layout="wide")

if st.session_state.get("debugger"):
    st.error(":material/Terminal: APP EM TESTE")

# Inicialização do BD
url = st.secrets["connections"]["supabase"]["url"]
key = st.secrets["connections"]["supabase"]["key"]
supabase: Client = create_client(url, key)

# --- INTERFACE STREAMLIT ---
st.title(":material/Folder_Check_2: Conversor de Pedidos para Importação")

confere_prazo_pedido()
st.space()

# Tabs para base de dados e importação pedidos
tab1, tab2, tab3 = st.tabs(
    [
        ":material/Database: Base de Dados",
        ":material/Database_Upload: Pedidos Lojas",
        ":material/Database_Upload: Pedido Atacado",
    ]
)
with tab1:
    st.header("Upload de Bases de Dados")
    bd_automatico = st.toggle("Deseja pegar arquivos automaticamente?", value=True)
    if bd_automatico:
        LOJAS = carregar_lojas_banco_dados()
        desativa_manual = True

        if "dados_onedrive" not in st.session_state:
            st.session_state.dados_onedrive = carregar_dados_onedrive(link_produto)
        if "dados_onedrive_extra" not in st.session_state:
            st.session_state.dados_onedrive_extra = carregar_dados_onedrive(
                link_produto_extra
            )

        response = st.session_state.dados_onedrive
        response_extra = st.session_state.dados_onedrive_extra

        if response["falha"]:
            st.error("Não foi possível pegar produto.txt automaticamente")
        if response_extra["falha"]:
            st.error("Não foi possível pegar produto_extra.txt automaticamente")

        if response["data"]:
            ultima_modificacao_dt = converte_ultima_modificacao(response["data"])

            st.write(
                f"Ultima modificação: :red[{ultima_modificacao_dt.strftime("%H:%M:%S")}]  | :red[{ultima_modificacao_dt.strftime("%d/%m/%Y")}]"
            )

        f_produto_auto = response["resp"]
        f_extra_auto = response_extra["resp"]

    col1, col2 = st.columns(2)
    with col1:
        f_produto = st.file_uploader(
            ":material/Barcode: Arquivo 00001produto.txt",
            disabled=desativa_manual,
            type="txt",
        )
    with col2:
        f_extra = st.file_uploader(
            ":material/Add: Arquivo 00001produtoextra.txt",
            disabled=desativa_manual,
            type="txt",
        )
with tab2:
    st.header("Upload de Pedidos da Loja")
    f_pedido = st.file_uploader(":material/Article: Pedido Loja.txt", type="txt")
with tab3:
    st.header("Upload de Pedidos do Atacado")
    f_pedido_atacado = st.file_uploader(
        ":material/Article: Pedido Atacado.xlsx", type="xlsx"
    )

loja_pedido = st.selectbox(
    ":red[Seleciona Loja]",
    LOJAS,
    index=None,
    placeholder="Seleciona a loja que realizou o pedido",
)
st.space()


if ((f_produto and f_extra) or desativa_manual) and f_pedido or f_pedido_atacado:
    if f_pedido and f_pedido_atacado:
        st.error("Inserido Pedido Loja e Pedido Atacado - Informar somente 1")
        st.stop()
    if not loja_pedido:
        st.error(":material/Priority_High: Selecione uma Loja")
        st.stop()
    # --- PROCESSAMENTO ---
    if desativa_manual:
        df = abrir_arquivo_txt(f_produto_auto, colunas_produto)
        df_extra = abrir_arquivo_txt(f_extra_auto, colunas_produto_extra)
    else:
        if f_produto.name != "00001produto.txt":
            st.error(":material/Close: 00001produto.txt erro ao carregar")
            st.stop()
        if f_extra.name != "00001produtoextra.txt":
            st.error(":material/Close: 00001produtoextra.txt erro ao carregar")
            st.stop()
        df = abrir_arquivo_txt(f_produto, colunas_produto)
        df_extra = abrir_arquivo_txt(f_extra, colunas_produto_extra)

    # Importa Pedido da Loja
    if f_pedido:
        f_pedido = limpa_texto(f_pedido)
        df_Pedido_Loja, df_Erro_Qt, Linhas_Pedidos = trata_pedido_loja(
            abrir_arquivo_txt(f_pedido), colunas_Pedidos
        )
    else:
        df_pedido_atacado = pd.read_excel(f_pedido_atacado, engine="openpyxl")
        df_pedido_atacado = df_pedido_atacado[
            ["CodProduto", "Descricao", "R$/Un", "QUANTIDADE CX"]
        ]
        df_pedido_atacado = df_pedido_atacado.dropna(subset={"QUANTIDADE CX"})
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
            linhas_com_erro

        df_pedido_atacado["Qt Solicitada"] = (
            df_pedido_atacado["QUANTIDADE CX"].astype(int).astype(str)
            + " cx "
            + df_pedido_atacado["Descricao"]
        )
        f_pedido_atacado = "\n".join(df_pedido_atacado["Qt Solicitada"])
        f_pedido_atacado = io.StringIO(f_pedido_atacado)

        df_Pedido_Loja, df_Erro_Qt, Linhas_Pedidos = trata_pedido_loja(
            abrir_arquivo_txt(f_pedido_atacado), colunas_Pedidos
        )
    produtos_cadastrados = len(df)

    df_Pedido_Final, df_Erro_Desc, df_Produto_Base = processar_pedidos(
        df, df_extra, df_Pedido_Loja
    )

    st.write(f"Foram importados: {Linhas_Pedidos} linhas")

    # --- EXIBIÇÃO DE ERROS ---
    if not df_Erro_Qt.empty or not df_Erro_Desc.empty:
        aplicar_correcao = False
        with st.expander(
            ":orange[:material/Warning:] Ver Erros de Importação", expanded=True
        ):
            if not df_Erro_Qt.empty:
                st.warning(f"[{len(df_Erro_Qt)}] Linhas com erro na quantidade:")
                st.dataframe(df_Erro_Qt)
            if not df_Erro_Desc.empty:
                st.error(
                    f"[{len(df_Erro_Desc)}] Itens não encontrados na base de produtos:"
                )

                lista_base = df_Produto_Base["Descricao"].tolist()
                matches = df_Erro_Desc["Descricao"].apply(
                    lambda x: encontra_melhor_match(x, lista_base)
                )
                df_validacao = pd.concat([df_Erro_Desc, matches], axis=1).sort_values(
                    by="Score_Similaridade", ascending=False
                )

                st.write(
                    f"Encontrados Automaticamente: {df_validacao["Descricao_Sugerida"].notna().sum()}/{df_validacao["Descricao"].notna().sum()} itens"
                )
                st.write("Selecione as alterações corretas:")

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
                        df, df_extra, df_Pedido_Corrigido
                    )
    else:
        st.success("Sem erro de exportação")
        st.toast("Todos itens importados", icon="✅")
        aplicar_correcao = False

    # --- DOWNLOADS ---
    Linhas_Pedidos_por_Tipo = df_Pedido_Final["TIPO"].value_counts().to_dict()

    if not Linhas_Pedidos_por_Tipo:
        st.error("ERRO NA IMPORTAÇÃO - Arquivo fora do padrão")
        st.stop()
    else:
        st.divider()
        if aplicar_correcao:
            st.header(
                f":blue[{loja_pedido}] - Baixar Pedidos Gerados - :red[Correção Automática]"
            )
        else:
            st.header(f":blue[{loja_pedido}] - Baixar Pedidos Gerados")

        c1, c2, c3 = st.columns(3)
        tipos = [("SECO", c1), ("CONG", c2), ("PESO", c3)]
        for tipo, col in tipos:
            df_sub = df_Pedido_Final[df_Pedido_Final["TIPO"] == tipo][
                ["Codigo", "VALOR_STR"]
            ]
            with col:
                if not df_sub.empty:
                    st.success(f"[{len(df_sub)}] Pedido {tipo} pronto!")
                    # Gera o CSV em memória para download
                    output = io.StringIO()
                    df_sub.to_csv(output, sep="\t", index=False, header=False)

                    st.download_button(
                        label=f":material/Download: Baixar Pedido {tipo}",
                        data=output.getvalue(),
                        file_name=f"{AGORA.strftime("%Y%m%d_%HH%MM")}_{loja_pedido}_{tipo}.txt",
                        mime="text/plain",
                        on_click="ignore",
                    )
                    salvar_pedido_banco_dados(loja_pedido, tipo, output, f_pedido)
                else:
                    st.info(f"Sem itens para {tipo}")

# todos arquivos bd enviados menos o pedido
elif f_produto and f_extra and not f_pedido:
    # Validações
    if f_produto.name != "00001produto.txt":
        st.error(
            ":material/Close: 00001produto.txt erro ao carregar - Verifique se o arquivo é '0001produto.txt'"
        )
    if f_extra.name != "00001produtoextra.txt":
        st.error(
            ":material/Close: 00001produtoextra.txt erro ao carregar - Verifique se o arquivo é '0001produtoextra.txt'"
        )
    if f_produto.name == "00001produto.txt" and f_extra.name == "00001produtoextra.txt":
        st.info(":material/Check: Arquivos iniciais OK. Aguardando upload do pedido.")
else:
    st.info(":material/Warning: Aguardando o upload do arquivos iniciais para iniciar.")

with st.sidebar:
    st.write(f"Produtos cadastrados: :blue[{produtos_cadastrados}]")
    with st.expander("Link para arquivo .txt"):
        st.subheader("Link para produto.txt:")
        st.link_button("Clique aqui", link_produto)

        st.subheader("Link para produtoextra.txt:")
        st.link_button("Clique aqui", link_produto_extra)
