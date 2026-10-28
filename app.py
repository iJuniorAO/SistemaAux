import streamlit as st

st.set_page_config(page_title="Sistema Mumix", layout="wide")

if "perfil" not in st.session_state:
    st.session_state["perfil"] = {"role": "client"}

# login
login_page = st.Page("login.py", title="Login", icon=":material/login:")
home_page = st.Page("Home.py", title="Home", icon=":material/home:")
margem_page = st.Page(
    "pages/8Conversor_Margem.py",
    title="margem x markup",
    icon=":material/swap_horizontal_circle:",
)

# administrativo
fazer_pedido_page = st.Page(
    "pages/Fazer_Pedido.py",
    title="Fazer Pedidos",
    icon=":material/universal_currency_alt:",
)
lanca_pedido_page = st.Page(
    "pages/1Lanca_Pedido.py", title="Lança Pedidos", icon=":material/add_shopping_cart:"
)
lanca_rp_page = st.Page(
    "pages/Pedido_RP.py", title="Lança Pedidos RP", icon=":material/add_shopping_cart:"
)
divisao_page = st.Page(
    "pages/divisao.py", title="Divisão", icon=":material/prompt_suggestion:"
)
calcula_nf_page = st.Page(
    "pages/5Calcula_NF.py", title="Calcula NFe", icon=":material/calculate:"
)
plan_dev_page = st.Page(
    "pages/7Planilha_Dev.py",
    title="Planilha Devolução",
    icon=":material/assignment_return:",
)
pedidos_page = st.Page(
    "pages/4Pedidos.py", title="Pedidos Feitos", icon=":material/shopping_cart:"
)

trocas_page = st.Page(
    "pages/jira.py",
    title="Trocas e Devolucoes",
    icon=":material/swap_horizontal_circle:",
)


validade = st.Page("pages/Validade.py", title="Validade", icon=":material/date_range:")

# lista
lista_loja_page = st.Page(
    "pages/2Lista.py", title="Lista Lojas", icon=":material/shelves:"
)
lista_atacado_page = st.Page(
    "pages/3Atacado.py", title="Lista Atacado", icon=":material/local_mall:"
)

# financeiro
previa_financeira_page = st.Page(
    "pages/6Previa_Financeira.py", title="Previa Financeira", icon=":material/wallet:"
)

# Relatórios
Faturamento = st.Page(
    "pages/faturamento.py",
    title="Faturamento",
    icon=":material/universal_currency_alt:",
)

CMV = st.Page("pages/cmv.py", title="CMV", icon=":material/bar_chart:")

Evolucao_Vendas = st.Page(
    "pages/Evolucao_Vendas.py",
    title="Evolução de Vendas",
    icon=":material/work:",
)

resultados = st.Page(
    "pages/AR.py", title="Apresentação Resultado", icon=":material/area_chart:"
)


# logistica
print_guia_page = st.Page(
    "pages/GuiaCega.py", title="Guia Cega", icon=":material/adf_scanner:"
)
rotas_page = st.Page("pages/Rotas.py", title="Rotas", icon=":material/route:")

pages = {
    "Home": [login_page, home_page, margem_page],
    "Administrativo": [
        fazer_pedido_page,
        lanca_pedido_page,
        divisao_page,
        pedidos_page,
        calcula_nf_page,
        plan_dev_page,
        trocas_page,
        validade,
    ],
    "Logistica": [rotas_page, print_guia_page],
    "Lista": [lista_loja_page, lista_atacado_page],
    "Financeiro": [previa_financeira_page],
}


if st.session_state.perfil.get("role") == "administrador":
    pages["Relatórios"] = [Faturamento, CMV, Evolucao_Vendas, resultados]
    pages["Administrativo"].append(lanca_rp_page)

# --- CONFIGURAÇÃO PAGINA ---
pg = st.navigation(pages, position="top")
pg.run()
