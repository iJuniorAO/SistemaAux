import streamlit as st
import pandas as pd
import numpy as np
import re
import io
import zipfile
from datetime import datetime
from bancoDados import inicia_conexao_bancoDados, obter_lojas
from utils import (
    carregar_dados_onedrive,
    abrir_arquivo_txt,
    validar_acesso,
    converte_ultima_modificacao,
)

if "perfil" not in st.session_state:
    st.session_state.perfil = "none"

validar_acesso(["administrador", "usuario"])

# --- CONSTANTES DE TEMPO (para formato RPOne) ---
AGORA = datetime.now()
DDMMAA = AGORA.strftime("%d%m%y")
AAAAMMDD = AGORA.strftime("%y%m%d%H%M")[:11]


# ==============================================================================
# FUNÇÕES DE NEGÓCIO
# ==============================================================================


def trata_df(
    resposta, df_produtos
):  # irá mesclear a resposta da funçaõ distribuir_estoque com as demais descrições

    df_lista = []
    for filial, dados in resposta.items():
        temp_df = dados.copy()
        temp_df["filial"] = filial
        df_lista.append(temp_df)

    df_completo = pd.concat(df_lista, ignore_index=True)

    df_pivot = df_completo.pivot(index="CodProduto", columns="filial", values="Qt Cx")
    df_pivot["Total Distribuído"] = df_pivot.sum(axis=1)

    df_pivot = df_pivot.reset_index()
    df_produtos = df_produtos[
        ["CodProduto", "Descricao", "TIPO", "Estoq", "Fornecedor"]
    ]

    df_merge = df_produtos.merge(df_pivot, on="CodProduto", how="inner")

    return df_merge


def distribuir_estoque_df(df_divisao, df_loja):
    df_loja = df_loja.copy().reset_index(drop=True)
    df_loja["Loja"] = df_loja["filial"] + "_" + df_loja["cod_empresa"]
    df_loja["fator"] = df_loja["fator_porcentagem"] / 100
    df_loja["store_order"] = df_loja.index

    df_final = (
        df_divisao[["CodProduto", "Qt Cx"]]
        .merge(df_loja[["store_order", "Loja", "fator"]], how="cross")
        .sort_values(["CodProduto", "store_order"])
    )
    df_final["valor_ideal"] = df_final["Qt Cx"] * df_final["fator"]
    df_final["cumsum_ideal"] = df_final.groupby("CodProduto")["valor_ideal"].cumsum()
    df_final["cumsum_rounded"] = df_final.groupby("CodProduto")[
        "cumsum_ideal"
    ].transform(lambda x: x.round())
    df_final["Qt Cx"] = (
        df_final["cumsum_rounded"]
        - df_final.groupby("CodProduto")["cumsum_rounded"].shift(fill_value=0)
    ).astype(int)
    df_final = df_final[["CodProduto", "Loja", "Qt Cx"]]

    df_pivoted = df_final.pivot(index="CodProduto", columns="Loja", values="Qt Cx")

    df_pivoted["Total Distribuído"] = df_pivoted.sum(axis=1)

    df_pivoted.columns.name = None
    df_pivoted = df_divisao[
        ["CodProduto", "Descricao", "TIPO", "Fator Conversao"]
    ].merge(df_pivoted, on="CodProduto")

    return df_pivoted


# ==============================================================================
# FUNÇÕES DE EXPORTAÇÃO — ALTERDATA
# ==============================================================================


def extrai_qt_TXT_alterdata(df):
    """Gera dicionário {loja: DataFrame(Codigo, Valor)} no formato AlterData."""
    colunas_fixas = [
        "cod_empresa",
        "CodProduto",
        "Fator Conversao",
        "Total Distribuído",
    ]
    df["CodProduto"] = df["CodProduto"].astype(str).str.rjust(13)

    colunas_qt = [c for c in df.columns if c not in colunas_fixas]
    saida = {}

    for col in colunas_qt:

        if df[col].sum() == 0:
            continue

        nome_qt_txt = f"Qt_TXT_{col}"
        qt_convertida = df[col] * df["Fator Conversao"]

        df[nome_qt_txt] = qt_convertida.apply(lambda x: f"{x:09.3f}".replace(".", ","))

        saida[col] = df[["CodProduto", nome_qt_txt]].rename(
            columns={"CodProduto": "Codigo", nome_qt_txt: "Valor"}
        )

    return saida


def criar_downloads_alterdata(df_txt_dict, categoria):
    """Cria botões de download no formato AlterData (.txt tab-separated)."""
    if not df_txt_dict:
        return st.info(f"Nenhum produto {categoria}")

    st.markdown(f"### :blue[{categoria}]", text_alignment="center")
    for loja, df_loja in df_txt_dict.items():
        output = io.StringIO()
        df_loja.to_csv(output, sep="\t", index=False, header=False)
        loja_nome = loja.split("_")[0]
        col1, col2 = st.columns(2, vertical_alignment="center")
        col1.markdown(loja_nome)
        col2.download_button(
            label=f":material/Download: Baixar",
            data=output.getvalue(),
            file_name=f"DIVISAO_{loja}_{categoria}.txt",
            mime="text/plain",
            key=f"alt_{categoria}_{loja}",
            on_click="ignore",
        )


# ==============================================================================
# FUNÇÕES DE EXPORTAÇÃO — RP ONE
# ==============================================================================


def abrir_arquivo_txt_rp(arquivo, colunas=None, separador=";", eng="python"):
    """Lê arquivo TXT com separador customizável (padrão ';' para RPOne)."""
    try:
        if isinstance(arquivo, str):
            arquivo = io.StringIO(arquivo)
        return pd.read_csv(
            arquivo,
            sep=separador,
            header=None,
            names=colunas,
            encoding="latin1",
            engine=eng,
        )
    except Exception as e:
        st.error(f"Erro ao ler arquivo RP: {e}")
        st.stop()


def formata_pedido_rp(df_sub, cod_cliente, doc_pad, tipo):
    """Formata linhas no padrão PV^...  do RP One (.apv)."""
    cod_tipo = {"SECO": "1", "CONG": "2", "PESO": "3"}

    df_sub = df_sub[["CodProduto", "VALOR_STR", "CONV", "PrecoUnPd"]].copy()
    df_sub["CodProduto"] = df_sub["CodProduto"].astype(np.int64).astype(str)
    df_sub = df_sub.fillna("")

    prefixo = f"PV^{DDMMAA}^{doc_pad}^{AAAAMMDD}{cod_tipo.get(tipo, 0)}{cod_cliente}^{cod_cliente}^"
    sufixo = "^^0^512^006^^^V^^0.000^"

    linhas_formatadas = [
        f"{prefixo}{'^'.join(row.astype(str))}{sufixo}" for _, row in df_sub.iterrows()
    ]
    return "\n".join(linhas_formatadas)


def extrai_qt_RPOne(df, df_produto_base):
    """
    Gera dicionário {loja: DataFrame(CodProduto, VALOR_STR, CONV, PrecoUnPd)}
    para exportação no formato RP One.
    """
    colunas_fixas = [
        "cod_empresa",
        "CodProduto",
        "Fator Conversao",
        "Total Distribuído",
    ]
    colunas_qt = [c for c in df.columns if c not in colunas_fixas]
    saida = {}

    # Busca SiglaUn e PrecoUnPd da base de produtos
    df = df.merge(
        df_produto_base[["CodProduto", "SiglaUn", "PrecoUnPd"]],
        on="CodProduto",
        how="left",
    )

    for col in colunas_qt:

        if df[col].sum() == 0:
            continue

        df_loja = df[
            ["CodProduto", col, "SiglaUn", "PrecoUnPd", "Fator Conversao"]
        ].copy()

        # QtCx = quantidade distribuída por loja
        df_loja["QtCx"] = df_loja[col]

        # CONV = SiglaUn (fator de conversão unitário do RPOne)
        df_loja["CONV"] = df_loja["SiglaUn"]

        # PrecoUnPd = PrecoUnPd * QtCx * CONV (preço total)
        df_loja["PrecoUnPd"] = df_loja["PrecoUnPd"] * df_loja["QtCx"] * df_loja["CONV"]
        df_loja["PrecoUnPd"] = df_loja["PrecoUnPd"].apply(lambda x: f"{x:03.3f}")

        # TOTAL = QtCx (no RP One, quantidade = caixas sem multiplicar por fator)
        df_loja["VALOR_STR"] = df_loja["QtCx"].apply(lambda x: f"{x:03.3f}")

        saida[col] = df_loja[["CodProduto", "VALOR_STR", "CONV", "PrecoUnPd"]]

    return saida


def criar_downloads_rpone(df_txt_dict, categoria, cod_cliente_map, doc_padrao):
    """Cria botões de download no formato RP One (.apv) com opção de baixar todos em um arquivo .zip."""
    if not df_txt_dict:
        return st.info(f"Nenhum produto {categoria}")

    st.markdown(f"### :blue[{categoria}]", text_alignment="center")

    arquivos_gerados = []
    buffer_zip = io.BytesIO()

    # 1. Pré-processa os arquivos e monta o arquivo .ZIP em memória
    with zipfile.ZipFile(buffer_zip, "w", zipfile.ZIP_DEFLATED) as zf:
        for loja, df_loja in df_txt_dict.items():
            loja_nome = loja.split("_")[0]
            cod_cliente = cod_cliente_map.get(loja_nome, "")

            conteudo_arquivo = formata_pedido_rp(
                df_loja, cod_cliente, doc_padrao, categoria
            )

            nome_arquivo = (
                f"DIVISAO_{AGORA.strftime('%Y%m%d_%HH%MM')}_{loja}_{categoria}.apv"
            )

            # Escreve o arquivo no pacote ZIP
            zf.writestr(nome_arquivo, conteudo_arquivo)

            # Guarda os dados necessários para os botões individuais
            arquivos_gerados.append(
                {
                    "loja_nome": loja_nome,
                    "nome_arquivo": nome_arquivo,
                    "conteudo": conteudo_arquivo,
                    "loja_key": loja,
                }
            )

    buffer_zip.seek(0)

    # 2. Botão principal: Baixar tudo em um único arquivo .zip
    st.download_button(
        label=":material/folder_zip: Baixar Todos os Arquivos (.zip)",
        data=buffer_zip,
        file_name=f"TODOS_PEDIDOS_{AGORA.strftime('%Y%m%d_%HH%MM')}_{categoria}.zip",
        mime="application/zip",
        key=f"zip_{categoria}",
        on_click="ignore",
        use_container_width=True,
    )

    st.divider()

    # 3. Botões individuais (item a item)
    for item in arquivos_gerados:
        col1, col2 = st.columns(2, vertical_alignment="center")
        col1.markdown(item["loja_nome"])
        col2.download_button(
            label=":material/Download: Baixar",
            data=item["conteudo"],
            file_name=item["nome_arquivo"],
            mime="text/plain",
            key=f"rp_{categoria}_{item['loja_key']}",
            on_click="ignore",
        )


# ==============================================================================
# INICIALIZAÇÃO: BANCO DE DADOS E CONFIGURAÇÃO
# ==============================================================================

supabase = inicia_conexao_bancoDados()
todas_lojas = obter_lojas(supabase)

if not todas_lojas["status"]:
    st.markdown("# :material/Close: Nâo é possível acessar as lojas")
    st.error("Contacte suporte técnico")
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
COLUNAS_PRODUTOS_RP = [
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
    "ListaCodCaract",
]
COLUNAS_PRODUTOS_EXTRA = ["CodProduto", "Fam", "ListaCodCaract", "DescComplementar"]
GRUPO = ["SECO", "CONG", "REFR", "PESO"]
FORNECEDORES = marcas = [
    "ATALAIA",
    "AYMORE",
    "BELINHO",
    "CIDINHA",
    "DONDON",
    "ELMA CHIPS",
    "FINI",
    "FRUTTBOM",
    "FUGINI",
    "HELLMANNS",
    "ITAMBE",
    "KIBON",
    "LOBITS",
    "MAMMA DALVA",
    "MAMMAMIA",
    "MARICOTA",
    "MAVI",
    "MINAS MAIS",
    "NESTLE",
    "NINHO",
    "PALHA LEVE",
    "PERDIGAO",
    "PORTO ALEGRE",
    "PULSI",
    "RENATA",
    "SADIA",
    "SEARA",
    "TREVO",
    "UAI",
    "UNIBABY",
    "YPE",
]

desativa_manual = False
produtos_cadastrados = 0

# --- CONF PAGINA
st.set_page_config(page_title="Fazer Pedidos", layout="wide")

st.title(":material/Universal_Currency_Alt: LANÇA :blue[DIVISÃO]")

# ==============================================================================
# SELETOR DE SISTEMA (FLAG PRINCIPAL)
# ==============================================================================

with st.sidebar:
    st.markdown("## Configurações")
    sistema = st.pills(
        "Selecione o ERP de Destino:", ["AlterData", "RPOne"], default="RPOne"
    )

    if sistema == "RPOne":
        doc_padrao = st.text_input("Documento Padrão", value="6101")
        link_produto = st.secrets["onedrive"]["links"]["produto_rp_txt"]
        link_produto_extra = None
    else:
        link_produto = st.secrets["onedrive"]["links"]["produto"]
        link_produto_extra = st.secrets["onedrive"]["links"]["produto_extra"]

if not sistema:
    st.error("Selecione o ERP de Destino (barra lateral)")
    st.stop()

# --- LAYOUT PAGINA
bd_automatico = st.toggle("Deseja pegar arquivos automaticamente?", value=True)
if bd_automatico:
    desativa_manual = True

    # ===================== CARGA AUTOMÁTICA CONDICIONAL =====================
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
            st.error("Não foi possível pegar produto.txt automaticamente")
        if response_extra["falha"]:
            st.error("Não foi possível pegar produto_extra.txt automaticamente")

        if response["data"]:
            ultima_modificacao_dt = converte_ultima_modificacao(response["data"])
            st.write(
                f"Ultima modificação: :red[{ultima_modificacao_dt.strftime('%H:%M:%S')}]  | :red[{ultima_modificacao_dt.strftime('%d/%m/%Y')}]"
            )

        f_produto_auto = response["resp"]
        f_extra_auto = response_extra["resp"]

    elif sistema == "RPOne":
        if "dados_onedrive_rp_div" not in st.session_state:
            st.session_state.dados_onedrive_rp_div = carregar_dados_onedrive(
                link_produto
            )

        response = st.session_state.dados_onedrive_rp_div

        if response["falha"]:
            st.error("Não foi possível pegar arquivo de produtos RP automaticamente")

        if response["data"]:
            ultima_modificacao_dt = converte_ultima_modificacao(response["data"])
            st.write(
                f"Ultima modificação: :red[{ultima_modificacao_dt.strftime('%H:%M:%S')}]  | :red[{ultima_modificacao_dt.strftime('%d/%m/%Y')}]"
            )

        f_produto_auto = response["resp"]
        f_extra_auto = None  # RPOne não usa arquivo extra


# --- UPLOAD MANUAL
if sistema == "AlterData":
    col1, col2, col3 = st.columns(3)
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
    with col3:
        f_cod_filtro = st.file_uploader(
            ":material/Add: Arquivo TXT para :blue[FILTRO]", type="txt"
        )

elif sistema == "RPOne":
    col1, col2 = st.columns(2)
    with col1:
        f_produto = st.file_uploader(
            ":material/Barcode: Arquivo Produtos RP (.txt)",
            disabled=desativa_manual,
            type="txt",
        )
        f_extra = None
    with col2:
        f_cod_filtro = st.file_uploader(
            ":material/Add: Arquivo TXT para :blue[FILTRO]", type="txt"
        )

if f_cod_filtro:
    st.info("Filtro Ativado")


st.markdown("### :material/Toggle_On: Filtro:")
ignora_negativo = st.checkbox(":material/Package: Estoque Negativo", value=True)
ind_grupo = st.pills(
    ":material/Group_Work: Grupo", options=GRUPO, selection_mode="multi", default=GRUPO
)
st.divider()

# ==============================================================================
# PROCESSAMENTO PRINCIPAL
# ==============================================================================

pode_processar = (
    (f_produto and f_extra) or desativa_manual
    if sistema == "AlterData"
    else (f_produto is not None or desativa_manual)
)

if pode_processar:

    # ===================== LEITURA DA BASE DE PRODUTOS =====================
    if sistema == "AlterData":
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

    elif sistema == "RPOne":
        if desativa_manual:
            df = abrir_arquivo_txt_rp(
                f_produto_auto, COLUNAS_PRODUTOS_RP, ";", "python"
            )
        else:
            df = abrir_arquivo_txt_rp(f_produto, COLUNAS_PRODUTOS_RP, ";", "python")
        df_extra = None

    # Guarda base original (antes de filtros) para referência RPOne
    df_produto_base = df.copy()

    # ===================== FILTRO DE CÓDIGO (OPCIONAL) =====================
    if f_cod_filtro:
        conteudo = f_cod_filtro.read().decode("utf-8").split()
        df = df[df["CodProduto"].isin(conteudo)]

    produtos_cadastrados = len(df)

    # ===================== MERGE E CLASSIFICAÇÃO (CONDICIONAL) =====================
    if sistema == "AlterData":
        df = df.merge(
            df_extra[["CodProduto", "ListaCodCaract"]], on="CodProduto", how="left"
        )
        df = df[
            ["CodProduto", "CodGrupo", "Descricao", "Estoq", "Fam", "ListaCodCaract"]
        ]

        # Classificação AlterData: CodGrupo numérico
        df["TIPO"] = "SECO"
        df.loc[df["CodGrupo"].isin([9]), "TIPO"] = "CONG"
        df.loc[df["CodGrupo"].isin([14]), "TIPO"] = "REFR"
        df.loc[df["ListaCodCaract"].astype(str).str.contains("000002"), "TIPO"] = "PESO"

    elif sistema == "RPOne":
        # RPOne já traz ListaCodCaract no próprio arquivo
        df = df[
            ["CodProduto", "CodGrupo", "Descricao", "Estoq", "Fam", "ListaCodCaract"]
        ]

        # Classificação RPOne: CodGrupo string, ListaCodCaract com "KG"
        CONDICOES = [
            (
                df["ListaCodCaract"].astype(str).str.contains("KG", na=False)
                if "ListaCodCaract" in df.columns
                else False
            ),
            df["CodGrupo"].isin(["REFRIGERADO", "CONGELADO"]),
        ]
        df["TIPO"] = np.select(CONDICOES, ["PESO", "CONG"], default="SECO")

    # ===================== FORNECEDORES =====================
    padrao = "|".join(FORNECEDORES)
    df["Fornecedor"] = df["Descricao"].str.extract(
        f"({padrao})", flags=re.IGNORECASE, expand=False
    )
    df["Fornecedor"] = df["Fornecedor"].fillna("Outros")

    # ===================== FILTROS GERAIS =====================
    if not ignora_negativo:
        df = df[df["Estoq"] > 0].copy()
    df = df[df["TIPO"].isin(ind_grupo)].copy()

    if df.empty:
        st.error(":material/Cancel: Nenhum Produto selecionado")
        st.stop()

    df["Qt Cx"] = 0

    # ===================== FATOR DE CONVERSÃO =====================
    if sistema == "AlterData":
        # AlterData: extrai última palavra da descrição como fator
        df["Fator Conversao"] = df["Descricao"].astype(str).str.split()
        df["Fator Conversao"] = df["Fator Conversao"].str[-1]
        df["Fator Conversao"] = pd.to_numeric(
            df["Fator Conversao"], errors="coerce"
        ).fillna(1)

    elif sistema == "RPOne":
        # RPOne: usa SiglaUn da base original como fator
        df = df.merge(
            df_produto_base[["CodProduto", "SiglaUn"]], on="CodProduto", how="left"
        )
        df["Fator Conversao"] = pd.to_numeric(df["SiglaUn"], errors="coerce").fillna(1)

    # ==================================================================
    # SEÇÃO: LOJAS
    # ==================================================================
    st.markdown("## Lojas")
    df_lojas = pd.DataFrame(todas_lojas["resposta"])
    df_lojas = df_lojas.drop(columns="id")
    fator_porcentagem_total = df_lojas["fator_porcentagem"].sum()

    if fator_porcentagem_total != 100.00:
        st.error(
            f"Fator de porcentagem atual: {fator_porcentagem_total}, esperado 100%"
        )
        st.dataframe(
            df_lojas[["filial", "grupo", "fator_porcentagem"]].sort_values(
                ["fator_porcentagem"], ascending=False
            ),
            hide_index=True,
        )
        if st.button("Corrigir", width="stretch"):
            st.switch_page("Home.py")
        st.stop()

    df_lojas = df_lojas[~df_lojas["grupo"].isin(["atacado", "teste"])]

    with st.expander(":blue[:material/settings:] Mostrar lojas"):

        st.title("Editar Fator de Divisão")

        df_lojas["fator_porcentagem"] = df_lojas["fator_porcentagem"].astype(float)

        df_lojas = st.data_editor(
            df_lojas,
            column_config={
                "fator_porcentagem": st.column_config.NumberColumn(
                    "fator_porcentagem",
                    help="A soma total deve ser exatamente 100%",
                    min_value=0.00,
                    max_value=100.00,
                    step=0.01,
                )
            },
            num_rows="delete",
            disabled=["cod_empresa", "filial", "razao_social", "cnpj", "grupo"],
            hide_index=True,
        )

        # 2. Validação da Soma
        soma_atual = df_lojas["fator_porcentagem"].sum()

        st.metric("SOMA: fator conversão", f"{soma_atual:.2f}%")

        st.bar_chart(df_lojas, x="filial", y="fator_porcentagem")
        if round(soma_atual, 2) == 100.0:
            st.success(":material/Check: Fator de Conversão correto (100%).")
        else:
            diferenca = 100.0 - soma_atual
            if diferenca < 0:
                st.error(f"Necessário subtrair: {diferenca:.2f}%")
            else:
                st.error(f"Necessário somar: {diferenca:.2f}%")
            st.text("Ajuste os valores acima para prosseguir com a divisão.")
            st.stop()

    df_lojas_fatorZero = df_lojas[df_lojas["fator_porcentagem"] <= 0]
    if not df_lojas_fatorZero.empty:
        with st.expander("Mostrar lojas fator zerado"):
            st.info(
                f"Há {len(df_lojas_fatorZero)} lojas sem fator de conversão (zerado)"
            )
            df_lojas_fatorZero
    else:
        st.success("Nenhuma loja com fator de conversão Zerado")
    st.divider()

    # ==================================================================
    # SEÇÃO: SELEÇÃO DE PRODUTOS
    # ==================================================================
    st.markdown("## Selecione os Produtos para Divisão")
    with st.expander(":blue[:material/Edit:] produtos", expanded=True):
        st.write("Selecione os produtos que farão parte da divisão: ")
        grid_divisao = st.dataframe(
            df[["CodProduto", "Descricao", "Fornecedor", "TIPO", "Estoq"]],
            selection_mode="multi-row",
            on_select="rerun",
        )

        itens_divisao = grid_divisao["selection"]["rows"]
        df_divisao = df.iloc[itens_divisao]

    if df_divisao.empty:
        st.error("Selecione ao menos 1 item para divisão")
        st.stop()

    df_divisao = df_divisao[
        [
            "CodProduto",
            "Descricao",
            "Estoq",
            "Fornecedor",
            "TIPO",
            "Qt Cx",
            "Fator Conversao",
        ]
    ]

    st.divider()
    st.markdown("## Informe Quantidade de Caixa")
    df_editado = st.data_editor(
        df_divisao[
            [
                "CodProduto",
                "Descricao",
                "Fornecedor",
                "TIPO",
                "Estoq",
                "Fator Conversao",
                "Qt Cx",
            ]
        ],
        hide_index=True,
        column_config={
            "Qt Cx": st.column_config.NumberColumn(
                "Qt Cx",
                help="Digite a quantidade desejada",
                min_value=0,
                max_value=10_000,
                step=10,
                format="%d",
            ),
            "CodProduto": st.column_config.Column(disabled=True),
            "Descricao": st.column_config.Column(disabled=True),
            "Fornecedor": st.column_config.Column(disabled=True),
            "TIPO": st.column_config.Column(disabled=True),
            "Estoq": st.column_config.Column(disabled=True),
            "Fator Conversao": st.column_config.Column(disabled=True),
        },
        width="stretch",
    )

    if (df_editado["Qt Cx"] == 0).any():
        st.info('Preencher a "Qt Cx" de TODOS dos produtos selecionados')
        st.stop()

    # ==================================================================
    # SEÇÃO: CONFERÊNCIA DA DIVISÃO
    # ==================================================================
    st.divider()
    with st.expander(":blue[:material/Visibility:] Conferir Divisão"):
        resposta = distribuir_estoque_df(df_editado, df_lojas)

        df_cong = resposta[resposta["TIPO"].isin(["CONG", "REFR"])].copy()
        df_peso = resposta[resposta["TIPO"] == "PESO"].copy()
        df_seco = resposta[resposta["TIPO"] == "SECO"]

        st.markdown("# Todas Lojas (Qt Cx)")
        resposta

        st.markdown("### Divisão :blue[SECO]")
        if df_seco.empty:
            st.info("Nenhum item SECO selecionado")
        else:
            df_seco

        st.markdown("### Divisão :blue[CONG/REFR]")
        if df_cong.empty:
            st.info("Nenhum item CONG/REFR selecionado")
        else:
            df_cong

        st.markdown("### Divisão :blue[PESO]")
        if df_peso.empty:
            st.info("Nenhum item PESO selecionado")
        else:
            df_peso

    df_peso = df_peso.drop(columns=["TIPO", "Descricao"])
    df_seco = df_seco.drop(columns=["TIPO", "Descricao"])
    df_cong = df_cong.drop(columns=["TIPO", "Descricao"])

    # ==================================================================
    # SEÇÃO: EXPORTAÇÃO CONDICIONAL POR SISTEMA
    # ==================================================================
    st.divider()

    if sistema == "AlterData":
        # ================ EXPORTAÇÃO ALTERDATA (.txt) ================
        st.markdown("# DIVISÃO .TXT", text_alignment="center")

        df_txt_seco = extrai_qt_TXT_alterdata(df_seco)
        df_txt_cong = extrai_qt_TXT_alterdata(df_cong)
        df_txt_peso = extrai_qt_TXT_alterdata(df_peso)

        col_txt_seco, col_txt_cong, col_txt_peso = st.columns(3, gap="medium")

        with col_txt_seco:
            criar_downloads_alterdata(df_txt_seco, "SECO")
        with col_txt_cong:
            criar_downloads_alterdata(df_txt_cong, "CONG")
        with col_txt_peso:
            criar_downloads_alterdata(df_txt_peso, "PESO")

    elif sistema == "RPOne":
        # ================ EXPORTAÇÃO RP ONE (.apv) ================
        st.markdown("# DIVISÃO .APV (RP One)", text_alignment="center")

        # Monta mapa de cod_cliente por filial (busca da tabela clientes/lojas)
        cod_cliente_map = {}

        if "cod_cliente_loja" in df_lojas.columns:
            cod_cliente_map = dict(
                zip(df_lojas["filial"], df_lojas["cod_cliente_loja"])
            )
        else:
            # Tenta buscar de uma tabela separada se disponíve'l
            try:
                from supabase import create_client as _sc

                _url = st.secrets["connections"]["supabase"]["url"]
                _key = st.secrets["connections"]["supabase"]["key"]
                _sb = _sc(_url, _key)
                _resp = _sb.table("Lojas").select("Filial, cod_cliente_loja").execute()
                _df_lojas_rp = pd.DataFrame(_resp.data)
                if not _df_lojas_rp.empty:
                    cod_cliente_map = dict(
                        zip(_df_lojas_rp["Filial"], _df_lojas_rp["cod_cliente_loja"])
                    )
            except Exception:
                st.warning(
                    "Não foi possível buscar cod_cliente_loja. "
                    "Verifique se a coluna existe na tabela de lojas."
                )

        df_txt_seco = extrai_qt_RPOne(df_seco, df_produto_base)
        df_txt_cong = extrai_qt_RPOne(df_cong, df_produto_base)
        df_txt_peso = extrai_qt_RPOne(df_peso, df_produto_base)

        col_txt_seco, col_txt_cong, col_txt_peso = st.columns(3, gap="medium")

        with col_txt_seco:
            criar_downloads_rpone(df_txt_seco, "SECO", cod_cliente_map, doc_padrao)
        with col_txt_cong:
            criar_downloads_rpone(df_txt_cong, "CONG", cod_cliente_map, doc_padrao)
        with col_txt_peso:
            criar_downloads_rpone(df_txt_peso, "PESO", cod_cliente_map, doc_padrao)

# --- SIDEBAR: informações adicionais
with st.sidebar:
    st.space()
    st.markdown("### Produtos Base")
    st.write(f"Produtos cadastrados na memória: :blue[{produtos_cadastrados}]")
    if link_produto:
        st.link_button("Acessar Arquivo Principal", link_produto)
    if sistema == "AlterData" and link_produto_extra:
        st.link_button("Acessar Arquivo Extra", link_produto_extra)
