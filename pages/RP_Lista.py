import streamlit as st
import pandas as pd
import re
import io
import requests
from utils import carregar_dados_onedrive, converte_ultima_modificacao


# --- FUNÇÕES E DEFINIÇÕES
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


COLUNAS_PRODUTOS = [
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
COLUNAS_PRODUTOS_EXTRA = ["CodProduto", "Fam", "ListaCodCaract", "DescComplementar"]
GRUPO = ["SECO", "CONG", "REFR", "PESO"]
# FORNECEDORES = marcas = [
#     "ATALAIA",
#     "AYMORE",
#     "BELINHO",
#     "CIDINHA",
#     "DONDON",
#     "ELMA CHIPS",
#     "FINI",
#     "FRUTTBOM",
#     "FUGINI",
#     "HELLMANNS",
#     "ITAMBE",
#     "KIBON",
#     "LOBITS",
#     "MAMMA DALVA",
#     "MAMMAMIA",
#     "MARICOTA",
#     "MAVI",
#     "MINAS MAIS",
#     "NESTLE",
#     "NINHO",
#     "PALHA LEVE",
#     "PERDIGAO",
#     "PORTO ALEGRE",
#     "PULSI",
#     "RENATA",
#     "SADIA",
#     "SEARA",
#     "TREVO",
#     "UAI",
#     "UNIBABY",
#     "YPE",
# ]
link_produto = st.secrets["onedrive"]["links"]["produto"]
link_produto_extra = st.secrets["onedrive"]["links"]["produto_extra"]
desativa_manual = False
produtos_cadastrados = 0

# --- CONF PAGINA
st.set_page_config(page_title="Editor de Lista", layout="wide")

st.title(":material/Attach_File: Editor de :red[Lista]")

# --- LAYOUT PAGINA
bd_automatico = st.toggle("Deseja pegar arquivos automaticamente?", value=True)
if bd_automatico:
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
        ":material/Add: Arquivo 00001produtoextra.txt.txt",
        disabled=desativa_manual,
        type="txt",
    )


st.subheader(":material/Toggle_On: Excessões: O que retirar da lista")
c1, c2 = st.columns(2)
with c1:
    ind_neg = st.checkbox("[:material/Stat_Minus_1:]  Estoque Negativo", value=True)
    ind_div = st.checkbox("[:material/Safety_Divider:]  Divisão", value=True)
    ind_loja = st.checkbox("[:material/Shopping_Bag:]  Loja", value=True)
with c2:
    ind_grupo = st.pills(
        ":material/Group_Work: Grupo",
        options=GRUPO,
        selection_mode="multi",
        default=GRUPO,
    )
    ind_qtmin = st.number_input(
        ":material/Numbers: Estoque Mínimo",
        value=None,
        placeholder="Digite um valor",
        step=10,
    )

# --- PROCESSAMENTO

if (f_produto and f_extra) or desativa_manual:
    with st.status("Processando dados...", expanded=True) as status:
        #   1. Inicialização
        # Abre df
        if desativa_manual:
            df = abrir_arquivo_txt(f_produto_auto, COLUNAS_PRODUTOS)
            df_extra = abrir_arquivo_txt(f_extra_auto, COLUNAS_PRODUTOS_EXTRA)
        else:
            if f_produto.name != "00001produto.txt":
                st.error(":material/Close: 00001produto.txt erro ao carregar")
                st.stop()
            if f_extra.name != "00001produtoextra.txt":
                st.error(":material/Close: 00001produtoextra.txt erro ao carregar")
                st.stop()
            df = abrir_arquivo_txt(f_produto, COLUNAS_PRODUTOS)
            df_extra = abrir_arquivo_txt(f_extra, COLUNAS_PRODUTOS_EXTRA)

        produtos_cadastrados = len(df)
        # Merge Produto + Extra
        df = df.merge(
            df_extra[["CodProduto", "ListaCodCaract"]], on="CodProduto", how="left"
        )

        df = df[
            ["CodProduto", "CodGrupo", "Descricao", "Estoq", "Fam", "ListaCodCaract"]
        ]

        # Cria coluna de fornecedores
        df["Fornecedor"] = df["Descricao"].str.split().str[-3]

        # Cria nova coluna de tipo
        if False:
            df["TIPO"] = "SECO"
            df.loc[df["CodGrupo"].isin([9, 14]), "TIPO"] = "CONG"
            df.loc[df["ListaCodCaract"].astype(str).str.contains("000002"), "TIPO"] = (
                "PESO"
            )

        df["FAMILIA"] = "-"
        df.loc[df["Fam"] == 900000007, "FAMILIA"] = "LISTA"
        df.loc[df["Fam"] == 900000008, "FAMILIA"] = "DIVISAO"
        df.loc[df["Fam"] == 900000009, "FAMILIA"] = "LOJA"

        df["TIPO"] = "SECO"
        df.loc[df["CodGrupo"].isin([9]), "TIPO"] = "CONG"
        df.loc[df["CodGrupo"].isin([14]), "TIPO"] = "REFR"
        df.loc[df["ListaCodCaract"].astype(str).str.contains("000002"), "TIPO"] = "PESO"

        #   2. FILTRO DATAFRAME
        # filtro negativo
        if ind_neg:
            df = df[df["Estoq"] > 0].copy()
        # filtro divisão
        if ind_div:
            df = df[df["Fam"] != 900000008].copy()
        # filtro grupo
        df = df[df["TIPO"].isin(ind_grupo)].copy()
        # filtro qt mínima estoque
        if ind_qtmin:
            df = df[df["Estoq"] > ind_qtmin]

        #   --- MOSTRAR INFORMAÇÕES
        if df.empty:
            st.error(":material/Cancel: Nenhum item selecionado")
            status.update(label="Processamento concluído!", state="complete")
            st.stop()

        st.write(
            f":material/Delete: Selecione os produtos que deseja remover da lista original: :red[{len(df)} itens]"
        )

        remover_linhas = st.dataframe(
            df[["CodProduto", "Descricao", "Fornecedor", "TIPO", "FAMILIA", "Estoq"]],
            hide_index=True,
            selection_mode="multi-row",
            on_select="rerun",
        )

        # Pega o dict e remove as linhas selecionadas
        ind_remover_linhas = remover_linhas["selection"]["rows"]
        df_removido = df.drop(df.index[ind_remover_linhas]).copy()

        df_removido = df_removido[
            ["CodProduto", "Descricao", "Fornecedor", "TIPO", "FAMILIA", "Estoq"]
        ]
        df_removido = df_removido.sort_values(by=["Fornecedor"])

        if not df_removido.empty and len(df_removido) == len(df):
            st.write(
                f":material/List: Total Itens na lista: :red[{len(df_removido)} itens]"
            )
        else:
            st.write(
                f":material/List: Total Itens na lista: :blue[{len(df_removido)} itens]"
            )

        status.update(label="Processamento concluído!", state="complete")

    coluna1, coluna2, coluna3, coluna4 = st.columns(4)
    tipos = [("SECO", coluna1), ("CONG", coluna2), ("REFR", coluna3), ("PESO", coluna4)]

    for tipo, col in tipos:
        # Filtrar o DF pelo tipo
        df_filtrado = df_removido[df_removido["TIPO"] == tipo]

        # Só exibe se houver dados para aquele tipo
        with col:
            if not df_filtrado.empty:
                with st.expander(
                    f":material/Copy_All: {len(df_filtrado)} itens: {tipo}",
                    expanded=True,
                ):

                    # Criar a string formatada (um item por linha)
                    if tipo == "CONG":
                        dfList = df_filtrado["Descricao"].astype(str).tolist()
                        dfList.insert(0, "CONGELADO")
                        texto_formatado = "\n".join(dfList)
                    elif tipo == "REFR":
                        dfList = df_filtrado["Descricao"].astype(str).tolist()
                        dfList.insert(0, "REFRIGERADO")
                        texto_formatado = "\n".join(dfList)
                    elif tipo == "SECO":
                        dfList = df_filtrado["Descricao"].astype(str).tolist()
                        dfList.insert(0, "SECO")
                        texto_formatado = "\n".join(dfList)
                    else:
                        dfList = df_filtrado["Descricao"].astype(str).tolist()
                        dfList.insert(0, "PESÁVEIS")
                        texto_formatado = "\n".join(dfList)

                    # texto_formatado = "\n".join(df_filtrado["Descricao"].astype(str).tolist())
                    # O usuário clica no ícone que aparece no canto superior direito do quadro
                    st.code(texto_formatado, language=None)
                    st.caption(
                        f"Clique no ícone no canto superior direito do quadro acima para copiar os itens de {tipo}."
                    )
            else:
                st.info(f":material/Cancel: {tipo} Sem itens")

else:
    st.info(
        "Insira _'00001produto.txt'_ e _'00001produtoextra.txt'_ para começar a edição"
    )

#   --- SIDEBAR
with st.sidebar:
    with st.expander("Link para arquivo .txt"):
        st.subheader("Link para produto.txt:")
        st.link_button("Clique aqui", link_produto)

        st.subheader("Link para produtoextra.txt:")
        st.link_button("Clique aqui", link_produto_extra)
    st.write(f"Produtos cadastrados: :blue[{produtos_cadastrados}]")
