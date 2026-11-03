import streamlit as st
import pandas as pd
import re
import io
import numpy as np
from utils import (
    carregar_dados_onedrive,
    carregar_dados_onedrive_rp,
    converte_ultima_modificacao,
)


# --- FUNÇÕES E DEFINIÇÕES ---
def abrir_arquivo_txt(arquivo, colunas=None, separador="|", eng=None):
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
        st.error(f"Erro ao ler arquivo {e}")
        st.stop()


COLUNAS_PRODUTOS_ALTERDATA = [
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
COLUNAS_PRODUTOS_PRECO = ["Tabela", "CodProduto", "Preco"]

FORNECEDORES = [
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

# --- CONF PAGINA ---
st.set_page_config(page_title="Gestor de Listas e Atacado", layout="wide")

# --- SIDEBAR DE CONTROLE ---
with st.sidebar:
    st.markdown("## ⚙️ Configuração do Sistema")
    sistema = st.pills(
        "Selecione o ERP de Destino:", ["AlterData", "RPOne"], default="RPOne"
    )
    modo = st.radio("Modo de Operação:", ["Lista Comum", "Atacado"])
    if modo == "Atacado":
        habilita_preco_cx = st.toggle("Habilitar Preço por Caixa", value=False)
    else:
        habilita_preco_cx = False
    if sistema == "AlterData":
        link_produto = st.secrets["onedrive"]["links"]["produto"]
        link_produto_extra = st.secrets["onedrive"]["links"]["produto_extra"]
        link_tabela_preco = st.secrets["onedrive"]["links"]["tabela_preco"]

    if sistema == "RPOne":
        link_produto = st.secrets["onedrive"]["links"]["produto_rp_txt"]
        link_produto_extra = None
        link_tabela_preco = None

# --- CABEÇALHO ---
if modo == "Lista Comum":
    st.title(f":material/Attach_File: Editor de :red[Lista] ({sistema})")
else:
    st.title(
        f":material/Shopping_Cart: Tabela de Produtos para :red[Atacado] ({sistema})"
    )

# --- CARREGAMENTO AUTOMÁTICO ---
desativa_manual = False
f_produto_auto = f_extra_auto = f_tabela_preco_auto = None
GRUPO = ["SECO", "CONG", "REFR", "PESO"]  # Padrão Inicial

bd_automatico = st.toggle("Deseja pegar arquivos automaticamente?", value=True)
if bd_automatico:
    desativa_manual = True

    if sistema == "AlterData":
        if "dados_onedrive" not in st.session_state:
            st.session_state.dados_onedrive = carregar_dados_onedrive(link_produto)
        if "dados_onedrive_extra" not in st.session_state:
            st.session_state.dados_onedrive_extra = carregar_dados_onedrive(
                link_produto_extra
            )

        resp = st.session_state.dados_onedrive
        resp_extra = st.session_state.dados_onedrive_extra

        if resp["falha"]:
            st.error("Erro ao pegar produto.txt")
        if resp_extra["falha"]:
            st.error("Erro ao pegar produto_extra.txt")

        f_produto_auto = resp["resp"]
        f_extra_auto = resp_extra["resp"]

        if modo == "Atacado":
            if "dados_onedrive_preco" not in st.session_state:
                st.session_state.dados_onedrive_preco = carregar_dados_onedrive(
                    link_tabela_preco
                )
            resp_preco = st.session_state.dados_onedrive_preco
            if resp_preco["falha"]:
                st.error("Erro ao pegar produtotabela.txt")
            f_tabela_preco_auto = resp_preco["resp"]

        data_mod = resp["data"]

    if sistema == "RPOne":
        if "dados_onedrive_rp" not in st.session_state:
            st.session_state.dados_onedrive_rp = carregar_dados_onedrive(link_produto)

        resp = st.session_state.dados_onedrive_rp
        if resp["falha"]:
            st.error("Erro ao pegar csv de produtos RPOne")
        f_produto_auto = resp["resp"]

        f_produto_auto = abrir_arquivo_txt(
            f_produto_auto, COLUNAS_PRODUTOS_RP, ";", "python"
        )

        f_produto_auto["TIPO"] = f_produto_auto["CodGrupo"]

        if not resp["falha"]:
            # GRUPO = f_produto_auto["CodGrupo"].unique().tolist()
            GRUPO = f_produto_auto["TIPO"].unique().tolist()
            if "PESO" not in GRUPO:
                GRUPO.append("PESO")

            GRUPO = ["Sem Grupo" if pd.isna(x) else x for x in GRUPO]
            if "Sem Grupo" in GRUPO:
                f_produto_auto["TIPO"] = f_produto_auto["TIPO"].fillna("Sem Grupo")

        data_mod = resp["data"]

    if data_mod:
        dt = converte_ultima_modificacao(data_mod)
        st.write(
            f"Ultima modificação base: :red[{dt.strftime('%H:%M:%S')}]  | :red[{dt.strftime('%d/%m/%Y')}]"
        )

# --- UPLOAD MANUAL DE ARQUIVOS (Se bd_automatico for falso) ---
c1, c2, c3 = st.columns(3)
with c1:
    f_produto = st.file_uploader(
        f":material/Barcode: Produtos ({sistema})", disabled=desativa_manual
    )
with c2:
    if sistema == "AlterData":
        f_extra = st.file_uploader(
            ":material/Add: Produto Extra", disabled=desativa_manual
        )
    if sistema == "RPOne":
        f_extra = None
with c3:
    if modo == "Atacado":
        f_tabela_preco = st.file_uploader(
            ":material/Add: Tabela de Preço", disabled=desativa_manual
        )
    else:
        f_tabela_preco = None

# --- FILTROS UI ---
st.subheader(":material/Toggle_On: Exceções: O que retirar/filtrar")
c1, c2 = st.columns(2)
with c1:
    ind_neg = st.checkbox("[:material/Stat_Minus_1:]  Estoque Negativo", value=True)
    ind_div = st.checkbox("[:material/Safety_Divider:]  Divisão", value=True)
    if modo == "Lista Comum":
        ind_loja = st.checkbox("[:material/Shopping_Bag:]  Loja", value=True)
    else:
        ind_preco_zero = st.checkbox("[:material/Sell:] Preço Zerado", value=True)
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

# --- PROCESSAMENTO PRINCIPAL ---
iniciar_processamento = False
if desativa_manual:
    iniciar_processamento = True
elif sistema == "AlterData":
    if modo == "Lista Comum":
        iniciar_processamento = (f_produto is not None) and (f_extra is not None)
    else:
        iniciar_processamento = (
            (f_produto is not None)
            and (f_extra is not None)
            and (f_tabela_preco is not None)
        )
elif sistema == "RPOne":
    iniciar_processamento = f_produto is not None

if iniciar_processamento:
    with st.status("Processando dados...", expanded=True) as status:

        # 1. Carrega DFs Base
        if sistema == "AlterData":
            df = abrir_arquivo_txt(
                f_produto_auto if desativa_manual else f_produto,
                COLUNAS_PRODUTOS_ALTERDATA,
            )
            df_extra = abrir_arquivo_txt(
                f_extra_auto if desativa_manual else f_extra, COLUNAS_PRODUTOS_EXTRA
            )
            if modo == "Atacado":
                df_preco = abrir_arquivo_txt(
                    f_tabela_preco_auto if desativa_manual else f_tabela_preco,
                    COLUNAS_PRODUTOS_PRECO,
                )
        if sistema == "RPOne":
            df = (
                f_produto_auto
                if desativa_manual
                else pd.read_csv(f_produto, sep=None, engine="python")
            )
            df_extra = None

        produtos_cadastrados = len(df)

        # 2. Merge de Atributos e Classificação de "TIPO"
        if sistema == "AlterData":
            df_merge = df.merge(
                df_extra[["CodProduto", "ListaCodCaract"]], on="CodProduto", how="left"
            )
            df_merge = df_merge[
                [
                    "CodProduto",
                    "CodGrupo",
                    "Descricao",
                    "Estoq",
                    "Fam",
                    "ListaCodCaract",
                ]
            ]

            df_merge["TIPO"] = "SECO"
            df_merge.loc[df_merge["CodGrupo"].isin([9]), "TIPO"] = "CONG"
            df_merge.loc[df_merge["CodGrupo"].isin([14]), "TIPO"] = "REFR"
            df_merge.loc[
                df_merge["ListaCodCaract"].astype(str).str.contains("000002", na=False),
                "TIPO",
            ] = "PESO"
        if sistema == "RPOne":
            df_merge = df.copy()

            df_merge = df_merge.rename(
                columns={"MinVenda": "Atacado", "PrecoUnPd": "Lojas"}
            )

            df_merge = (
                df_merge[
                    [
                        "CodProduto",
                        "TIPO",
                        "Descricao",
                        "Estoq",
                        "Fam",
                        "ListaCodCaract",
                        "Atacado",
                        "Lojas",
                    ]
                ]
                if "ListaCodCaract" in df_merge
                else df_merge[
                    [
                        "CodProduto",
                        "TIPO",
                        "Descricao",
                        "Atacado",
                        "Lojas",
                        "Estoq",
                        "Fam",
                    ]
                ]
            )

            if "ListaCodCaract" in df_merge.columns:
                df_merge.loc[
                    df_merge["ListaCodCaract"].astype(str).str.contains("KG", na=False),
                    "TIPO",
                ] = "PESO"

        # 3. Definição do Fornecedor e Família
        if modo == "Atacado":
            if sistema == "AlterData":
                padrao = "|".join(FORNECEDORES)
                df_merge["Fornecedor"] = df_merge["Descricao"].str.extract(
                    f"({padrao})", flags=re.IGNORECASE, expand=False
                )
                df_merge["Fornecedor"] = df_merge["Fornecedor"].fillna("Outros")
            else:
                df_merge["Fornecedor"] = df_merge["Descricao"].str.split().str[-3]
        else:
            df_merge["Fornecedor"] = df_merge["Descricao"].str.split().str[-3]

        df_merge["FAMILIA"] = "-"
        df_merge.loc[df_merge["Fam"] == 900000007, "FAMILIA"] = "LISTA"
        df_merge.loc[df_merge["Fam"] == 900000008, "FAMILIA"] = "DIVISAO"
        df_merge.loc[df_merge["Fam"] == 900000009, "FAMILIA"] = "LOJA"

        # 4. Merge de Preços (Somente Atacado)
        if modo == "Atacado":

            if sistema == "AlterData":
                df_preco_pivot = df_preco.pivot(
                    index="CodProduto", columns="Tabela", values="Preco"
                ).reset_index()
                df_completo = df_merge.merge(
                    df_preco_pivot, on="CodProduto", how="left"
                )
                df_completo = df_completo.rename(
                    columns={"SUGER": "Lojas", "PRATI": "Atacado"}
                )

            if sistema == "RPOne":
                df_completo = df_merge.copy()
        else:
            df_completo = df_merge.copy()

        # 5. Filtros Visuais
        if ind_neg:
            df_completo = df_completo[df_completo["Estoq"] > 0].copy()
        if ind_div:
            df_completo = df_completo[df_completo["Fam"] != 900000008].copy()
        if modo == "Lista Comum" and ind_loja:
            df_completo = df_completo[df_completo["Fam"] != 900000009].copy()
        df_completo = df_completo[df_completo["TIPO"].isin(ind_grupo)].copy()
        if ind_qtmin:
            df_completo = df_completo[df_completo["Estoq"] > ind_qtmin]

        if modo == "Atacado" and ind_preco_zero:
            df_completo = df_completo[
                (df_completo["Atacado"] > 0) & (df_completo["Lojas"] > 0)
            ]

        if df_completo.empty:
            st.error(":material/Cancel: Nenhum item selecionado após filtros")
            status.update(label="Concluído (Vazio)", state="complete")
            st.stop()

        st.write(
            f":material/Delete: Selecione produtos para remover da lista original: :red[{len(df_completo)} itens]"
        )

        cols_visualizacao = ["CodProduto", "Descricao", "Fornecedor", "TIPO", "Estoq"]
        if modo == "Lista Comum":
            cols_visualizacao.insert(4, "FAMILIA")

        remover_linhas = st.dataframe(
            df_completo[cols_visualizacao],
            hide_index=True,
            selection_mode="multi-row",
            on_select="rerun",
        )

        # 6. Remoção de Selecionados e Tratamentos Finais
        ind_remover = remover_linhas["selection"]["rows"]
        df_removido = (
            df_completo.drop(df_completo.index[ind_remover])
            .copy()
            .sort_values(by="Fornecedor")
        )

        if modo == "Atacado":
            if habilita_preco_cx:
                ultimo = df_removido["Descricao"].astype(str).str.split().str[-1]
                df_removido["CONV"] = np.where(ultimo.str.isdigit(), ultimo, 1).astype(
                    float
                )
                df_removido["Venda"] = df_removido["CONV"] * df_removido["Lojas"]
                df_removido["R$ Venda"] = df_removido["Venda"].map(
                    lambda x: f"R$ {x:,.2f}".replace(",", "X")
                    .replace(".", ",")
                    .replace("X", ".")
                )

            df_removido["Lojas_FMT"] = df_removido["Lojas"].map(
                lambda x: f"R$ {x:,.2f}".replace(",", "X")
                .replace(".", ",")
                .replace("X", ".")
            )
            df_removido["Atacado_FMT"] = df_removido["Atacado"].map(
                lambda x: f"R$ {x:,.2f}".replace(",", "X")
                .replace(".", ",")
                .replace("X", ".")
            )

        if df_removido.empty:
            st.write(":material/List: :red[Nenhum item na lista]")
            st.stop()
        else:
            cor_txt = "red" if len(df_removido) == len(df_completo) else "blue"
            st.write(
                f":material/List: Total Itens na lista: :{cor_txt}[{len(df_removido)} itens]"
            )

        status.update(label="Processamento concluído!", state="complete")

    # --- RENDERIZAÇÃO FINAL ---
    if modo == "Lista Comum":
        # Formatação Visual de Lista (em Colunas com Código)
        colunas = st.columns(max(len(ind_grupo), 1))

        for idx, tipo in enumerate(ind_grupo):
            df_filtrado = df_removido[df_removido["TIPO"] == tipo]
            with colunas[idx % len(colunas)]:
                if not df_filtrado.empty:
                    with st.expander(
                        f":material/Copy_All: {len(df_filtrado)} itens: {tipo}",
                        expanded=True,
                    ):

                        # Padroniza Cabeçalho baseado no sistema
                        if sistema == "AlterData":
                            cabecalhos = {
                                "CONG": "CONGELADO",
                                "REFR": "REFRIGERADO",
                                "SECO": "SECO",
                                "PESO": "PESÁVEIS",
                            }
                            titulo = cabecalhos.get(tipo, tipo)
                        if sistema == "RPOne":
                            titulo = tipo

                        dfList = [titulo] + df_filtrado["Descricao"].astype(
                            str
                        ).tolist()
                        texto_formatado = "\n".join(dfList)

                        st.code(texto_formatado, language=None)
                        st.caption(
                            f"Clique no ícone no canto superior direito para copiar {tipo}."
                        )
                else:
                    st.info(f":material/Cancel: {tipo} Sem itens")

    elif modo == "Atacado":
        # Formatação Visual de Atacado (Tabelas e Análise de Preços)
        st.divider()
        st.markdown("## :material/Sell: Lista Atacado:")

        if habilita_preco_cx:
            st.dataframe(
                df_removido[
                    [
                        "CodProduto",
                        "Descricao",
                        "Lojas_FMT",
                        "R$ Venda",
                        "Fornecedor",
                        "Estoq",
                    ]
                ].rename(columns={"Lojas_FMT": "R$/Un"}),
                hide_index=True,
            )
        else:
            st.dataframe(
                df_removido[
                    [
                        "CodProduto",
                        "Descricao",
                        "Atacado_FMT",
                        "Fornecedor",
                        "Estoq",
                    ]
                ].rename(columns={"Atacado_FMT": "Atacado"}),
                hide_index=True,
            )

        st.divider()
        if st.toggle("Mostrar Análise e Discrepâncias de Preços"):
            st.markdown("### Validar preço dos produtos abaixo")

            df_atencao = df_completo[
                [
                    "CodProduto",
                    "Descricao",
                    "Estoq",
                    "Lojas",
                    "Atacado",
                    "Fornecedor",
                    "TIPO",
                ]
            ].copy()
            df_atencao["Dif_Preco"] = df_atencao["Lojas"] - df_atencao["Atacado"]

            st.markdown("#### Mesmo Preço - Lojas e Atacado")
            st.dataframe(
                df_atencao[df_atencao["Dif_Preco"] == 0].sort_values(
                    by="Estoq", ascending=False
                ),
                hide_index=True,
            )

            st.markdown("#### Preço Maior nas Lojas")
            df_atencao["Dif_Perc"] = (
                df_atencao["Dif_Preco"] / df_atencao["Lojas"]
            ) * 100
            st.dataframe(
                df_atencao[df_atencao["Dif_Preco"] > 0].sort_values(
                    by="Dif_Perc", ascending=False
                ),
                hide_index=True,
            )

            st.markdown("#### Desconto maior que 50% para Atacado")
            st.dataframe(
                df_atencao[df_atencao["Dif_Perc"] <= -50].sort_values(by="Dif_Perc"),
                hide_index=True,
            )  # Atualizei de -20 visual para -50 para condizer c o título

else:
    st.info("Insira os arquivos indicados para começar a visualização.")

# --- INFORMAÇÕES DA SIDEBAR ---
with st.sidebar:
    st.divider()
    if link_produto:
        st.link_button("📄 Acessar Base: Produtos", link_produto)
    if link_produto_extra:
        st.link_button("📄 Acessar Base: Extra", link_produto_extra)
    if link_tabela_preco and modo == "Atacado":
        st.link_button("📄 Acessar Base: Preços", link_tabela_preco)

    st.write(f"Produtos em memória: :blue[{produtos_cadastrados}]")
