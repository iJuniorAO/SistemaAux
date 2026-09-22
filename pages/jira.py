import streamlit as st
import pandas as pd
from jira import JIRA
from datetime import datetime
from typing import Optional, Dict, Any, List
from utils import validar_acesso

# ==========================================
# CONFIGURAÇÃO INICIAL E CONSTANTES
# ==========================================

st.set_page_config(
    page_title="Central Mumix - Jira",
    layout="wide",
    page_icon=":material/local_post_office:",
)

TODAY_STR = datetime.now().strftime("%d/%m/%Y")
JQL_DEFAULT = "id is not EMPTY ORDER BY created DESC"

# Leitura segura de links do st.secrets
LINK_PORTAL = st.secrets.get("jira", {}).get("link_portal_cliente", "#")
LINK_FORMULARIO = st.secrets.get("jira", {}).get("link_formulario", "#")
JIRA_URL = st.secrets.get("jira", {}).get("url", "")

# Mapeamento dos IDs de campos customizados do Jira
JIRA_FIELD_MAP: Dict[str, str] = {
    "loja": "customfield_10126",
    "fornecedor": "customfield_10129",
    "motivo": "customfield_10127",
    "cod_produto": "customfield_10184",
    "qtd_produto": "customfield_10185",
    "desc_produto": "customfield_10125",
}

# Mapeamento do Status da issue para o índice da coluna no Kanban
STATUS_COLUMN_INDEX: Dict[str, int] = {
    "Aberto": 0,
    "Validação NFe": 1,
    "Ordem de Coleta": 2,
    "Negociação Fornecedor": 3,
    "Concluído (reposição)": 4,
    "Concluído (prejuízo)": 4,
    "Concluído (estoque)": 4,
    "Troca Recusada": 4,
}

BOARD_TITLES: List[str] = [
    ":material/Edit: A fazer",
    ":material/Barcode: Validação NFe",
    ":material/Send: Ordem de Coleta",
    ":material/Group: Negociação Fornecedor",
    ":material/Check: Concluído",
]

# Validação de acesso do usuário
validar_acesso(["administrador", "prevencao"])


# ==========================================
# FUNÇÕES DE INFRAESTRUTURA E CONEXÃO JIRA
# ==========================================


@st.cache_resource(show_spinner="Conectando ao Jira...")
def conectar_jira() -> Optional[JIRA]:
    """
    Estabelece e armazena em cache a conexão com a API do Jira.
    Retorna None em caso de falha de conexão.
    """
    try:
        jira_secrets = st.secrets["jira"]
        return JIRA(
            server=jira_secrets["url"],
            basic_auth=(jira_secrets["email"], jira_secrets["token"]),
        )
    except Exception as e:
        st.error(f"Erro ao conectar ao Jira: {e}")
        return None


def _extrair_dados_issue(issue: Any) -> Dict[str, Any]:
    """
    Extrai e sanitiza os campos de um objeto Issue do Jira com tratamento de nulos.
    """
    fields = issue.fields
    assignee = getattr(fields, "assignee", None)
    responsavel = assignee.displayName if assignee else "Não atribuído"
    created = getattr(fields, "created", "") or ""
    criado_em = created[:10] if len(created) >= 10 else "-"
    descricao = getattr(fields, "description", None) or "Sem descrição informada."

    fornecedor = issue.get_field(JIRA_FIELD_MAP["fornecedor"])

    return {
        "key": issue.key,
        "summary": getattr(fields, "summary", ""),
        "status": (
            getattr(fields.status, "name", "") if hasattr(fields, "status") else ""
        ),
        "tipo": (
            getattr(fields.issuetype, "name", "")
            if hasattr(fields, "issuetype")
            else ""
        ),
        "responsavel": responsavel,
        "criado_em": criado_em,
        "descricao": descricao,
        "loja": issue.get_field(JIRA_FIELD_MAP["loja"]) or "-",
        "fornecedor": "-" if fornecedor is None else fornecedor,
        "motivo": issue.get_field(JIRA_FIELD_MAP["motivo"]) or "",
        "cod_produto": issue.get_field(JIRA_FIELD_MAP["cod_produto"]) or "-",
        "qtd_produto": issue.get_field(JIRA_FIELD_MAP["qtd_produto"]) or 0,
        "desc_produto": issue.get_field(JIRA_FIELD_MAP["desc_produto"]) or "-",
    }


def buscar_dados_jira(jira_conn: Optional[JIRA], jql: str) -> pd.DataFrame:
    """
    Realiza a busca no Jira via JQL e converte o resultado em um DataFrame pandas.
    """
    if not jira_conn:
        return pd.DataFrame()

    try:
        issues = jira_conn.search_issues(jql, maxResults=False)
        dados = [_extrair_dados_issue(issue) for issue in issues]
        return pd.DataFrame(dados)
    except Exception as e:
        st.error(f"Erro ao buscar dados do Jira: {e}")
        return pd.DataFrame()


# ==========================================
# COMPONENTES DE INTERFACE DE USUÁRIO (UI)
# ==========================================


def renderizar_board(df: pd.DataFrame):
    """
    Renderiza o Quadro Kanban agrupando tarefas por colunas de status.
    """

    if "loja" in df.columns and not df.empty:
        todas_lojas = sorted([str(l) for l in df["loja"].dropna().unique()])
        lojas_selecionadas = st.multiselect(
            "Filtrar por Loja",
            options=todas_lojas,
            placeholder="Todas as lojas",
        )
        if lojas_selecionadas:
            df = df[df["loja"].astype(str).isin(lojas_selecionadas)]

    st.markdown(f"# :material/dashboard: Quadro :blue[({len(df)})]")

    # Agrupa os cards diretamente em listas nativas (evita iterrows para alta performance)
    cards_por_coluna: List[List[Dict[str, Any]]] = [[] for _ in range(5)]

    if not df.empty:
        records = df.to_dict("records")
        for row in records:
            col_idx = STATUS_COLUMN_INDEX.get(row["status"], 0)
            cards_por_coluna[col_idx].append(row)

    colunas_ui = st.columns(5)

    for titulo, col_ui, cards in zip(BOARD_TITLES, colunas_ui, cards_por_coluna):
        with col_ui:
            with st.expander(
                f"{titulo} :blue[({len(cards)})]", type="compact", expanded=True
            ):
                for row in cards:
                    with st.container(border=True):
                        motivo_str = str(row["motivo"]).upper() if row["motivo"] else ""
                        st.markdown(f"##### **{row['key']}** | {motivo_str}")
                        cardCol1, cardCol2 = st.columns(2)
                        with cardCol1:
                            st.markdown(f"**LOJA:** {row['loja']}")
                        with cardCol2:
                            st.markdown(f"**Aberto em:** {row['criado_em']}")
                        st.markdown(
                            f"**{row['cod_produto']}** | {row['qtd_produto']}x {row['desc_produto']}"
                        )
                        st.markdown(
                            f"[🔗 Abrir no Jira]({JIRA_URL}/browse/{row['key']})"
                        )


def renderizar_painel_detalhado(
    jira_conn: Optional[JIRA], jql: str, inicio_registro: int, itens_por_pagina: int
):
    """
    Busca e exibe as tarefas de forma paginada e detalhada via expanders.
    """
    if not jira_conn:
        st.info("Aguardando conexão com o Jira...")
        return

    with st.spinner("Buscando tarefas no Jira..."):
        try:
            # issues = jira_conn.search_issues(
            #     jql, startAt=inicio_registro, maxResults=itens_por_pagina
            # )

            issues = jira_conn.search_issues(jql)

            total_issues = getattr(issues, "total", len(issues))

            st.markdown(f"## Ultimas Tarefas :blue[({total_issues})]")

            if issues:
                for issue in issues:
                    fields = issue.fields
                    assignee = getattr(fields, "assignee", None)
                    responsavel = assignee.displayName if assignee else "Não atribuído"
                    status_name = (
                        getattr(fields.status, "name", "-")
                        if hasattr(fields, "status")
                        else "-"
                    )
                    issue_type = (
                        getattr(fields.issuetype, "name", "-")
                        if hasattr(fields, "issuetype")
                        else "-"
                    )
                    created = getattr(fields, "created", "") or ""
                    criado_em = created[:10] if len(created) >= 10 else "-"
                    descricao = (
                        getattr(fields, "description", None)
                        or "*Sem descrição informada.*"
                    )

                    if status_name == "Aberto":
                        titulo_card = f":red[**{issue.key}** - *{status_name}*]"
                    else:
                        titulo_card = f"**{issue.key}** - *{status_name}*"
                    with st.expander(titulo_card):
                        col1, col2 = st.columns(2)
                        with col1:
                            st.write(f"**Status:** {status_name}")
                            st.write(f"**Tipo:** {issue_type}")
                            st.write(f"**Responsável:** {responsavel}")
                        with col2:
                            st.write(f"**Criado em:** {criado_em}")
                            st.markdown(
                                f"[🔗 Abrir diretamente no Jira]({JIRA_URL}/browse/{issue.key})"
                            )

                        st.markdown("---")
                        st.write("**Descrição:**")
                        st.write(descricao)
            else:
                st.info("Nenhuma tarefa corresponde aos filtros selecionados.")

        except Exception as e:
            st.error(f"Erro ao processar a busca no Jira: {e}")


def renderizar_ordens_coleta(df: pd.DataFrame):
    """
    Filtra e renderiza as ordens de coleta agrupadas por loja.
    """
    df_coleta = df[df["status"] == "Ordem de Coleta"]

    if df_coleta.empty:
        st.success(
            "Nenhuma tarefa no status 'Ordem de Coleta' para gerar ordens de coleta."
        )
        return

    st.markdown("# Todas Coletas")

    datas_coleta = pd.to_datetime(df_coleta["criado_em"], errors="coerce")
    coleta_mais_antiga = datas_coleta.min()
    coleta_mais_antiga_texto = (
        coleta_mais_antiga.strftime("%d/%m/%Y") if pd.notna(coleta_mais_antiga) else "-"
    )

    metrica_lojas, metrica_coletas, metrica_antiga = st.columns(3)
    metrica_lojas.metric("Lojas", df_coleta["loja"].nunique())
    metrica_coletas.metric("Coletas", len(df_coleta))
    metrica_antiga.metric("Chamado mais Antigo", coleta_mais_antiga_texto)

    # Iteração por loja
    lojas_coleta = df_coleta["loja"].unique()

    for loja in lojas_coleta:
        st.markdown("## Ordem de Coleta")
        c1, c2, c3 = st.columns(3)
        c1.markdown(f"### :material/store: Loja: {loja}")
        c2.markdown("### Motorista:______________")
        c3.markdown(f"### {TODAY_STR}")

        df_loja = df_coleta[df_coleta["loja"] == loja].copy()
        df_loja["Coletado"] = False

        # Projeção limpa de colunas com renomeações explicítas
        df_display = df_loja[
            ["cod_produto", "desc_produto", "qtd_produto", "key", "Coletado"]
        ].rename(
            columns={
                "cod_produto": "Cód. Produto",
                "desc_produto": "Descrição / Produto",
                "qtd_produto": "Qtd",
                "key": "Ticket",
                "Coletado": "Coletado",
            }
        )

        st.dataframe(df_display, hide_index=True, width="stretch")
        st.space("xxlarge")
        st.divider()


def renderizar_dashboard(df: pd.DataFrame):
    """
    Renderiza o dashboard com os KPIs e gráficos da operação.
    """
    if df.empty:
        st.warning("Não há dados suficientes para gerar os indicadores.")
        return

    st.markdown("# :material/monitoring: Dashboard de Indicadores")

    # Cálculos dos KPIs
    df_aprovados = df[
        df["status"].astype(str).str.contains("Concluído", case=False, na=False)
    ]
    df_rejeitados = df[
        df["status"]
        .astype(str)
        .str.contains("Recusada|Rejeitada", case=False, na=False)
    ]

    qtd_aprovados = len(df_aprovados)
    qtd_rejeitados = len(df_rejeitados)

    contagem_lojas = df["loja"].value_counts()

    loja_mais_problemas = "-"
    loja_menos_problemas = "-"
    if not contagem_lojas.empty:
        loja_mais_problemas = str(contagem_lojas.idxmax())
        loja_menos_problemas = str(contagem_lojas.idxmin())

    contagem_aprovados = df_aprovados["loja"].value_counts()
    loja_mais_aprovados = "-"
    loja_menos_aprovados = "-"
    if not contagem_aprovados.empty:
        loja_mais_aprovados = str(contagem_aprovados.idxmax())
        loja_menos_aprovados = str(contagem_aprovados.idxmin())

    contagem_rejeitados = df_rejeitados["loja"].value_counts()
    loja_mais_rejeitados = "-"
    loja_menos_rejeitados = "-"

    if not contagem_rejeitados.empty:
        loja_mais_rejeitados = str(contagem_rejeitados.idxmax())
        loja_menos_rejeitados = str(contagem_rejeitados.idxmin())

    contagem_motivos = df["motivo"].value_counts()
    motivo_mais_comum = contagem_motivos.idxmax() if not contagem_motivos.empty else "-"

    # Exibição dos Métricas em colunas
    c1, c2, c3, c4 = st.columns(4)
    c1.metric("Total Tickets", len(df))
    c2.metric(
        "Tickets Aprovados",
        qtd_aprovados,
        delta=f"{qtd_aprovados / len(df):.2%}",
        delta_color="off",
        delta_arrow="off",
    )
    c3.metric(
        "Tickets Rejeitados",
        qtd_rejeitados,
        delta=f"{qtd_rejeitados / len(df):.2%}",
        delta_color="off",
        delta_arrow="off",
    )
    c4.metric(
        "Motivo + Comum",
        str(motivo_mais_comum),
        delta=f"{contagem_motivos.max()}",
        delta_color="inverse",
        delta_arrow="off",
    )

    c5, c6, c7, c8 = st.columns(4)
    c5.metric(
        "Loja + Problemas",
        loja_mais_problemas,
        delta=f"{contagem_lojas.max()}",
        delta_color="inverse",
        delta_arrow="off",
    )

    c6.metric(
        "Loja - Problemas",
        loja_menos_problemas,
        delta=f"{contagem_lojas.min()}",
        delta_arrow="off",
    )

    c7.metric(
        "Loja + Aprovados",
        loja_mais_aprovados,
        delta=f"{contagem_aprovados.max()}",
        delta_color="off",
        delta_arrow="off",
    )
    c8.metric(
        "Loja + Rejeitados",
        loja_mais_rejeitados,
        delta=f"{contagem_rejeitados.max()}",
        delta_color="inverse",
        delta_arrow="off",
    )

    st.divider()

    # Gráficos
    g1, g2 = st.columns(2)

    with g1:
        st.markdown("### Tickets por Mês")
        df_mes = df.copy()
        df_mes["mes"] = (
            pd.to_datetime(df_mes["criado_em"], errors="coerce")
            .dt.to_period("M")
            .astype(str)
        )
        tickets_por_mes = df_mes["mes"].value_counts().sort_index()
        st.bar_chart(tickets_por_mes)

    with g2:
        st.markdown("### Problemas por Loja")
        st.bar_chart(contagem_lojas, sort="-count")

    st.markdown("### Motivos mais frequentes")
    st.bar_chart(contagem_motivos, sort="-count")


# ==========================================
# FLUXO PRINCIPAL (MAIN EXECUTION)
# ==========================================

jira = conectar_jira()

# --- BARRA LATERAL (FILTROS E PAGINAÇÃO) ---


# --- CARREGAMENTO INICIAL DE DADOS ---
if "df_jira" not in st.session_state:
    with st.spinner("Carregando dados iniciais do Jira..."):
        st.session_state["df_jira"] = buscar_dados_jira(jira, JQL_DEFAULT)

df_jira = st.session_state["df_jira"]

# --- RENDERIZAÇÃO DO CORPO PRINCIPAL ---
st.markdown("# :material/local_post_office: Central Trocas e Devoluções")
st.markdown(f"Portal: [:material/Captive_Portal: Portal do Cliente]({LINK_PORTAL})")
st.markdown(
    f"Link das Lojas: [:material/Content_Paste: Formulário Trocas e Devoluções]({LINK_FORMULARIO})"
)
st.divider()

if not df_jira.empty:
    aba_board, aba_view, aba_coleta, aba_dashboard = st.tabs(
        [
            ":material/Bar_Chart: Quadro (Board)",
            ":material/Docs: Painel de Tarefas (detalhado)",
            ":material/Package: Ordem Coleta",
            ":material/monitoring: Dashboard",
        ]
    )

    with aba_board:
        renderizar_board(df_jira)

    with aba_view:
        renderizar_painel_detalhado(jira, JQL_DEFAULT, 1, 20)

    with aba_coleta:
        renderizar_ordens_coleta(df_jira)

    with aba_dashboard:
        renderizar_dashboard(df_jira)

st.divider()
